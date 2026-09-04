import argparse
import csv
import io
import posixpath
import re
import sqlite3
import subprocess
import sys
import tarfile
from datetime import UTC, datetime, date, timedelta
from pathlib import Path

from amg import extractors

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
ARCHIVE_DATE = re.compile(r"_(\d{4})(\d{2})(\d{2})_\d{4}\.tar\.Z$")


def normalize_flight_date(flight_date, archive_name):
    if not flight_date:
        return None
    day_only = re.fullmatch(r"(\d{1,2})", flight_date)
    archive_match = ARCHIVE_DATE.search(archive_name)
    if not archive_match:
        return None
    year = int(archive_match.group(1))
    month = int(archive_match.group(2))
    archive_day = date(year, month, int(archive_match.group(3)))
    if day_only:
        try:
            flight_day = date(year, month, int(day_only.group(1)))
        except ValueError:
            return None
        if flight_day < archive_day:
            import calendar
            days_left_in_month = calendar.monthrange(year, month)[1] - archive_day.day
            forward_window_days = 2
            if days_left_in_month + int(day_only.group(1)) <= forward_window_days:
                month += 1
                year += (month - 1) // 12
                month = (month - 1) % 12 + 1
                try:
                    flight_day = date(year, month, int(day_only.group(1)))
                except ValueError:
                    return None
        return f"{flight_day:%Y%m%d}"
    match = re.fullmatch(r"(\d{1,2})([A-Z]{3})(\d{2})?", flight_date)
    if not match or match.group(2) not in MONTHS:
        return None
    day, month = int(match.group(1)), MONTHS[match.group(2)]
    if match.group(3):
        return f"{2000 + int(match.group(3)):04d}{month:02d}{day:02d}"
    flight_day = date(year, month, day)
    if (flight_day - archive_day).days > 183:
        flight_day = date(year - 1, month, day)
    return f"{flight_day:%Y%m%d}"

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY,
  received_at TEXT,
  station TEXT NOT NULL,
  status TEXT NOT NULL,
  msg_type TEXT NOT NULL DEFAULT 'OTHER',
  priority TEXT,
  destination TEXT,
  origin TEXT,
  flight_number TEXT,
  aircraft_reg TEXT,
  flight_airport TEXT,
  flight_date TEXT,
  part_number INTEGER,
  raw_text TEXT NOT NULL,
  raw_text_plain TEXT,
  parse_error TEXT,
  source_archive TEXT NOT NULL,
  source_file TEXT NOT NULL,
  UNIQUE (source_archive, source_file)
);
CREATE TABLE IF NOT EXISTS archives (
  name TEXT PRIMARY KEY,
  size INTEGER NOT NULL,
  ingested_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING
  fts5(raw_text, content='messages', content_rowid='id');
CREATE TABLE IF NOT EXISTS message_facts (
  message_id INTEGER PRIMARY KEY REFERENCES messages(id),
  family TEXT NOT NULL,
  facts_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS message_segments (
  id INTEGER PRIMARY KEY,
  message_id INTEGER NOT NULL REFERENCES messages(id),
  seq INTEGER NOT NULL,
  data_json TEXT NOT NULL
);
CREATE VIEW IF NOT EXISTS messages_readable AS
SELECT id, received_at, station, status, msg_type, priority, destination, origin,
       flight_number, aircraft_reg, flight_airport, flight_date, part_number,
       source_archive, source_file,
       replace(replace(replace(raw_text, char(1), ''), char(2), ''), char(3), '')
         AS message_text,
       replace(replace(replace(raw_text_plain, char(1), ''), char(2), ''), char(3), '')
         AS message_text_plain
FROM messages;
"""

# LDM facts that map onto AODB columns, in display order. The target column
# defaults to the fact's own name; INTERFACE_COLUMN_MAPPINGS remaps it (e.g.
# PAX -> AMG_PAX). These are the DB-facing fields from the AHM 583 spec.
LDM_COLUMN_FIELDS = [
    ("reg", "REG"),
    ("pax", "PAX"),
    ("si", "SI"),
    ("crew", "CRW"),
    ("ddl", "DDL"),
    ("px1", "PX1"),
    ("px2", "PX2"),
    ("px3", "PX3"),
    ("px6", "PX6"),
    ("px7", "PX7"),
]


def _remap_view_sql():
    """Build a view showing, per LDM, each DB column and the value that would
    land there after INTERFACE_COLUMN_MAPPINGS remapping.

    The target column comes from INTERFACE_COLUMN_MAPPINGS; facts it doesn't
    list keep their default column (documented above).
    """
    cols, selects = [], []
    for fact_key, default_col in LDM_COLUMN_FIELDS:
        up = fact_key.upper()
        target = extractors.INTERFACE_COLUMN_MAPPINGS.get(up, default_col)
        # The JSON key reflects the fact as persisted after apply_column_mappings:
        # remapped facts are stored under their target (AMG_*), unremapped ones
        # keep their natural lowercase name (px7, ddl, crew).
        stored = extractors.INTERFACE_COLUMN_MAPPINGS.get(up, fact_key)
        quoted = target.replace('"', '""')
        cols.append(f'"{quoted}"')
        selects.append(f"json_extract(f.facts_json, '$.{stored}') AS \"{quoted}\"")
    cols_sql = ", ".join(cols)
    selects_sql = ",\n       ".join(selects)
    # DROP first: the view's columns are baked in at CREATE time, so a rebuild
    # must recreate it whenever INTERFACE_COLUMN_MAPPINGS changes.
    return f"""
DROP VIEW IF EXISTS ldm_remap;
CREATE VIEW ldm_remap AS
SELECT r.id AS message_id, r.received_at, r.flight_number, r.flight_airport,
       {selects_sql}
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type = 'LDM';
"""


def build_schema():
    return SCHEMA + _remap_view_sql() + _pnl_view_sql()


PNL_VIEW_COLUMNS = [
    ("carrier", "carrier"),
    ("flight_no", "flight_number"),
    ("suffix", "suffix"),
    ("dep_day", "dep_day"),
    ("dep_month", "dep_month"),
    ("boarding_airport", "boarding_airport"),
    ("part_number", "part_number"),
    ("cfg", "cfg"),
    ("name_rows", "name_rows"),
    ("identifier_rows", "identifier_rows"),
    ("ssrs", "ssrs"),
    ("pxe", "pxe"),
    ("px6", "px6"),
    ("no_action", "no_action"),
    ("arrival_action", "arrival_action"),
    ("departure_action", "departure_action"),
    ("changes", "changes"),
]


def _pnl_view_sql():
    """Analytics view over structured PNL/ADL facts (RP 1708).

    Like ldm_remap but no INTERFACE_COLUMN_MAPPINGS involvement - NAME_LIST
    facts are never remapped, so every column reads its natural key. Adds a
    boarded total (`pax_on_board`) and destination-leg count derived from the
    per-segment rows.
    """
    selects = [f"json_extract(f.facts_json, '$.{key}') AS \"{col}\"" for col, key in PNL_VIEW_COLUMNS]
    selects_sql = ",\n       ".join(selects)
    return f"""
DROP VIEW IF EXISTS pnl_remap;
CREATE VIEW pnl_remap AS
SELECT r.id AS message_id, r.received_at, r.msg_type, r.flight_number,
       r.flight_airport, r.flight_date,
       {selects_sql},
       COALESCE(SUM(CASE WHEN json_valid(s.data_json) THEN
                       json_extract(s.data_json, '$.declared_total') END), 0)
         AS pax_on_board,
       COUNT(s.id) AS segment_count
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
LEFT JOIN message_segments s ON s.message_id = r.id
WHERE r.msg_type IN ('PNL', 'ADL')
GROUP BY r.id;
"""

FLIGHT_LINE = re.compile(
    r"^([A-Z0-9]{2,3}\d{1,4}[A-Z]?)/(\d{1,2})\.([A-Z0-9-]+)(?:\.([A-Z]{3}))?", re.ASCII
)
PNL_LINE = re.compile(
    r"^([A-Z0-9]{2,3}\d+[A-Z]?)/(\d{1,2}[A-Z]{3})\s+([A-Z]{3}(?:[A-Z]{3})?)"
    r"(?:\s+PART\s*(\d+))?",
    re.ASCII,
)
FWD_LINE = re.compile(
    r"^([A-Z0-9]{2,3}\d+[A-Z]?)/(\d{1,2})\.([A-Z]{3})(?![A-Z0-9])", re.ASCII
)
LDM_NEW_LINE = re.compile(
    r"^([A-Z0-9]{2,3}\d+[A-Z]?)/(\d{1,2}[A-Z]{3})(\d{2})?\.([A-Z0-9-]+)", re.ASCII
)
ASM_LINE = re.compile(
    r"^([A-Z0-9]{2,3}\d+[A-Z]?)/(\d{1,2}[A-Z]{3})(\d{2})(?:\s|$)", re.ASCII
)
KEYWORD_LINE = re.compile(r"^([A-Z]{3})(?:\s+(.*))?$")
GLUED_KEYWORD_LINE = re.compile(
    r"^(FWD|ASM|MVT|MVA|DIV|LDM|PTM|PNL|ADL|PSM|PAL|CAL)(\w+/\S.*)$"
)


def parse_received_at(stem):
    try:
        dt = datetime.strptime(stem[:12], "%y%m%d%H%M%S")
        if len(stem) == 15:
            return f"{dt:%Y-%m-%dT%H:%M:%S}.{stem[12:]}"
    except ValueError:
        pass
    try:
        dt = datetime.strptime(stem[:14], "%Y%m%d%H%M%S")
        return f"{dt:%Y-%m-%dT%H:%M:%S}.{stem[14:].ljust(3, '0')}"
    except ValueError:
        return None


def status_for(suffix):
    if suffix.lower() == ".cor":
        return "corrupted"
    return "processed"


CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f]")


def _match_flight_dot(line):
    match = FLIGHT_LINE.match(line)
    if not match:
        return None
    return {
        "flight_number": match.group(1),
        "flight_date": match.group(2),
        "aircraft_reg": match.group(3),
        "flight_airport": match.group(4),
    }


def _match_pnl_style(line):
    match = PNL_LINE.match(line)
    if not match:
        return None
    return {
        "flight_number": match.group(1),
        "flight_date": match.group(2),
        "flight_airport": match.group(3),
        "part_number": int(match.group(4)) if match.group(4) else None,
    }


def _match_fwd(line):
    match = FWD_LINE.match(line)
    if not match:
        return None
    return {
        "flight_number": match.group(1),
        "flight_date": match.group(2),
        "flight_airport": match.group(3),
    }


def _match_ldm_new(line):
    match = LDM_NEW_LINE.match(line)
    if not match:
        return None
    year_suffix = match.group(3) or ""
    return {
        "flight_number": match.group(1),
        "flight_date": match.group(2) + year_suffix,
        "aircraft_reg": match.group(4),
    }


def _match_asm(line):
    match = ASM_LINE.match(line)
    if not match:
        return None
    return {
        "flight_number": match.group(1),
        "flight_date": match.group(2) + match.group(3),
    }


CATEGORY_PARSERS = {
    "FWD": (_match_fwd, _match_flight_dot, _match_pnl_style),
    "LDM": (_match_ldm_new, _match_flight_dot, _match_pnl_style),
    "ASM": (_match_asm, _match_flight_dot, _match_pnl_style),
}
DEFAULT_PARSERS = (_match_flight_dot, _match_pnl_style)


def parse_envelope(raw_text):
    lines = [CONTROL_CHARS.sub("", line) for line in raw_text.splitlines()]
    priority = destination = origin = None
    header = next((line for line in lines if line.strip()), "")
    priority_dest = header.split(None, 1)
    if len(priority_dest) == 2 and re.fullmatch(r"[A-Z]{2}", priority_dest[0]):
        priority, destination = priority_dest[0], priority_dest[1].strip()

    keyword_index = None
    keyword_rest = None
    msg_type = "OTHER"
    for i, line in enumerate(lines):
        stripped = line.strip()
        match = KEYWORD_LINE.match(stripped) or GLUED_KEYWORD_LINE.match(stripped)
        if match:
            msg_type, keyword_index, keyword_rest = match.group(1), i, match.group(2)
            break

    if keyword_index is not None:
        for line in reversed(lines[:keyword_index]):
            if line.startswith(".") and len(line) > 1:
                origin = line[1:].split()[0]
                break

    flight_number = aircraft_reg = flight_airport = None
    flight_date = part_number = None
    if keyword_index is not None:
        candidates = ([keyword_rest] if keyword_rest else []) + lines[keyword_index + 1 :]
        parsers = CATEGORY_PARSERS.get(msg_type, DEFAULT_PARSERS)
        for line in candidates:
            fields = None
            for parser in parsers:
                fields = parser(line.strip())
                if fields:
                    break
            if fields:
                flight_number = fields.get("flight_number")
                aircraft_reg = fields.get("aircraft_reg")
                flight_airport = fields.get("flight_airport")
                flight_date = fields.get("flight_date")
                part_number = fields.get("part_number")
                break

    return {
        "msg_type": msg_type,
        "priority": priority,
        "destination": destination,
        "origin": origin,
        "flight_number": flight_number,
        "aircraft_reg": aircraft_reg,
        "flight_airport": flight_airport,
        "flight_date": flight_date,
        "part_number": part_number,
    }


def ingest_archive(archive_path, con):
    result = subprocess.run(
        ["tar", "-cf", "-", f"@{archive_path.as_posix()}"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"tar failed on {archive_path.name}: {result.stderr.decode(errors='replace').strip()}"
        )
    rows = []
    fact_rows = []
    segment_rows = []
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            rel = posixpath.normpath(member.name).lstrip("./")
            station = posixpath.dirname(rel) or "-"
            stem, suffix = posixpath.splitext(posixpath.basename(rel))
            parse_error = None
            extraction = None
            plain = None
            try:
                original = tar.extractfile(member).read().decode("latin-1")
                envelope = parse_envelope(original)
                extraction = extractors.extract_message(envelope["msg_type"], original)
                raw = extractors.redact_text(envelope["msg_type"], original) or original
                plain = original
            except Exception as error:
                raw = ""
                envelope = {"msg_type": "OTHER", "priority": None, "destination": None,
                            "origin": None, "flight_number": None, "aircraft_reg": None,
                            "flight_airport": None, "flight_date": None,
                            "part_number": None}
                parse_error = f"{type(error).__name__}: {error}"
            if extraction:
                fact_rows.append((rel, extraction["family"],
                                  extractors.dumps(extraction["facts"]),
                                  extraction["segments"]))
            rows.append(
                (
                    parse_received_at(stem),
                    station,
                    status_for(suffix),
                    envelope["msg_type"],
                    envelope["priority"],
                    envelope["destination"],
                    envelope["origin"],
                    envelope["flight_number"],
                    envelope["aircraft_reg"],
                    envelope["flight_airport"],
                    normalize_flight_date(envelope["flight_date"], archive_path.name),
                    envelope["part_number"],
                    raw,
                    plain,
                    parse_error,
                    archive_path.name,
                    rel,
                )
            )
    con.executemany(
        "INSERT OR IGNORE INTO messages"
        " (received_at, station, status, msg_type, priority, destination, origin,"
        "  flight_number, aircraft_reg, flight_airport, flight_date, part_number,"
        "  raw_text, raw_text_plain, parse_error, source_archive, source_file)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    if fact_rows:
        id_by_file = dict(con.execute(
            "SELECT source_file, id FROM messages WHERE source_archive = ?",
            (archive_path.name,),
        ))
        fact_values = []
        segment_values = []
        for rel, family, facts_json, segments in fact_rows:
            message_id = id_by_file.get(rel)
            if message_id is None:
                continue
            fact_values.append((message_id, family, facts_json))
            for seq, data in enumerate(segments):
                segment_values.append((message_id, seq, extractors.dumps(data)))
        con.executemany(
            "INSERT OR REPLACE INTO message_facts (message_id, family, facts_json)"
            " VALUES (?, ?, ?)",
            fact_values,
        )
        con.executemany(
            "INSERT INTO message_segments (message_id, seq, data_json)"
            " VALUES (?, ?, ?)",
            segment_values,
        )
    con.execute(
        "INSERT OR REPLACE INTO archives (name, size, ingested_at) VALUES (?, ?, ?)",
        (archive_path.name, archive_path.stat().st_size, datetime.now(UTC).isoformat()),
    )


def ingest_archives(archive_paths, db_path, progress=None, should_stop=None):
    _probe_writable(db_path)
    con = sqlite3.connect(db_path)
    con.executescript(build_schema())
    _migrate(con)
    seen = dict(con.execute("SELECT name, size FROM archives"))
    ingested = skipped = failed = 0
    done = 0
    total = len(archive_paths)
    for archive_path in archive_paths:
        if should_stop and should_stop():
            break
        if seen.get(archive_path.name) == archive_path.stat().st_size:
            skipped += 1
        else:
            try:
                ingest_archive(archive_path, con)
                con.commit()
                ingested += 1
            except Exception as error:
                con.rollback()
                print(f"failed to ingest {archive_path.name}: {error}", file=sys.stderr)
                failed += 1
        done += 1
        if progress:
            progress(done, total, ingested, skipped, failed)
    fts_stale = con.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0] != con.execute(
        "SELECT COUNT(*) FROM messages"
    ).fetchone()[0]
    if ingested or fts_stale:
        con.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
        con.commit()
    con.close()
    return ingested, skipped, failed


def _migrate(con):
    """Bring an existing DB up to the current schema.

    ``CREATE TABLE IF NOT EXISTS`` never adds columns to a table that already
    exists and never replaces an existing view, so older databases need
    explicit migration here. Currently adds ``messages.raw_text_plain`` and
    re-creates ``messages_readable`` to expose it.
    """
    cols = {c[1] for c in con.execute("PRAGMA table_info(messages)")}
    if "raw_text_plain" not in cols:
        con.execute("ALTER TABLE messages ADD COLUMN raw_text_plain TEXT")
    # Always rebuild the readable view so it tracks the current column set.
    con.execute("DROP VIEW IF EXISTS messages_readable")
    con.executescript(build_schema())
    con.commit()


def _probe_writable(db_path):
    try:
        con = sqlite3.connect(db_path, timeout=5.0)
        con.execute("BEGIN IMMEDIATE")
        con.commit()
        con.close()
    except sqlite3.OperationalError as error:
        raise RuntimeError(
            f"database {db_path} is locked - close DB Browser or any other"
            " program using it, then try again"
        ) from error


def rebuild_archives(archive_paths, db_path, progress=None, should_stop=None):
    _probe_writable(db_path)
    con = sqlite3.connect(db_path)
    con.executescript(build_schema())
    _migrate(con)
    # Clear every derived table, not just the message table: message ids restart
    # at 1 after the delete (no AUTOINCREMENT), so stale fact/segment rows from a
    # previous run would otherwise collide with the freshly re-ingested rows.
    con.execute("DELETE FROM message_segments")
    con.execute("DELETE FROM message_facts")
    con.execute("DELETE FROM messages")
    con.execute("DELETE FROM archives")
    con.commit()
    # Reclaim the pages freed by the DELETEs above. DELETE alone leaves the file
    # sized as-is; VACUUM rewrites it so a Full rebuild also shrinks the file.
    con.execute("VACUUM")
    con.close()
    return ingest_archives(archive_paths, db_path, progress=progress,
                           should_stop=should_stop)


def cmd_ingest(args):
    paths = sorted(Path(args.archive_dir).glob("*.tar.Z"))
    if args.only:
        wanted = set(args.only)
        paths = [p for p in paths if p.name in wanted]
    try:
        ingested, skipped, failed = ingest_archives(paths, Path(args.db))
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    print(
        f"ingest summary: {ingested} ingested, {skipped} skipped, {failed} failed",
        file=sys.stderr,
    )
    if failed and (ingested or skipped):
        return 3
    if failed:
        return 1
    return 0


def scan_archives(archive_dir, db_path):
    indexed = {}
    if Path(db_path).exists():
        con = sqlite3.connect(db_path)
        try:
            indexed = dict(con.execute("SELECT name, size FROM archives"))
        finally:
            con.close()
    entries = []
    for archive_path in sorted(Path(archive_dir).glob("*.tar.Z")):
        size_bytes = archive_path.stat().st_size
        entries.append({
            "name": archive_path.name,
            "size_bytes": size_bytes,
            "state": "indexed" if indexed.get(archive_path.name) == size_bytes else "pending",
        })
    return entries


def cmd_status(args):
    con = sqlite3.connect(args.db)
    indexed = {name for (name,) in con.execute("SELECT name FROM archives")}
    con.close()
    for archive_path in sorted(Path(args.archive_dir).glob("*.tar.Z")):
        state = "indexed" if archive_path.name in indexed else "pending"
        print(f"{archive_path.name} {state}")
    return 0


def cmd_search(args):
    con = sqlite3.connect(args.db)
    where, params = [], []
    joins = ""
    if args.q:
        joins = "JOIN messages_fts f ON f.rowid = m.id"
        where.append("messages_fts MATCH ?")
        params.append(args.q)
    if args.type:
        where.append("m.msg_type = ?")
        params.append(args.type.upper())
    if args.flight:
        where.append("m.flight_number = ?")
        params.append(args.flight.upper())
    if args.origin:
        where.append("m.origin = ?")
        params.append(args.origin.upper())
    if args.dest:
        where.append("m.destination = ?")
        params.append(args.dest.upper())
    if args.status:
        where.append("m.status = ?")
        params.append(args.status)
    if args.from_date:
        where.append("m.received_at >= ?")
        params.append(args.from_date)
    if args.to_date:
        to = args.to_date
        if len(to) == 10:
            to += "T23:59:59.999"
        where.append("m.received_at <= ?")
        params.append(to)
    sql = (
        "SELECT m.id, m.received_at, m.station, m.status, m.msg_type, m.priority,"
        " m.destination, m.origin, m.flight_number, m.aircraft_reg,"
        " m.source_archive, m.source_file"
        f" FROM messages m {joins}"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY m.received_at DESC, m.id DESC"
    )
    rows = con.execute(sql, params).fetchall()
    out = sys.stdout
    if args.csv:
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(
            [
                "id", "received_at", "station", "status", "msg_type", "priority",
                "destination", "origin", "flight_number", "aircraft_reg",
                "source_archive", "source_file",
            ]
        )
        writer.writerows(rows)
    else:
        out.write("id received_at status type flight origin\n")
        for row in rows:
            out.write(
                f"{row[0]} {row[1] or '-'} {row[3]} {row[4]}"
                f" {row[8] or '-'} {row[7] or '-'}\n"
            )
    con.close()
    return 0


def cmd_show(args):
    con = sqlite3.connect(args.db)
    column = "raw_text_plain" if getattr(args, "plain", False) else "raw_text"
    row = con.execute(
        f"SELECT {column} FROM messages WHERE id = ?", (args.message_id,)
    ).fetchone()
    con.close()
    if row is None:
        print(f"no message with id {args.message_id}", file=sys.stderr)
        return 1
    sys.stdout.write(row[0] or "")
    return 0


STATS_BUCKET = {
    "day": "substr(received_at, 1, 10)",
    "hour": "substr(received_at, 1, 13)",
    "type": "msg_type",
    "airline": (
        "COALESCE(NULLIF(upper(substr(flight_number, 1,"
        " length(flight_number) - length(ltrim(flight_number, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ')))), ''), '-')"
    ),
}


def cmd_stats(args):
    con = sqlite3.connect(args.db)
    bucket = STATS_BUCKET[args.by]
    split_status = args.by in ("day", "hour")
    select = (
        f"SELECT COALESCE({bucket}, '-') AS bucket, COUNT(*) AS total"
        + (", SUM(m.status = 'processed'), SUM(m.status = 'corrupted')" if split_status else "")
        + f" FROM messages m GROUP BY bucket ORDER BY (bucket = '-') ASC,"
        + (" bucket ASC" if split_status else " total DESC, bucket ASC")
    )
    rows = con.execute(select).fetchall()
    out = sys.stdout
    if args.csv:
        writer = csv.writer(out, lineterminator="\n")
        header = [args.by, "total"] + (["processed", "corrupted"] if split_status else [])
        writer.writerow(header)
        writer.writerows(rows)
    else:
        out.write(
            f"{args.by} total"
            + (" processed corrupted" if split_status else "")
            + "\n"
        )
        for row in rows:
            out.write(" ".join(str(v) for v in row) + "\n")
    con.close()
    return 0


def cmd_gui(args):
    from amg.gui import run_gui

    return run_gui(Path(args.archive_dir), Path(args.db))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="amg")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="ingest archives into the index")
    p_ingest.add_argument("archive_dir")
    p_ingest.add_argument("--db", required=True)
    p_ingest.add_argument(
        "--only", nargs="*", metavar="NAME",
        help="import just these archive file names instead of the whole folder",
    )

    p_search = sub.add_parser("search", help="search indexed messages")
    p_search.add_argument("--db", required=True)
    p_search.add_argument("--type", dest="type")
    p_search.add_argument("--flight")
    p_search.add_argument("--origin")
    p_search.add_argument("--dest")
    p_search.add_argument("--status", choices=["processed", "corrupted"])
    p_search.add_argument("--from", dest="from_date", metavar="FROM")
    p_search.add_argument("--to", dest="to_date", metavar="TO")
    p_search.add_argument("--q", help="full-text query over message bodies")
    p_search.add_argument("--csv", action="store_true")

    p_show = sub.add_parser("show", help="print the full raw text of one message")
    p_show.add_argument("--db", required=True)
    p_show.add_argument("--plain", action="store_true",
                        help="print the stored un-redacted plaintext instead of the redacted text")
    p_show.add_argument("message_id", type=int)

    p_stats = sub.add_parser("stats", help="aggregate statistics over the index")
    p_stats.add_argument("--db", required=True)
    p_stats.add_argument(
        "--by", required=True, choices=["day", "hour", "type", "airline"]
    )
    p_stats.add_argument("--csv", action="store_true")

    p_status = sub.add_parser("status", help="show indexed vs pending archives")
    p_status.add_argument("--db", required=True)
    p_status.add_argument("--archive-dir", required=True)

    p_gui = sub.add_parser("gui", help="open a window to pick archives to import")
    p_gui.add_argument("--archive-dir", default="AMG_msg")
    p_gui.add_argument("--db", default="amg_messages.db")

    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_request:
        return exit_request.code
    handlers = {
        "ingest": cmd_ingest,
        "search": cmd_search,
        "show": cmd_show,
        "stats": cmd_stats,
        "status": cmd_status,
        "gui": cmd_gui,
    }
    return handlers[args.command](args)


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
        flight_day = date(year, month, int(day_only.group(1)))
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
         AS message_text
FROM messages;
"""

FLIGHT_LINE = re.compile(
    r"^([A-Z0-9]{2,3}\d+[A-Z]?)/\d+\.([A-Z0-9]+)(?:\.([A-Z]{3}))?", re.ASCII
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
    r"^([A-Z0-9]{2,3}\d+[A-Z]?)/(\d{1,2}[A-Z]{3})(\d{2})?\.([A-Z0-9]+)", re.ASCII
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
        "aircraft_reg": match.group(2),
        "flight_airport": match.group(3),
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
            try:
                original = tar.extractfile(member).read().decode("latin-1")
                envelope = parse_envelope(original)
                extraction = extractors.extract_message(envelope["msg_type"], original)
                raw = extractors.redact_text(envelope["msg_type"], original) or original
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
                    parse_error,
                    archive_path.name,
                    rel,
                )
            )
    con.executemany(
        "INSERT OR IGNORE INTO messages"
        " (received_at, station, status, msg_type, priority, destination, origin,"
        "  flight_number, aircraft_reg, flight_airport, flight_date, part_number,"
        "  raw_text, parse_error, source_archive, source_file)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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


def ingest_archives(archive_paths, db_path):
    _probe_writable(db_path)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    seen = dict(con.execute("SELECT name, size FROM archives"))
    ingested = skipped = failed = 0
    for archive_path in archive_paths:
        if seen.get(archive_path.name) == archive_path.stat().st_size:
            skipped += 1
            continue
        try:
            ingest_archive(archive_path, con)
            con.commit()
            ingested += 1
        except Exception as error:
            con.rollback()
            print(f"failed to ingest {archive_path.name}: {error}", file=sys.stderr)
            failed += 1
    fts_stale = con.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0] != con.execute(
        "SELECT COUNT(*) FROM messages"
    ).fetchone()[0]
    if ingested or fts_stale:
        con.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
        con.commit()
    con.close()
    return ingested, skipped, failed


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


def rebuild_archives(archive_paths, db_path):
    _probe_writable(db_path)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    con.execute("DELETE FROM messages")
    con.execute("DELETE FROM archives")
    con.commit()
    con.close()
    return ingest_archives(archive_paths, db_path)


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
    row = con.execute(
        "SELECT raw_text FROM messages WHERE id = ?", (args.message_id,)
    ).fetchone()
    con.close()
    if row is None:
        print(f"no message with id {args.message_id}", file=sys.stderr)
        return 1
    sys.stdout.write(row[0])
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


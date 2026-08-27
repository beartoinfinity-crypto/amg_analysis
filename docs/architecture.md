# AMG Message Toolkit - Internals Reference

This document is the map for further development: every function, the logic
behind it, and the traps to avoid. For user-facing documentation see
`README.md`.

## Module layout

```
amg/cli.py      core: parsing, ingestion, query commands, argparse entry point
amg/extractors.py per-family extractors: MVT, LDM, DIV, PTM, PSM/PAL/CAL, PNL/ADL, FWD, ASM
amg/gui.py      thin tkinter layer over cli core functions (no business logic)
amg/__main__.py enables `python -m amg`
tests/          pytest suite; drives only public seams (CLI + database schema)
run.bat         double-click launcher -> `python -m amg gui`
```

Design stance: **one deep module** (`cli.py`) behind one seam (`main(argv)`).
The GUI and any future interface must stay thin clients over the same core
functions so behaviour has exactly one home and tests exercise reality.

---

## Entry point and command surface

### `main(argv=None) -> int`

- Builds one argparse tree with subcommands: `ingest`, `search`, `show`,
  `stats`, `status`, `gui`.
- `parse_args` failures raise `SystemExit`; we catch it and **return its code**
  (argparse uses 2) instead of killing the process - callers (tests, GUI,
  console script) always get an integer.
- Dispatches via a handler dict `{command: cmd_*}`, not an if-cascade.
- Exit codes contract:

| Code | Meaning |
| --- | --- |
| 0 | clean |
| 2 | argument error (from argparse) |
| 1 | total failure OR database locked |
| 3 | partial failure (some archives failed, others succeeded/skipped) |

### `__main__.py` and `[project.scripts]`

Both exist so `python -m amg ...` and (after `pip install -e .`) a real `amg`
command work. Keep them in sync if the package layout ever changes.

---

## Database schema (SCHEMA constant)

```sql
messages(id PK, received_at TEXT NULL, station NOT NULL, status NOT NULL,
         msg_type DEFAULT 'OTHER', priority, destination, origin,
         flight_number, aircraft_reg, flight_airport, flight_date,
         part_number INTEGER, raw_text NOT NULL, parse_error,
         source_archive NOT NULL, source_file NOT NULL,
         UNIQUE (source_archive, source_file))
archives(name PK, size INTEGER NOT NULL, ingested_at TEXT NOT NULL)
messages_fts  fts5(raw_text, content='messages', content_rowid='id')
message_facts(message_id PK REFERENCES messages(id), family NOT NULL,
              facts_json TEXT NOT NULL)
message_segments(id PK, message_id NOT NULL REFERENCES messages(id),
                 seq INTEGER NOT NULL, data_json TEXT NOT NULL)
VIEW messages_readable = messages + message_text (framing bytes stripped)
```

Column meanings:

- `received_at` - ISO `YYYY-MM-DDTHH:MM:SS.mmm`, derived from the inner
  filename stem; NULL for non-timestamp filenames (sequence numbers).
- `station` - inner folder name (always `HKG` in this corpus; `-` fallback).
- `status` - `processed` (`.rcv`) / `corrupted` (`.COR`) by extension only;
  the PROCESSED_/CORRUPTED_ archive prefix is redundant metadata, extension is
  the per-file truth.
- `msg_type` - three-letter keyword from the body; `OTHER` when none found.
- `parse_error` - populated when reading/parsing a member raised; row still
  stored with empty text. Rarely triggered; exists so bad data never aborts
  an archive import.

**Adding a column checklist** (the one data-clump to respect): touch ALL of -
`SCHEMA`, `messages_readable` view, `parse_envelope` return dict, the
exception-fallback dict inside `ingest_archive`, the row tuple + `INSERT`
column list, `tests/test_parsing.py::ingest_one` SELECT, and the
`envelope()` expectation helper. Missing one shows up as either an
OperationalError (no such column) or silently None fields.

---

## Filename and date handling

### `parse_received_at(stem) -> str|None`

Filename shapes seen in the corpus (census-complete):

1. `YYMMDDHHMMSSmmm` (majority, 15 digits) - `%y%m%d%H%M%S` + literal millis.
2. `YYYYMMDDHHMMSS` + optional extra digits (12 files) - `%Y%m%d%H%M%S`,
   fraction zero-padded to 3.
3. Pure sequence numbers (10 files) - unparseable -> `NULL`.

Try shape 1 then shape 2; anything else NULL. Never raise.

### `normalize_flight_date(flight_date, archive_name) -> str|None`

Converts an info-line date like `13MAY`, `16MAY26` to `YYYYMMDD`.

- `DDMMMYY` (explicit year in the message) wins outright: `2000 + YY`.
- `DDMMM` without year: take year from the **archive filename** via
  `ARCHIVE_DATE = r"_(\d{4})(\d{2})(\d{2})_\d{4}\.tar\.Z$"`.
- Wrap rule: if the constructed date lies more than 183 days after the
  archive's own date, use the previous year (a `28DEC` flight in a January
  archive belongs to December just gone).
- Day-only dates (FWD `28`, LDM `31`) have no month: take the archive's
  month. Forward-window rule: if the remaining days in the archive's month
  plus the day value is ≤ 48 hours (`forward_window_days = 2`), roll into
  the next month. E.g. day-31 in a 30-day-month archive → 1st of next month;
  day-31 in a 31-day-month archive → stays 31st. Unknown months -> NULL.
  Never raise.

---

## Envelope parsing

### Framing

Real Type B messages carry `\r\n` line endings plus framing bytes: `\x01`
(SOH) prefixes address lines, `\x02` (STX) prefixes the type keyword itself,
`\x03` (ETX) terminates. `CONTROL_CHARS = [\x00-\x08\x0b-\x1f]` is stripped
**per line for matching only**; stored `raw_text` stays byte-verbatim
(latin-1). Fixtures written as clean `\n` text also parse - the strip makes
both worlds work.

### `KEYWORD_LINE = ^([A-Z]{3})(?:\s+(.*))?$`

Any standalone-or-prefixed three-letter uppercase word is the type keyword.
This replaced a fixed MESSAGE_TYPES set: it generalises to types we have
never seen (ADL, LPM, MVH appeared later). Requiring exactly-three-then-
boundary keeps body markers out: `SI` (2), `ULD.` (followed by dot), `CHKD`
(4 letters) never match. First match wins; `group(2)` is the inline remainder
used as the first flight-info candidate.

### Origin / priority

- Priority/destination: first **non-empty** line split once; accepted only if
  the first token is exactly two uppercase letters (`QU HKGTSXH`). Leading
  blank lines are common, hence "first non-empty".
- Origin: last line starting with `.` before the keyword line, first token
  after the dot (`HKGODCI`). Scanned backwards so SOH continuation blocks
  resolve to the final sending address.

### Per-category info-line parsers

Matchers are small functions returning field dicts (or None). Ordering is
**most specific type first, generic last** - a wrong-but-matching generic
regex is how `NRT` ended up in `aircraft_reg` for FWD messages historically.

| Matcher | Regex | Used by | Returns |
| --- | --- | --- | --- |
| `_match_fwd` | `FWD_LINE`: `FLIGHT/\d{1,2}.([A-Z]{3})(?![A-Z0-9])` | FWD first | flight_airport from segment 2 |
| `_match_ldm_new` | `LDM_NEW_LINE`: `FLIGHT/DDMMM(\d{2})?.REG` | LDM first | flight, raw date (+YY), reg |
| `_match_asm` | `ASM_LINE`: `FLIGHT/DDMMM(\d{2})(?:\s\|$)` | ASM first | flight, raw date |
| `_match_flight_dot` | `FLIGHT_LINE`: `FLIGHT/\d{1,4}.REG(.AIRPORT)?` | everyone (generic) | flight, reg, airport |
| `_match_pnl_style` | `PNL_LINE`: `FLIGHT/DDMMM AIRPORT[PAIR]( PARTn)?` | everyone (generic) | flight, raw date, airport/city-pair, part |

`CATEGORY_PARSERS` gates the specific ones: FWD/LDM/ASM get their matcher
prepended; everything else gets `DEFAULT_PARSERS`. The candidate list is
`[keyword-line remainder] + all subsequent lines`; scanning stops at the
first matcher hit.

Regex discipline learned the hard way:

- Boundaries matter. `([A-Z]{3})(?:\s|$)` broke on `.NRT.3/3/7`; use negative
  lookahead `(?!...)` when the token may be followed by punctuation.
- Group indices must match the regex. An off-by-one `group(4)` raised
  IndexError inside `ingest_archive`'s try-block, which silently produced an
  OTHER row with `parse_error` set - the symptom was "type vanished", the
  cause was invisible until the fallback was understood.
- Optional segments (`(?:\.([A-Z]{3}))?` for MVT airports) deliberately
  reject non-airport tokens like `.42/198` - garbage stays NULL rather than
  being stored.

### `parse_envelope(raw_text) -> dict`

Pipeline: strip control chars per line -> priority/destination from header ->
keyword scan -> origin scan backwards -> build candidate list -> run category
parser chain -> return dict of msg_type/priority/destination/origin/
flight_number/aircraft_reg/flight_airport/flight_date/part_number. Raw date
strings leave this function unnormalised; conversion happens at insert time
because only there is the archive name known.

---

## Per-family extractors (`amg/extractors.py`)

Pure functions: message text in, structured facts out. No database access.
`CATEGORY_PARSERS` in `cli.py` dispatches to the right extractor by keyword;
each returns a dict that becomes `message_facts.facts_json` (scalar facts) and
optionally `message_segments.data_json` rows (repeating data).

### `extract_movement(raw_text) -> dict`

Covers MVT and MVA. Parses:

- **AHM 780 times** via `_times(raw_text)`: scans lines for time codes
  (`AD`, `EA`, `EO`, `EL`, `TD`, `AA`, `ED`, `RA`, etc.). Each time code
  becomes `{"time":"1939","date":null}`. Special cases:
  - `AD1654/1712` → `AD` = off-blocks, pair value → `EO` (estimated off-blocks)
  - `EA1834` → `EL` (estimated landing)
  - `AA1612/1624` without explicit `TD` → `TD` = touchdown (first), `AA` = on-blocks (second)
  - `AA1612/1624` with explicit `TD` token → `TD` from token (wins), `AA` = on-blocks
  - 6-digit forms (`AD070110`) → `time: "0110"`, `date: "07"`
- **Destination**: airport code after a time line (3-letter IATA after `EA`/`AD`/`AA`).
- **Delay slots** via `_delay_slots(raw_text)`: `DL…` fills `IR1`/`DL1` pairs,
  `EDL…` continues at `IR3`/`DL3`+, `DLA…` adds code-only entries at `IR5`+.
  Legacy flat lists (`delay_codes`, `delay_durations`) kept for compatibility.
- **PAX**: `PX30/185` → transit + disembarking + total; `PAX215+0INF` → total + infants.
- **SI section** via `_si_section(raw_text)`: after an `SI` marker line, scans
  for known keys (`FR` fuel remaining, `EET` elapsed time, `BO` burn-off,
  `TOF` takeoff fuel, `PL` payload, `ZFW` zero fuel weight) as glued or spaced
  values. Event lines like `SI DOOR CLSD 0455` captured as timestamped events.
  Leading-zero strings (`EET0122`) preserved as strings, not integers.

### `extract_diversion(raw_text) -> dict`

DIV: DVA/ETA from `DVA_ETA_RE`, POB count, CAN flag.

### `extract_load(raw_text) -> (dict, [dict])`

LDM (AHM 583) covers full load messages. Returns flat facts and one row per
destination segment. Sub-functions:

- **`_ldm_header(raw_text)`** - parses the info line via `LDM_HEADER_RE`:
  `CARRIER/DD[MMMYY].REG.TYPE[.CREW_CKPT/CREW_CAB[/CREW_CAB_F]]`. Handles 2-part
  and 3-part crew tokens (female cabin subset optional); cabin config (e.g.
  `J12C30Y200`, `Y189`) captured via `cabins` using the shared
  `CABIN_RUN_RE`/`CABIN_PAIR_RE`; day accepts `DD` or `DDMMMYY`.
- **`_parse_ldm_segments(raw_text)`** - each `-DEST` line opens a segment;
  dot-continuation lines (starting `.`) extend the current one. Per token
  (via `_parse_ldm_segment_tokens`):
  - `.NIL` → `nil_traffic` (excluded from aggregation, stored as zeros)
  - `T<digits>` → deadload weight
  - `PAX/a/b` or `PAX/a/b/c` → cabin classes (First/Business/Economy);
    single `PAX/n` ignored (redundant total)
  - `PAD/...` → pad classes (positional, same 2/3-value forms)
  - `\d+/\d+/\d+` or `\d+/\d+/\d+/\d+` → pax breakdown. 3-part =
    adults/children/infants; 4-part = male/female/child/infant (adults =
    male+female).
  - `\d+/\d+` → compartment weight (ignored for pax)
  - `[A-Z]{3}/count[/weight]` → special category (HUM, EIC, etc.)
- **`_aggregate_load(segments)`** - runs the multi-leg aggregation from the
  spec. `local_station` defaults to HKG; if HKG absent, falls back to the
  first listed destination (station-absence safety). Transit = downstream
  segments after the local in route order; `.NIL` segments contribute zero.
  Outputs flat DB-column keys: `px7` (local), `px6` (transit), `pax` (total =
  AMG_PAX), `px1`/`px2`/`px3` (class totals from `PAX/` classes only - PAD is
  non-revenue and not summed), `ddl` (deadload total), `local_station`.
- **`_ldm_si(raw_text)`** - captures the free-text SI remarks block (stops at
  `END` or the ETX marker). Also parses the per-station breakdown line
  `STATION FRE n POS n BAG p[/w] TRA n` into `station_breakdown`
  (`fre`/`pos`/`bag`/`bag_weight`/`tra`).

Facts keys: `reg`, `cabins`, `crew` (`{cockpit,cabin,total}`), `ac_type`,
`si`, `station_breakdown`, `px6`, `px7`, `pax`, `px1`-`px3`, `ddl`,
`local_station`, `basic_weight`, `balance_index`. These are the field names
`INTERFACE_COLUMN_MAPPINGS` remaps (e.g. `PAX`→`AMG_PAX`, `REG`→`AMG_REG`,
`SI`→`AMG_SIT`) via `apply_column_mappings`.

### `extract_transfer(raw_text) -> (dict, [dict])`

PTM: total transfers, total baggage, per-transfer segments stored in
`message_segments`. Names are partially redacted (policy: names stripped,
assist codes kept).

### `extract_assistance(raw_text) -> dict`

PSM/PAL/CAL: assist codes list. CAL also captures delta ops and pax total.

### `extract_name_list(raw_text) -> (dict, str)`

PNL/ADL: counts name rows and identifier rows (or ADL changes). Returns
facts dict and a fully-redacted text skeleton. Zero PII in storage.

### `extract_forward(raw_text) -> (dict, [dict])`

FWD: crew, multi-hop destinations via `FWD_DASH_DEST_RE`, per-block components
(`.B`/`.R`/`.A`/`.L`/`.T`), nationalities per-block + merged. Transfer rows
stored in `message_segments`.

### `validate(facts_json, family) -> [str]`

Post-extraction validation. Catches 0-destination FWD, negative PAX, payload
exceeding MTOW, etc. Returns a list of warning strings (empty = clean).

### `redact_text(text, family) -> str`

PII redaction: PNL/ADL fully redacted (count-only); PTM/PSM/PAL/CAL partial
(names stripped, assist codes kept). Redaction runs on `raw_text` before
storage — verified zero leaks on MR/MRS/ticket/passport pattern sweeps.

---

## Ingestion

### `ingest_archive(archive_path, con)`

Performance-critical shape: Python's stdlib cannot read LZW-compressed
`.tar.Z`, but system bsdtar can. Instead of extracting to disk (measured
~52s/archive on this corpus due to per-file FS overhead), we run
`tar -cf - @<path>` which copy-converts the archive to an uncompressed tar
**in memory** (~0.2s), then stream members via
`tarfile.open(fileobj=BytesIO(...), mode="r:")` (~0.1s). Whole corpus drops
from 30+ minutes to ~60 seconds. Requires `tar` on PATH (documented).

Per member: skip non-files, normalise leading `./`, station = posix dirname,
stem/suffix from basename, latin-1 decode, `parse_envelope`, append row tuple.
A try/except around read+parse records `parse_error` and stores an OTHER row
instead of aborting the archive. Rows go in with `INSERT OR IGNORE` (dedupe),
then the archive row is `INSERT OR REPLACE`d into `archives`.

### `ingest_archives(archive_paths, db_path) -> (ingested, skipped, failed)`

1. `_probe_writable(db_path)` - fail fast with a human message if another
   program holds the DB (this exact failure shipped: rebuild wiped the index,
   then every archive write failed silently, leaving everything "pending").
   Probe = open with `timeout=5.0`, `BEGIN IMMEDIATE`, commit.
2. Create schema; load `seen = {name: size}` from `archives`.
3. Per path: skip when `seen[name] == current size` (same name AND size);
   otherwise ingest in its own transaction - commit on success, rollback +
   `failed++` on exception. Per-archive commits bound crash damage.
4. FTS staleness guard: rebuild whenever rows were added OR
   `count(messages_fts) != count(messages)` (a crash between data-commit and
   rebuild previously poisoned free-text search forever).

### `rebuild_archives(archive_paths, db_path)`

Probe FIRST, then `DELETE FROM messages` + `DELETE FROM archives`, then
delegate to `ingest_archives`. Deleting before probing would repeat the
locked-database disaster. Needed because plain re-ingest cannot update rows:
`INSERT OR IGNORE` keeps old parses alive under the unique constraint.

### `cmd_ingest(args)`

Glob `*.tar.Z` sorted; `--only NAME...` filters by basename (unknown names
are simply absent -> nothing ingested, exit 0). Prints the stderr summary
line; maps outcomes to exit codes; `RuntimeError` (locked DB) prints and
returns 1.

---

## Query commands

- `cmd_search` - WHERE-builder over typed filters; full-text joins
  `messages_fts` with `MATCH ?` against the table name (aliased join works
  despite the alias - verified against SQLite). Newest-first
  (`received_at DESC, id DESC`). CSV writer with stable column order.
- `cmd_show` - verbatim `raw_text` by id; missing id -> stderr + exit 1.
  Note: Windows text-mode stdout translates bare `\n` to `\r\n`; harmless for
  this corpus (raw text already uses CRLF everywhere) - revisit if that ever
  changes.
- `cmd_stats` - `STATS_BUCKET` maps `--by` to a SQL expression. Airline uses
  a leading-alpha prefix expression (ltrim charclass trick) so 3-letter
  carriers (DLH) survive; older version truncated to 2 chars. Split-by-status
  columns appear only for day/hour buckets. `'-'` (NULL bucket) always sorts
  LAST regardless of direction.
- `cmd_status` - name-set comparison against `archives` (no size check here;
  freshness view only).
- `scan_archives(archive_dir, db_path)` - GUI-facing state builder; indexed
  iff name+size both match. Missing DB file -> all pending, no error.

---

## GUI (`amg/gui.py`)

Thin by design: widget wiring only; all work happens in `ingest_archives` /
`rebuild_archives` / `scan_archives`.

- `ArchivePicker.__init__` builds Treeview whose first column is a checkbox
  glyph toggled by click (`on_click`) or the Select-all checkbutton.
- Pending archives pre-tick on `refresh()`; state text comes from
  `scan_archives`.
- `start_import` / `start_rebuild` confirm via messagebox, then call
  `run_in_background(paths, rebuild=False|True)`.
- Threading contract: sqlite + subprocess run on a daemon **worker thread**;
  the worker NEVER touches widgets directly - it posts UI updates through
  `root.after(0, ...)`. One `threading.Event` (`stop_event`) set by the Stop
  button ends the loop between archives (per-archive commits make that safe).
- Errors surface in the status bar via `finish_error` - an earlier version
  let exceptions kill the worker thread, leaving buttons dead and no
  explanation. Do not regress this.
- Buttons disable while busy; `finish_import(..., stopped)` reports
  "stopped:" vs "done:" and refreshes states.

---

## Testing strategy

- Everything goes through `main([...])` (the seam) or pure helpers; asserts
  land on stdout/stderr, exit codes, or direct SQLite reads of tmp DBs.
  Extractor tests drive `extract_*` functions directly against fixture text.
- `tests/conftest.py` ships a hand-rolled pure-Python **LZW compressor**
  because stdlib cannot WRITE `.tar.Z`. Keep fixtures genuine `.tar.Z` so the
  discovery glob and tar pipeline behave exactly like production; switching
  fixtures to plain `.tar` would weaken the seam.
- Integration test ingests the real corpus (`AMG_msg/`, marked `integration`,
  excluded by default via `addopts`). Run the complete suite with
  `python -m pytest -o addopts="" -q` (~90s). Fast suite: `python -m pytest`.
  Typecheck: `python -m mypy amg`.
- Expected values in tests are independent literals (measured corpus facts),
  never copies of implementation outputs.
- Lock-simulation tests hold `BEGIN EXCLUSIVE` on a second connection; note
  readers are blocked too in rollback-journal mode - assert THROUGH the
  blocking connection.

---

## Known limitations / future directions

- Dedupe is by location (archive name + inner filename), not content hash;
  identical text under different names stores twice. A `sha256(raw_text)`
  column + index would enable content-level dedupe.
- No `--force` flag; re-parsing means Full rebuild (GUI) or deleting the DB.
- Day-only dates (FWD) remain NULL; could inherit month/year heuristics if a
  use case appears.
- Airline attribution uses flight prefix only; spec once imagined deriving it
  from addresses too - judged low-value since addresses encode stations.
- ~263 genuinely untyped OTHER rows; census showed they lack any 3-letter
  keyword line (mostly fragments/garbage).
- `parse_error` is almost never populated; consider feeding it from tar-level
  anomalies if corrupt archives become interesting.
- Windows console output of `show` assumes CRLF-consistent corpus (see
  cmd_show note).

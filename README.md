# AMG Message Toolkit

Search and analyse SITA IATA Type B messages archived under `AMG_msg/` without
touching the archives themselves. Everything is indexed into a single portable
SQLite database; questions are answered from the index in seconds.

## Install

Requires Python 3.13+ and the system `tar` command (present by default on
Windows 10+, macOS, and Linux).

```console
pip install -e .
```

## Concepts

- **Archive** - a daily `.tar.Z` file named `PROCESSED_YYYYMMDD_HHMM.tar.Z` or
  `CORRUPTED_YYYYMMDD_HHMM.tar.Z`. Archives are immutable input; the toolkit
  never modifies them.
- **Message** - one raw Type B message per inner file (`.rcv` = processed,
  `.COR` = corrupted), named with its receipt timestamp under a station folder
  (e.g. `HKG/260607002540778.rcv`).
- **Index** - one SQLite database (`amg_messages.db` by default) holding all
  parsed messages plus full-text search.

## Usage

### Quick start (GUI)

Double-click `run.bat` (or run `python -m amg gui`). The window lists every
`*.tar.Z` with its size and indexed/pending state.

| Button | What it does |
| --- | --- |
| **Import selected** | imports the ticked archives only (pending ones are pre-ticked) |
| **Full rebuild** | wipes the index and re-parses every archive from scratch - use after a parsing-rule change |
| **Stop** | halts a running import/rebuild cleanly between archives |

Progress shows per archive; the final summary appears in the status bar. If the
database is open in DB Browser (or another program) you will see a clear
"database is locked" message instead of silent failures - close it and retry.

### 1. Build the index

```console
python -m amg ingest AMG_msg --db amg_messages.db
```

Import just some archives:

```console
python -m amg ingest AMG_msg --db amg_messages.db --only PROCESSED_20260610_0025.tar.Z
```

Ingest is incremental and idempotent: archives already recorded in the index
(name + size match) are skipped, so re-run it whenever new daily archives
arrive. Each run ends with a summary on stderr:

```
ingest summary: 2 ingested, 64 skipped, 0 failed
```

Exit codes: `0` clean, `3` some archives failed, `1` every archive failed
(or the database was locked).

### 2. Search

Filters combine freely; results are newest-first.

```console
python -m amg search --db amg_messages.db --type MVT --flight CI5825
python -m amg search --db amg_messages.db --from 2026-06-07 --to 2026-06-07
python -m amg search --db amg_messages.db --origin HKGODCI --status corrupted
python -m amg search --db amg_messages.db --q "B18778"
python -m amg search --db amg_messages.db --type BSM --csv > bsm.csv
```

| Filter | Meaning |
| --- | --- |
| `--type` | message keyword: MVT, LDM, ADL, PNL, ... (unrecognised bodies are typed OTHER) |
| `--flight` | flight number parsed from the info line, e.g. `CI5825` |
| `--origin` / `--dest` | Type B origin/destination address, e.g. `HKGTSXH` |
| `--status` | `processed` or `corrupted` |
| `--from` / `--to` | received-at window; dates (`2026-06-07`) or timestamps |
| `--q` | full-text query over raw message bodies |
| `--csv` | machine-readable output for Excel etc. |

### 3. Read a message

```console
python -m amg show --db amg_messages.db 42
```

Prints the stored raw text byte-for-byte.

### 4. Analyse

```console
python -m amg stats --db amg_messages.db --by day      # volumes + corrupted split per day
python -m amg stats --db amg_messages.db --by hour     # intra-day traffic profile
python -m amg stats --db amg_messages.db --by type     # message mix
python -m amg stats --db amg_messages.db --by airline  # carrier attribution from flight prefixes
```

`search` and `stats` accept `--csv`.

### 5. Check freshness

```console
python -m amg status --db amg_messages.db --archive-dir AMG_msg
```

Lists every archive as `indexed` or `pending`.

## How it works

**One seam.** All behaviour is reachable through one entry point -
`amg.cli.main(argv)` (and the GUI, which is a thin layer over the same core
functions). Archives are treated as immutable inputs; every derived fact lives
in the database so it can be recomputed at any time. Structured facts live in
`message_facts` (one row per extracted message); repeating rows (PTM transfers,
FWD hops) live in `message_segments`.

**Ingest pipeline.** For each archive: system `tar` converts the compressed
`.tar.Z` to an uncompressed stream in memory (~0.2s per archive), Python's
`tarfile` walks the members, each inner file is decoded as latin-1 and parsed,
and rows are inserted in one transaction per archive. A crash or failure
therefore never leaves a half-imported archive behind.

**Deduplication.** Two layers: (1) an archive whose name *and* file size are
already recorded is skipped entirely; (2) a `UNIQUE (source_archive,
source_file)` constraint with `INSERT OR IGNORE` makes message inserts safe no
matter how often an archive is processed. Dedupe is by location, not content.

**Envelope parsing.** Control characters of the Type B framing (`SOH`/`STX`/
`ETX`) are stripped for matching but preserved in stored raw text. The first
line that is a three-letter keyword (optionally followed by text) decides
`msg_type`; the last dotted address line before it gives `origin`; the header
line gives `priority`/`destination`.

**Per-category info lines.** The line after the keyword carries flight details
in different shapes per message family:

| Category | Shape | Extracted |
| --- | --- | --- |
| MVT, DIV, old LDM | `FLIGHT/DD.REG.AIRPORT` | flight_number, aircraft_reg, flight_airport |
| FWD | `FLIGHT/DD.AIRPORT...` | flight_number, flight_airport |
| new LDM | `FLIGHT/DDMMM[YY].REG...` | flight_number, aircraft_reg, flight_date |
| ASM | `FLIGHT/DDMMMYY ...` | flight_number, flight_date |
| PNL, ADL, PAL, CAL, PSM | `FLIGHT/DDMMM AIRPORT [PARTn]` | flight_number, flight_date, flight_airport, part_number |
| PTM | same, with from-to pair | flight_airport holds e.g. `SYXHKG` |

Flight numbers are restricted to 1-4 digits (`\d{1,4}`) per AHM 780 spec.

**flight_date normalisation.** Stored as `YYYYMMDD`. When the message itself
carries a year (`16MAY26`) that year wins; otherwise the year comes from the
archive filename, with a wrap rule (a December date in a January archive
belongs to the previous year). Day-only dates (FWD `28`, LDM `28`) roll forward
at month-end within a 48-hour window (e.g. day-30 in a 31-day month rolls to
1st of next month; day-31 in a 31-day month stays put).

**Per-family extractors.** Structured facts live in `message_facts` (one row
per message). Extractors cover MVT/MVA, LDM, DIV, PTM, PSM/PAL/CAL, PNL/ADL,
FWD, and ASM. Key fields:

| Family | Facts extracted |
| --- | --- |
| MVT/MVA | AHM 780 times (`AD`/`EO`/`TD`/`AA`/`EL`/`EA`), destinations, delay slots (`IR1`-`IR8`, `DL1`-`DL4`), PAX (`transit`/`disembarking`/`total`/`infants`), SI fuel/weight/events |
| LDM | cabins, PAX/PAD triples, BW/BI, deadload, crew |
| DIV | DVA, ETA, POB, CAN |
| PTM | transfer segments, total transfers, total baggage |
| PSM/PAL/CAL | assist codes, CAL delta ops |
| PNL/ADL | name-row/identifier-row counts, ADL changes (text fully redacted) |
| FWD | multi-hop destinations, component blocks (`.B`/`.R`/`.A`/`.L`/`.T`), nationalities per-block + merged |
| ASM | muted by default (allowlist for PQC-line carriers) |

**AHM 780 movement times.** Each time code (e.g. `AD`, `AA`, `EL`) is stored
as `{"time":"1939","date":null}` (or with a two-digit date for 6-digit forms
like `AD070110`). The `EO` (estimated off-blocks) and `EL` (estimated landing)
codes are derived from `AD/` pairs and `EA` tokens respectively. `TD` (touchdown)
is derived from the first value of an `AA/` pair when no explicit `TD` token
is present.

**Delay slots.** `DL…` lines fill IR1/DL1 through IR2/DL2 pairs, `EDL…` lines
fill IR3/DL3+, and `DLA…` lines add code-only entries at IR5+. Legacy flat
lists (`delay_codes`, `delay_durations`) are kept for compatibility.

**SI section.** Lines after an `SI` marker are scanned for known keys (`FR`,
`EET`, `BO`, `TOF`, `PL`, `ZFW`) as glued or spaced values. Event lines like
`SI DOOR CLSD 0455` are captured as timestamped events. Leading-zero strings
(e.g. `EET0122`) are preserved as strings, not converted to integers.

**Full-text search.** An SQLite FTS5 index over raw text, rebuilt after any
ingest that changed rows (guarded by an index/content count check so it can
never go stale). Structured facts and repeating segments live in separate
tables (`message_facts`, `message_segments`) joined by `message_id`.

**Browsing externally.** Open `amg_messages.db` in DB Browser for SQLite. Use
the `messages_readable` view - identical columns plus `message_text`, which is
raw text with framing bytes stripped for readable display. Structured facts
are in `message_facts.facts_json`; repeating rows (PTM transfers, FWD hops)
are in `message_segments.data_json`.

## Development

Ready-to-paste SQL for every message type lives in
[docs/query-cookbook.md](docs/query-cookbook.md). Internals, per-function
logic, and development traps are documented in
[docs/architecture.md](docs/architecture.md).

```console
python -m pytest               # fast unit suite (CLI seam only)
python -m pytest -o addopts="" # full suite incl. real-corpus integration test
python -m mypy amg             # type check
```

Tests drive only the public CLI against fixture archives and assert on stdout,
exit codes, and the database's public schema.

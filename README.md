# AMG Message Toolkit

Search and analyse SITA IATA Type B messages archived under `AMG_msg/` without
touching the archives themselves. Everything is indexed into a single portable
SQLite database; questions are answered from the index in seconds.

## Install

Source execution requires Python 3.13+. The GUIs also require tkinter/Tcl-Tk.
Archive ingestion requires the system `tar` command (present by default on
Windows 10+, macOS, and Linux); the standalone message generator does not.
The packaged generator executable needs neither Python nor the archive database.
The sender requires `requests` and `cryptography` (for encrypted config).

```console
pip install -e .
```

## Concepts

- **Archive** - a daily `.tar.Z` file named `PROCESSED_YYYYMMDD_HHMM.tar.Z` or
  `CORRUPTED_YYYYMMDD_HHMM.tar.Z`. Archives are immutable input; the toolkit
  never modifies them.
- **Message** - one raw Type B message per inner file (`.rcv` = processed,
  `.COR` = corrupted), named with its receipt timestamp under a station folder
  (e.g. `KIX/260607002540778.rcv`).
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

### Standalone test-message generator

This is a separate window, not an extension of the archive loader. On a Windows
PC, double-click `dist\AMGMessageGenerator.exe` from a local build; only the
executable needs copying. It embeds Python, Tk and the small JSON template
library, not `amg_messages.db`. The current build is approximately 10.8 MB.
It targets Windows 10/11 **x64**; startup was smoke-tested on Windows 10 x64,
not independently on Windows 11. The executable is unsigned.

From a source checkout, double-click `start_gen_gui.bat` or run:

```powershell
python -m amg.gen_gui
python -m amg.gen_gui --templates "amg\message_templates.json"
python -m amg.gen_gui --db "amg_messages.db"
```

`--templates` and `--db` are aliases: both accept JSON libraries or existing
AMG databases. With no argument, the generator loads the bundled
`amg/message_templates.json`, independently of the current working directory.
The default library contains 17 synthetic examples across 12 message types:
PNL, ADL, MVT, MVA, LDM, PTM, PSM, PAL, CAL, FWD, ASM and DIV. It includes
direct, multiple-destination and paired multipart PNL examples; it is not a
copy of the historical archive or a comprehensive protocol conformance suite.

1. Choose a message type and select a template. Optional flight and scheduled
   date filters select the **source template**, not the generated flight.
2. Enter replacements in the recognized flight/date/airport/pax fields; blank
   values keep the original. Choose the test direction relative to HKG.
3. Click **Apply fields to template**, then review or manually edit the preview.
   Applying fields again starts from the original template and asks before
   discarding manual edits.
4. Copy the preview or save `.txt` / framed `.rcv`. Exports use Latin-1 and CRLF;
   framed export requires a standalone recognized message-type line.
5. Click **Send** to POST the message to the configured API endpoint. The
   generator loads config from `.env` or `.env.enc` (see below).

The generator opens historical databases read-only. Un-redacted database
originals require opt-in; neither the redacted column nor user-supplied JSON
is guaranteed anonymous. Review before sharing.

**Current limits:** structured editing recognizes selected patterns for PNL,
ADL, MVT, MVA, LDM, FWD and ASM; other formats use manual preview editing.
Pax edits do not regenerate passenger names or recalculate dependent cabin,
weight, PAD or SI totals. Multipart examples are edited/exported separately.
A unique flight is `flight_number + scheduled_date + direction`; direction is
currently test metadata used in the suggested filename, not an automatic route
rewrite or enforced identity. Date edits retain the original header format,
so a day-only header does not encode the chosen month/year.

For the JSON contract and extension points, see the standalone generator
section in [docs/architecture.md](docs/architecture.md).

#### Sender configuration

The Send button POSTs messages to the AMG API. Config lives in a `.env` file
(in the `amg/` package directory for source runs, or next to the exe for
packaged builds).

```
API_URL=https://chilunsing.com/v1/amg
API_KEY=Basic UkVTVF9BTUc6a1VrZXp0cUtRTDVXMYYTTT=
```

Copy `amg/.env.example` to `amg/.env` and fill in your values. The `API_KEY`
is the full `Basic ...` authorization header value.

To encrypt the config (so the plaintext isn't stored on disk):

```powershell
python -m amg.encrypt_config                    # encrypts amg/.env -> amg/.env.enc
python -m amg.encrypt_config --input .env       # custom input path
python -m amg.encrypt_config --output out.enc   # custom output path
```

You will be prompted for a master password (entered twice to confirm). After
encrypting, delete the plaintext `.env`. The generator will prompt for the
master password when you click Send.

For packaged builds, place `.env` or `.env.enc` next to the exe and encrypt
from that directory:

```powershell
cd dist
python -m amg.encrypt_config --input .env --output .env.enc
```

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
python -m amg search --db amg_messages.db --q "B18778"
python -m amg search --db amg_messages.db --type BSM --csv > bsm.csv
```

| Filter | Meaning |
| --- | --- |
| `--type` | message keyword: MVT, LDM, ADL, PNL, ... (unrecognised bodies are typed OTHER) |
| `--flight` | flight number parsed from the info line, e.g. `CI5825` |
| `--origin` / `--dest` | Type B origin/destination address, e.g. `KIXTSXH` |
| `--status` | `processed` or `corrupted` |
| `--from` / `--to` | received-at window; dates (`2026-06-07`) or timestamps |
| `--q` | full-text query over raw message bodies |
| `--csv` | machine-readable output for Excel etc. |

### 3. Read a message

```console
python -m amg show --db amg_messages.db 42
```

Prints the stored raw text byte-for-byte (PNL/ADL name rows appear as
`[REDACTED]`). Add `--plain` to print the un-redacted original instead:

```console
python -m amg show --db amg_messages.db 42 --plain
```

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

**Separate application seams.** Archive operations use `amg.cli.main(argv)`
and the archive GUI over the same core functions. The independent generator
uses `amg.gen_gui.main(argv)` over `amg.generator` helpers and a JSON library
or read-only database. Archives are treated as immutable inputs; every derived
fact lives in the database so it can be recomputed at any time. Structured facts live in
`message_facts` (one row per extracted message); repeating rows (PTM transfers,
FWD hops, LDM destination segments) live in `message_segments`.

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
| PTM | same, with from-to pair | flight_airport holds e.g. `SYXKIX` |

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
| LDM | per-destination segments (pax breakdown, deadload, cabin classes, categories), aggregated PX6/PX7/PAX, PX1-3 classes, DDL deadload, crew, SI remarks + station FRE/POS/BAG/TRA breakdown |
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
raw text with framing bytes stripped for readable display, and
`message_text_plain`, the un-redacted original (PII policy applies to
`message_text` only; the plain column intentionally holds PNL/ADL names - see
`redact_text` in docs/architecture.md). Structured facts
are in `message_facts.facts_json`; repeating rows (PTM transfers, FWD hops,
LDM destination segments) are in `message_segments.data_json`.

## Development

Ready-to-paste SQL for every message type lives in
[docs/query-cookbook.md](docs/query-cookbook.md). Internals, per-function
logic, and development traps are documented in
[docs/architecture.md](docs/architecture.md).

```console
python -m pytest               # fast unit suite (CLI and generator seams)
python -m pytest -o addopts="" # full suite incl. real-corpus integration test
python -m mypy amg             # type check
python -m pytest tests/test_generator.py  # generator-only tests
python -m pytest tests/test_sender.py     # sender + config encryption tests
```

Build the standalone generator executable (requires PyInstaller):

```powershell
python -m pip install pyinstaller
.\build_gen_gui.bat
# -> dist\AMGMessageGenerator.exe
```

Tests drive the public CLI and generator entry points against fixture archives
and libraries and assert on stdout, exit codes, and the database's public
schema.

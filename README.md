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

- **Archive** — a daily `.tar.Z` file named `PROCESSED_YYYYMMDD_HHMM.tar.Z` or
  `CORRUPTED_YYYYMMDD_HHMM.tar.Z`. Archives are immutable input; the toolkit
  never modifies them.
- **Message** — one raw Type B message per inner file (`.rcv` = processed,
  `.COR` = corrupted), named with its receipt timestamp under a station folder
  (e.g. `HKG/260607002540778.rcv`).
- **Index** — a SQLite database you create once and reuse (`--db PATH`).

## Usage

### 1. Build the index

```console
python -m amg ingest AMG_msg --db index.db
```

Ingest is incremental and idempotent: archives already recorded in the index
are skipped, so re-run it whenever new daily archives arrive. Each run ends
with a summary on stderr:

```
ingest summary: 2 ingested, 64 skipped, 0 failed
```

Exit codes: `0` clean, `3` some archives failed, `1` every archive failed.

### 2. Search

Filters combine freely; results are newest-first.

```console
python -m amg search --db index.db --type MVT --flight CI5825
python -m amg search --db index.db --from 2026-06-07 --to 2026-06-07
python -m amg search --db index.db --origin HKGODCI --status corrupted
python -m amg search --db index.db --q "B18778"
python -m amg search --db index.db --type BSM --csv > bsm.csv
```

| Filter | Meaning |
| --- | --- |
| `--type` | message keyword: MVT, MVA, CHG, BSM, PNL, CPM, SVC, … (unknown bodies are typed OTHER) |
| `--flight` | flight number parsed from movement-style lines, e.g. `CI5825` |
| `--origin` / `--dest` | Type B origin/destination address, e.g. `HKGTSXH` |
| `--status` | `processed` or `corrupted` |
| `--from` / `--to` | received-at window; dates (`2026-06-07`) or timestamps |
| `--q` | full-text query over raw message bodies |
| `--csv` | machine-readable output for Excel etc. |

### 3. Read a message

```console
python -m amg show --db index.db 42
```

Prints the stored raw text byte-for-byte.

### 4. Analyse

```console
python -m amg stats --db index.db --by day      # volumes + corrupted split per day
python -m amg stats --db index.db --by hour     # intra-day traffic profile
python -m amg stats --db index.db --by type     # message mix
python -m amg stats --db index.db --by airline  # carrier attribution from flight prefixes
```

`search` and `stats` accept `--csv`.

### 5. Check freshness

```console
python -m amg status --db index.db --archive-dir AMG_msg
```

Lists every archive as `indexed` or `pending`.

## Development

```console
python -m pytest              # fast unit suite (CLI seam only)
python -m pytest -o addopts="" # full suite incl. real-corpus integration test
```

Tests drive only the public CLI against fixture archives and assert on stdout,
exit codes, and the database's public schema.

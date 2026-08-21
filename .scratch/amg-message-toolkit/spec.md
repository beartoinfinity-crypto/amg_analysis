# Spec: AMG Message Toolkit

Status: ready-for-agent

## Problem Statement

SITA IATA Type B messages arrive as daily `.tar.Z` archives under `AMG_msg/` — one raw text file per message inside a station folder, with `PROCESSED_` and `CORRUPTED_` prefixes. Finding every message about a flight, counting volumes by type or hour, or investigating what failed on a given day means manually extracting archives and grepping raw text. The data is effectively unsearchable and unanalysable.

## Solution

A command-line toolkit that treats the archives as immutable input: it ingests them into a local SQLite index without ever modifying them, parses each message's Type B envelope into structured columns plus a full-text index, and answers questions through `search`, `show`, and `stats` commands with table or CSV output. New daily archives are picked up incrementally; re-running ingest is always safe.

## User Stories

1. As a message analyst, I want to ingest all existing archives with one command, so that I stop extracting and grepping dozens of tar.Z files by hand.
2. As a message analyst, I want ingest to process only archives it hasn't seen, so that daily re-runs are fast.
3. As a message analyst, I want re-ingesting an already-indexed archive to change nothing, so that ingest is safe to run at any time.
4. As a message analyst, I want to search messages by flight number, so that I can pull up everything about e.g. CI5825.
5. As a message analyst, I want to search by date and time range, so that I can isolate an incident window.
6. As a message analyst, I want to filter by message type (MVT, MVA, CHG, BSM, PNL, CPM, …), so that I can work with just movement or just baggage traffic.
7. As a message analyst, I want to filter by origin or destination address, so that I can trace correspondence with one counterpart address.
8. As a message analyst, I want free-text search across full message bodies, so that I can find messages mentioning a tail number, passenger name, or error string.
9. As a message analyst, I want to combine filters freely, so that I can ask narrow questions like "CHG messages for flight X yesterday".
10. As a message analyst, I want results ordered newest-first with a stable order, so that scans are predictable.
11. As a message analyst, I want to view the complete raw text of any matched message, so that structured hits lead back to the source.
12. As a message analyst, I want to export any result set to CSV, so that colleagues can work with it in Excel.
13. As a duty engineer, I want volume statistics by day, hour, and message type, so that I can spot anomalies in traffic.
14. As a duty engineer, I want corrupted-vs-processed counts per day, so that I can quantify upstream failure rates.
15. As a duty engineer, I want per-airline breakdowns derived from addresses and flight prefixes, so that I can attribute load to carriers.
16. As an incident investigator, I want corrupted `.COR` messages indexed alongside processed ones but flagged, so that post-mortems cover the failures too.
17. As an incident investigator, I want malformed individual messages recorded rather than aborting ingest, so that one bad file never hides the rest of a day.
18. As a tool user, I want a status view of which archives are indexed and which are pending, so that I trust the index is current.
19. As a tool user, I want an ingest summary (new, skipped, errored), so that each run's effect is visible at a glance.
20. As a tool user, I want the source archives guaranteed untouched, so that the system of record stays intact.
21. As a tool user, I want queries served from the index rather than re-extracting archives, so that repeated questions answer in seconds.
22. As a tool user, I want the index as a single portable database file, so that I can copy or share it.
23. As a tool user, I want the schema station-aware even though only HKG exists today, so that new stations need no migration.

## Implementation Decisions

- Python 3 CLI application; standard library first; pytest for tests. Greenfield repo — no existing code constrains layout.
- One deep module behind one CLI entry point exposing subcommands: `ingest`, `search`, `show`, `stats`, `status`.
- Archives are immutable input. All derived state lives in a single SQLite database file at a configurable path, defaulting outside the archive folder.
- Ingest discovers `*.tar.Z` archives sorted by name, skips ones already recorded in the database (tracked by filename and size), extracts via the system `tar` subprocess (LZW `.Z` is not readable by the Python stdlib; bsdtar handles it and is present on this machine), then walks the extracted tree.
- Archive filenames encode processing outcome and date (`PROCESSED`/`CORRUPTED` + timestamp); inner files encode receipt time (`YYMMDDHHMMSSmmm`) and status (`.rcv`/`.COR`) under a station folder. These conventions populate received-at, station, and status columns without parsing message content.
- Envelope parsing extracts priority code, destination and origin addresses, and the body keyword line into a message-type column (MVT, MVA, CHG, BSM, PNL, CPM, …; anything unrecognised becomes OTHER). Flight-level fields (flight number, aircraft registration) are parsed for movement-family types. Full raw text is always retained verbatim.
- Schema: a messages table (identity, received-at, station, status, type, priority, origin, destination, flight number, registration, raw text, source archive, source file, parse-error) joined to an FTS5 full-text index over raw text; an archives table recording ingested sources. Idempotency enforced by uniqueness of source archive + source file.
- Per-file errors are caught and recorded on the row; ingest continues. A wholly unreadable archive fails that archive with a non-zero exit but does not block subsequent archives.
- Human-readable tables by default; `--csv` flag for machine consumption with stable column order.

## Testing Decisions

- Good tests assert external behaviour only: invoke the CLI against fixture archives, then assert on database contents via its public schema and on stdout/CSV output. No unit tests against parser internals.
- Single seam: the CLI boundary. Fixtures are the real in-repo archives (read-only integration fixtures) plus tiny synthetic archives for edge cases — empty archive, duplicate re-ingest, malformed message, unknown type.
- Prior art: none (greenfield); this spec establishes the pattern.

## Out of Scope

- Any GUI or web interface.
- Modifying, renaming, reorganising, or deleting source archives.
- Scheduled or watch-mode ingestion daemons.
- Deep field-level normalisation of every message body (BSM/PNL stored typed but not field-parsed).
- Network connectivity to SITA or any live feed.
- Multi-user concurrent access or a shared server deployment.

## Further Notes

- Observed data shape: ~5,600 messages/day across ~33 PROCESSED and ~33 CORRUPTED daily archives (~2 MB compressed each), all under the HKG station; types seen include MVT, MVA, CHG, BSM, PNL, CPM. The archive set has date gaps; the tool must tolerate missing days.
- Decisions reflect the recommended answers from the grilling session; they were adopted when the spec was commissioned.

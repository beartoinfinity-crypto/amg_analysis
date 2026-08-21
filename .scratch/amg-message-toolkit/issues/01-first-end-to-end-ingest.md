# 01 — First end-to-end ingest

**What to build:** A Python 3 project scaffold with pytest and a single CLI entry point exposing an `ingest` command. Pointing it at the archive folder discovers every `.tar.Z`, extracts each via the system `tar` into a temporary location, walks the extracted station folders, and stores one row per message file: raw text verbatim, plus received-at timestamp, station, and processed/corrupted status derived from archive prefix and file extension. An archives table records which sources are already ingested; a second run skips them, making ingest idempotent. Source archives are never modified.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Running ingest against the real archive folder populates the database with every message from every archive present
- [ ] Filename-derived columns (received-at, station, status) match the archive/file naming conventions observed in the corpus
- [ ] Re-running ingest on an already-indexed folder completes quickly and changes no message rows
- [ ] The source archives are byte-identical before and after any run
- [ ] Tests drive only the CLI against fixture archives (real + tiny synthetic) and assert on database contents via its public schema

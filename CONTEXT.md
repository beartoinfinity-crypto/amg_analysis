# AMG Message Toolkit — Context

Domain map for the SITA IATA Type B message toolchain. Read this before
`docs/architecture.md` (function map) and `docs/query-cookbook.md` (SQL
patterns). Agents working here: see `AGENTS.md` for skills and conventions.

## What this project is

A local, read-only analytical store for SITA IATA **Type B** telegrams. Raw
messages arrive compressed in daily `.tar.Z` archives under `AMG_msg/`; the
toolkit ingests them **without modifying the archives**, parses each
message's envelope + body into structured columns, extracts per-family
fields into facts/segments, and answers questions via a CLI (`search`,
`show`, `stats`, `status`), two GUI applications, and a SQLite database
(`amg_messages.db`).

## Core invariants

- **Archives are immutable input.** The system of record is never touched;
  all derived state lives in the SQLite database.
- **Ingest is idempotent.** Re-running only picks up new/changed archives
  (tracked by name + size).
- **PII is stripped at ingest.** PNL/ADL name rows are fully redacted
  (count-only policy); PTM/PSM/PAL/CAL names are partially redacted. The
  un-redacted original is retained in `messages.raw_text_plain` for
  authorized inspection — handle it as PII.
- **Analytics read from caches, not live JSON.** Every repeated view goes
  through a materialized cache table refreshed at ingest (see ADR-0001).

## Glossary

| Term | Meaning |
| --- | --- |
| **Type B message** | A SITA teleprinter telegram framed with control bytes (`\x01` SOH header, `\x02` STX body, `\x03` ETX end) plus a distribution header. |
| **Envelope** | The part `parse_envelope` reads: priority, destination/origin addresses, the keyword line identifying `msg_type`, and flight-level fields. |
| **Family** | The structured extractor group a message belongs to — LOAD (LDM), NAME_LIST (PNL/ADL), MOVEMENT (MVT/MVA), DIVERSION (DIV), TRANSFER (PTM), ASSISTANCE (PSM/PAL/CAL), FORWARD (FWD), SCHEDULE (ASM). |
| **Message family codes** | `MVT`, `MVA` movement · `LDM` load · `PNL`/`ADL` passenger name list (count-only) · `PTM` transfer · `PSM`/`PAL`/`CAL` assistance · `FWD` forward booking · `ASM` ad-hoc schedule · `DIV` diversion. Other types stay `OTHER`/`BSM`/`CPM`… unparsed. |
| **facts** | One JSON object per message in `message_facts.facts_json` — the structured fields the extractor emitted. |
| **segments** | Repeating rows per message in `message_segments.data_json` — destination blocks (LDM/PNL), transfer rows (PTM), forward hops (FWD). |
| **remap** | A flattened analytics view (`*_remap`) turning facts JSON into typed columns. |
| **cache table** | Materialized analytics table (`pnl_remaps`, `pnl_bursts`, `amg_pax_cache`) refreshed automatically at the end of ingest. |
| **burst** | A multi-part PNL/ADL transmission assembled from `PART1..N`; per-part rows must never be summed (each part repeats reference blocks). |
| **PXE / PX6** | Routing metrics: PXE = total bookings on board at departure; PX6 = passengers routed downline of HKG (per RP 1708 §4). |
| **boarding airport / dep date** | PNL/ADL header identity; combined with `flight_number` it uniquely identifies a flight rotation. |
| **HKG station** | The sending station the corpus is built around; schema is station-aware but only HKG exists today. |

## Where things live

- **`amg/cli.py`** — schema + views + caches, envelope parsing, ingest,
  search/show/stats/status commands, argparse entry point.
- **`amg/extractors.py`** — per-family extractors, redaction, column
  mappings.
- **`amg/gui.py`** — archive loader (ingest picker); **`amg/msg_analysis.py`**
  — tabbed field-analysis window; **`amg/gen_gui.py`** — test-message
  generator + sender.
- **`docs/architecture.md`** — function-by-function internals map.
- **`docs/query-cookbook.md`** — ready-to-paste SQL against `amg_messages.db`
  (views, caches, multi-hop, performance notes).

## The five facts/caches at a glance

| Object | Contents | Refresh |
| --- | --- | --- |
| `message_facts` / `message_segments` | extracted JSON per message | per ingest |
| `pnl_remaps` | per-message PNL/ADL facts | touched flights |
| `pnl_bursts` | burst-assembled PNL/ADL blocks | touched flights |
| `amg_pax_cache` | per-message LDM/PNL/ADL/FWD pax counts | touched messages |
| `messages_fts` | FTS5 over `raw_text` | rebuild after ingest |

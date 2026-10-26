# ADR-0001 — Materialized cache tables back the analytics views

**Status:** accepted · **Date:** 2026-10-20

## Context

The remap views originally re-parsed JSON per query: `AMG_PAX` took ~4.7 s
over the full corpus (200 k segment blobs), and a single point lookup paid
the same cost because the view could never prune. PNL/ADL facts needed a
second, burst-level perspective (multi-part PART1..N) that per-message rows
cannot express.

## Decision

Heavy analytics surfaces read from **materialized cache tables** refreshed
automatically at the end of every ingest:

- `pnl_remaps` (per-message PNL/ADL) + `pnl_remap` view
- `pnl_bursts` (burst assembly) — the `pnl_burst` view remains as an
  on-demand fallback
- `amg_pax_cache` + `AMG_PAX` view

Refresh granularity: the PNL caches key on **touched flights**; the pax
cache keys on **touched messages** (LDM/PNL/ADL/FWD across all of them).
A full rebuild happens on first ingest (empty cache) and whenever the
touched set is impractically large.

## Consequences

- `AMG_PAX` went from ~4.7 s to ~3 ms; `pnl_bursts` returns in ~2 ms.
- Caches are derived data: `rebuild_archives` clears them; `_migrate` may
  drop stale shapes and rely on next-ingest backfill.
- Query authors must read caches as the query surface (§14 of the query
  cookbook); the on-demand `pnl_burst` view stays for one-off freshness.
- Ingest cost rises slightly (cache recompute per touched flight).

## Considered alternatives

- Keep live JSON views and add indexes only — did not fix the JSON re-parse
  cost (rejected on measured 4.7 s).
- Materialized views via triggers — SQLite lacks live `CREATE MATERIALIZED
  VIEW`; triggers would duplicate the refresh logic in the schema.
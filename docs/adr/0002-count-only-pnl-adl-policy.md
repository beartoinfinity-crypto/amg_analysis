# ADR-0002 — Count-only privacy policy for NAME_LIST (PNL/ADL)

**Status:** accepted · **Date:** 2026-10-20 (policy predates; codified here)

## Context

PNL/ADL messages carry passenger names, record locators, and SSR contact
details (phones, email). The store is a shared, queryable index — full PII
at rest is unnecessary for traffic analysis and expands the blast radius of
the file.

## Decision

PNL/ADL text is **fully redacted before storage**: name rows (`^\d[A-Z]`)
and identifier rows (`^\.[A-Z][A-Z0-9]{0,2}/`) become `[REDACTED]`.
Extractors tally counts from those rows but never emit names. PTM/PSM/PAL/
CAL are **partially redacted** (name token and PNR locator masked, other
fields preserved). Other families are stored verbatim.

The **un-redacted original is retained** in `messages.raw_text_plain`
(original bytes), surfaced read-only via `messages_readable` as
`message_text_plain` — for authorized investigation only.

## Consequences

- `message_text` / `raw_text` (redacted) is the safe default for output;
  `message_text_plain` / `raw_text_plain` is PII and must not be exported
  without authorization.
- Facts (`message_facts`) never contain names — the fact views are PII-free
  by construction.
- The `--plain` flag on `amg show` and the cookbook's multi-hop queries
  explicitly opt into the un-redacted copy.

## Considered alternatives

- Store only counts, drop originals — loses ground truth for incident
  investigation (rejected: retained under `raw_text_plain`).
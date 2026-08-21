# 03 — Search, show, export

**What to build:** The everyday query workflow: a `search` command with freely combinable filters — message type, flight number, received-at date/time range, origin or destination address, and free-text over full bodies — returning newest-first results in a stable order; a `show` command printing the complete raw text of one message by identifier; and a CSV output flag on every result set for Excel handoff.

**Blocked by:** 02 — Structured envelope parsing.

**Status:** ready-for-agent

- [ ] Each filter works alone and in combination on the real corpus (e.g. movement messages for one flight within one day)
- [ ] Free-text search finds messages containing known strings (tail number, error text) that structured filters alone would miss
- [ ] Results are newest-first with ties broken deterministically across repeated runs
- [ ] Show reproduces the stored raw text byte-for-byte
- [ ] CSV export round-trips into a spreadsheet with stable column order
- [ ] All behaviour verified through the CLI boundary only

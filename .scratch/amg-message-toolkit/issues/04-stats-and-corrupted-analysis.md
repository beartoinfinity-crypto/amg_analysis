# 04 — Stats and corrupted analysis

**What to build:** A `stats` command answering trend questions over the indexed corpus: message volumes by day, hour, and type; corrupted-versus-processed counts per day to quantify upstream failure rates; and per-airline attribution derived from addresses and flight prefixes. Output as human-readable tables or CSV.

**Blocked by:** 02 — Structured envelope parsing.

**Status:** ready-for-agent

- [ ] Daily/hourly/type volume reports reconcile with direct counts from search on the same corpus
- [ ] Corrupted-vs-processed daily rates reflect the PROCESSED/CORRUPTED archive split actually present
- [ ] Airline breakdown attributes the dominant carriers visible in the corpus
- [ ] Date gaps in the archive set appear as gaps, not zeros or errors
- [ ] CSV variant matches the table variant row-for-row
- [ ] All behaviour verified through the CLI boundary only

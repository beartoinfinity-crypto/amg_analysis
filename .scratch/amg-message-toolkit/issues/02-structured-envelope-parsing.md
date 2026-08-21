# 02 — Structured envelope parsing

**What to build:** Extend ingest so each stored message gains structured columns parsed from its Type B envelope: priority code, destination address(es), origin address, and a message type taken from the body keyword line (movement/change/baggage/passenger-list families recognised; anything unrecognised typed as OTHER). Flight number and aircraft registration are extracted for movement-family messages. Every row keeps its raw text verbatim and is indexed for full-text search. A malformed message is recorded with its parse error rather than aborting the run.

**Blocked by:** 01 — First end-to-end ingest.

**Status:** ready-for-agent

- [ ] After re-ingesting the real archives, type/priority/address/flight columns are populated for the overwhelming majority of rows, with unrecognisable bodies typed OTHER rather than dropped
- [ ] Movement-family messages carry flight number and registration where present in the body
- [ ] Full-text index returns raw-text matches for terms known to appear in the corpus
- [ ] Handcrafted malformed-message fixtures end up stored with a recorded parse error while the rest of their archive ingests normally
- [ ] All behaviour verified through the CLI boundary only

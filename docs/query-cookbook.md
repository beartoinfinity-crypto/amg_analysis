# SQL Query Cookbook

Ready-to-paste queries for DB Browser for SQLite (or any SQLite client) against
`amg_messages.db`. JSON helpers use SQLite's `json_extract`, which DB Browser
ships with.

Tables involved:

| Object | Purpose |
| --- | --- |
| `messages` | raw parsed messages (framing bytes preserved in `raw_text`; `raw_text_plain` holds the un-redacted original) |
| `messages_readable` | view = `messages` + `message_text` (framing bytes stripped for display) + `message_text_plain` (un-redacted) |
| `message_facts` | one row per extracted message: `family`, `facts_json` (JSON object) |
| `message_segments` | repeating rows (PTM transfers, FWD hops, LDM destination segments): `seq`, `data_json` (JSON object) |
| `messages_fts` | FTS5 index over `raw_text`; query via `MATCH` on `rowid` |
| `archives` | ingested archive names + sizes (used by dedup logic) |
| `pnl_burst` | view: multi-part PNL/ADL transmission assembled to burst level — completeness gate (`complete` = final terminator seen), per-(dest,cabin) block totals, burst `pxe`/`px6` (computed on demand; slow on the full corpus) |
| `pnl_bursts` | cache table of the same burst assembly, refreshed automatically at the end of every ingest (incrementally for touched flights) — query this for fast repeated PXE/PX6 lookups |

---

## 1. Message content by type

```sql
-- Any type: change MVT to LDM / DIV / PTM / PSM / PAL / CAL / ASM / FWD ...
SELECT id, received_at, origin, flight_number, message_text
FROM messages_readable
WHERE msg_type = 'MVT'
ORDER BY received_at DESC
LIMIT 50;
```

```sql
-- Several types at once
SELECT msg_type, COUNT(*) FROM messages_readable
WHERE msg_type IN ('MVT', 'MVA', 'DIV')
GROUP BY msg_type;
```

## 2. MVT / MVA - AHM 780 times, destination, pax

```sql
SELECT r.id, r.received_at, r.flight_number, r.flight_airport, r.flight_date,
       json_extract(f.facts_json, '$.times.AD')    AS off_blocks,
       json_extract(f.facts_json, '$.times.EO')    AS airborne,
       json_extract(f.facts_json, '$.times.TD')    AS touchdown,
       json_extract(f.facts_json, '$.times.AA')    AS on_blocks,
       json_extract(f.facts_json, '$.times.EL')    AS est_landing,
       json_extract(f.facts_json, '$.destination') AS reported_dest,
       r.message_text
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type IN ('MVT', 'MVA')
ORDER BY r.received_at DESC;
```

Individual components of a time value (`{"time":"1939","date":null}`):

```sql
SELECT received_at, flight_number,
       json_extract(facts_json, '$.times.AD.time') AS off_blocks_hhmm,
       json_extract(facts_json, '$.times.AD.date') AS off_blocks_dd
FROM message_facts
WHERE family = 'MOVEMENT';
```

Passenger split (PX lines):

```sql
SELECT r.received_at, r.flight_number,
       json_extract(f.facts_json, '$.pax.transit')      AS transit_pax,
       json_extract(f.facts_json, '$.pax.disembarking') AS local_pax,
       json_extract(f.facts_json, '$.pax.total')        AS total_pax,
       json_extract(f.facts_json, '$.pax.infants')      AS infants
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type IN ('MVT', 'MVA')
  AND json_extract(f.facts_json, '$.pax.total') IS NOT NULL;
```

SI supplementary information (fuel, weights, events):

```sql
SELECT r.received_at, r.flight_number,
       json_extract(f.facts_json, '$.si.fuel_remaining') AS fuel_remaining,
       json_extract(f.facts_json, '$.si.takeoff_fuel')   AS takeoff_fuel,
       json_extract(f.facts_json, '$.si.burn_off')       AS burn_off,
       json_extract(f.facts_json, '$.si.payload')        AS payload,
       json_extract(f.facts_json, '$.si.zfw')            AS zfw,
       json_extract(f.facts_json, '$.si.eet')            AS eet,
       json_extract(f.facts_json, '$.si.events')         AS events
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE family = 'MOVEMENT' AND json_extract(f.facts_json, '$.si') IS NOT NULL;
```

## 3. Delays (IR1-IR8 codes, DL1-DL4 durations)

```sql
SELECT r.received_at, r.flight_number,
       json_extract(f.facts_json, '$.delays.IR1') AS ir1,
       json_extract(f.facts_json, '$.delays.DL1') AS dl1,
       json_extract(f.facts_json, '$.delays.IR2') AS ir2,
       json_extract(f.facts_json, '$.delays.DL2') AS dl2,
       json_extract(f.facts_json, '$.delays.IR3') AS ir3,
       json_extract(f.facts_json, '$.delays.DL3') AS dl3
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE f.family = 'MOVEMENT'
  AND json_extract(f.facts_json, '$.delays.IR1') IS NOT NULL;
```

All movements delayed by a specific IATA code (e.g. 57):

```sql
SELECT r.received_at, r.flight_number, f.facts_json
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE f.family = 'MOVEMENT'
  AND ('"' || json_extract(f.facts_json, '$.delays.IR1') || '"' IN
       (SELECT value FROM json_each(f.facts_json, '$.delay_codes'))
    OR '"' || json_extract(f.facts_json, '$.delays.IR2') || '"' IN
       (SELECT value FROM json_each(f.facts_json, '$.delay_codes')));
```

Simpler variant when you only care about the primary code:

```sql
SELECT received_at, flight_number
FROM messages_readable r JOIN message_facts f ON f.message_id = r.id
WHERE family='MOVEMENT' AND facts_json LIKE '%"IR1":"57"%';
```

## 4. LDM - loads

Aggregated load facts (AHM 583):

```sql
SELECT r.received_at, r.flight_number, r.flight_airport, r.flight_date,
       json_extract(f.facts_json, '$.reg')           AS reg,
       json_extract(f.facts_json, '$.pax')           AS pax_total,
       json_extract(f.facts_json, '$.px6')           AS transit_pax,
       json_extract(f.facts_json, '$.px7')           AS local_pax,
       json_extract(f.facts_json, '$.px1')           AS first_class,
       json_extract(f.facts_json, '$.px2')           AS business_class,
       json_extract(f.facts_json, '$.px3')           AS economy_class,
       json_extract(f.facts_json, '$.ddl')           AS deadload_total,
       json_extract(f.facts_json, '$.local_station') AS local_station,
       json_extract(f.facts_json, '$.crew')          AS crew,
       json_extract(f.facts_json, '$.cabins')        AS cabin_config,
       json_extract(f.facts_json, '$.si')            AS si_text,
       json_extract(f.facts_json, '$.station_breakdown') AS station_breakdown,
       json_extract(f.facts_json, '$.basic_weight')  AS basic_weight,
       json_extract(f.facts_json, '$.balance_index') AS balance_index
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type = 'LDM'
  AND json_extract(f.facts_json, '$.pax') IS NOT NULL;
```

Per-destination segment rows:

```sql
SELECT r.received_at, r.flight_number,
       json_extract(s.data_json, '$.dest')        AS dest,
       json_extract(s.data_json, '$.adults')      AS adults,
       json_extract(s.data_json, '$.children')    AS children,
       json_extract(s.data_json, '$.infants')     AS infants,
       json_extract(s.data_json, '$.pax_total')   AS pax,
       json_extract(s.data_json, '$.deadload')    AS deadload,
       json_extract(s.data_json, '$.classes')     AS cabin_pax,
       json_extract(s.data_json, '$.pads')        AS pads,
       json_extract(s.data_json, '$.categories')  AS categories,
       json_extract(s.data_json, '$.nil_traffic') AS nil_traffic
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
JOIN message_segments s ON s.message_id = r.id
WHERE r.msg_type = 'LDM'
ORDER BY r.received_at DESC, s.seq;
```

Flights touching a given destination (e.g. all LDM with a HKG segment):

```sql
SELECT r.received_at, r.flight_number
FROM messages_readable r
JOIN message_segments s ON s.message_id = r.id
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type = 'LDM'
  AND json_extract(s.data_json, '$.dest') = 'HKG'
  AND json_extract(s.data_json, '$.pax_total') > 0
ORDER BY r.received_at DESC;
```

### Expected values of the remap columns

`INTERFACE_COLUMN_MAPPINGS` (in `amg/extractors.py`) remaps LDM facts onto
their AODB target columns when the index is built - e.g. `PAX` -> `AMG_PAX`,
`REG` -> `AMG_REG`, `SI` -> `AMG_SIT`. Remapped facts are also **persisted**
in `message_facts.facts_json` under their remapped key. The `ldm_remap` view
materialises, per LDM message, each DB-facing column and the value that would
be committed there **after** remapping, reading the persisted key. Column names
reflect the current `INTERFACE_COLUMN_MAPPINGS` (remapped fields appear as
`AMG_*`; unremapped `CRW`/`DDL`/`PX1`-`PX7` keep their names). The view is
dropped and recreated on every rebuild, so its columns track the mapping.
Direct-facing MVT etc. are untouched - remapping is scoped to the LOAD family.

```sql
-- Everything that would be written for each departing/arriving flight
SELECT received_at, flight_number, flight_airport,
       REG  AS aircraft_reg,
       PAX  AS pax_on_board,
       PX6  AS transit, PX7 AS local,
       DDL  AS deadload,
       CRW  AS crew,
       SI   AS remarks_text
FROM ldm_remap
WHERE PAX > 0
ORDER BY received_at DESC;
```

When a remap is configured (`PAX -> AMG_PAX` etc.), query by the remapped
column names - the view's columns change accordingly:

```sql
SELECT l.*, r.message_text,r.flight_date
FROM ldm_remap l
JOIN messages_readable r ON message_id = r.id
WHERE AMG_PAX > 0
and r.flight_date ='20260820'
ORDER BY received_at DESC
LIMIT 20;
```

## 5. DIV - diversions

```sql
SELECT r.received_at, r.flight_number,
       json_extract(f.facts_json, '$.dva') AS diversion_airport,
       json_extract(f.facts_json, '$.eta') AS eta,
       json_extract(f.facts_json, '$.pob') AS persons_on_board,
       json_extract(f.facts_json, '$.can') AS cancelled,
       r.message_text
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type = 'DIV';
```

## 6. PTM - transfers and segments

Summary facts:

```sql
SELECT r.received_at, r.flight_number,
       json_extract(f.facts_json, '$.total_transfers') AS transfers,
       json_extract(f.facts_json, '$.total_baggage')   AS baggage,
       json_extract(f.facts_json, '$.segments')        AS segment_count
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type = 'PTM';
```

Each transfer row as its own line (names are redacted by policy):

```sql
SELECT r.received_at, r.flight_number,
       json_extract(s.data_json, '$.hop')        AS hop,
       json_extract(s.data_json, '$.flight')     AS connect_flight,
       json_extract(s.data_json, '$.day')        AS day,
       json_extract(s.data_json, '$.airports')   AS airports,
       json_extract(s.data_json, '$.cabin_bags') AS class_bags
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
JOIN message_segments s ON s.message_id = r.id
WHERE r.msg_type = 'PTM'
ORDER BY r.received_at DESC, s.seq;
```

## 7. PSM / PAL / CAL - special assistance + CAL deltas

```sql
SELECT r.msg_type, r.received_at, r.flight_number,
       json_extract(f.facts_json, '$.assist_codes') AS assist_codes,
       json_extract(f.facts_json, '$.delta')        AS cal_changes,
       json_extract(f.facts_json, '$.pax_total')    AS pax_total,
       r.message_text
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type IN ('PSM', 'PAL', 'CAL')
ORDER BY r.received_at DESC;
```

Messages mentioning a specific assist code (WCHR etc.):

```sql
SELECT r.received_at, r.flight_number, r.msg_type
FROM messages_readable r JOIN message_facts f ON f.message_id = r.id
WHERE family = 'ASSISTANCE'
  AND EXISTS (
    SELECT 1 FROM json_each(f.facts_json, '$.assist_codes')
    WHERE json_each.value = 'WCHR'
  );
```

## 8. PNL / ADL - RP 1708 passenger counts (PII is stripped by policy)

Stored text is a `[REDACTED]` skeleton; the numbers live in facts. Each message
is one `message_facts` row (flight element, aggregation) plus one
`message_segments` row per destination/cabin-class leg.

Per-leg destination breakdown (declared vs. actually parsed from name rows):

```sql
SELECT r.received_at, r.flight_number,
       json_extract(s.data_json, '$.dest')           AS dest,
       json_extract(s.data_json, '$.cabin_class')    AS cabin,
       json_extract(s.data_json, '$.declared_total') AS declared,
       json_extract(s.data_json, '$.actual_parsed_pax') AS parsed,
       json_extract(s.data_json, '$.pad_total')      AS pad
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
JOIN message_segments s ON s.message_id = r.id
WHERE r.msg_type IN ('PNL', 'ADL')
ORDER BY r.received_at DESC, s.seq;
```

Multi-leg routing metrics (PXE/PX6) and PNL aggregate view. `pnl_remap` is a
dedicated view (like `ldm_remap`) turning the PNL/ADL facts into columns -
flight element, boarding airport, part number, `pxe`/`px6`, `no_action`,
`pax_on_board` (sum of all leg declared totals) and `segment_count`:

```sql
SELECT received_at, msg_type, flight_number, flight_airport, boarding_airport,
       part_number, name_rows, pxe, px6, no_action,
       arrival_action, departure_action, pax_on_board, segment_count
FROM pnl_remap
WHERE pax_on_board > 0
ORDER BY received_at DESC
LIMIT 100;
```

PNL/ADL routed into and out of HKG (no-action legs filtered out):

```sql
SELECT received_at, flight_number, boarding_airport, pxe, px6, pax_on_board
FROM pnl_remap
WHERE no_action = 0
ORDER BY received_at DESC
LIMIT 100;
```

SSR tallies by code (anonymised - codes only, no names/phones):

```sql
SELECT received_at, flight_number, json_extract(facts_json, '$.ssrs') AS ssrs
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type IN ('PNL', 'ADL')
  AND json_extract(facts_json, '$.ssrs') IS NOT NULL
ORDER BY received_at DESC;
```

## 9. FWD - forward booking, multi-hop

Header level:

```sql
SELECT r.received_at, r.flight_number, r.flight_airport, r.flight_date,
       json_extract(f.facts_json, '$.crew')            AS crew,
       json_extract(f.facts_json, '$.destination')     AS final_dest,
       json_extract(f.facts_json, '$.hops')            AS hops,
       json_extract(f.facts_json, '$.components')      AS first_block,
       json_extract(f.facts_json, '$.nationalities')   AS pax_by_nationality
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type = 'FWD';
```

Every hop block:

```sql
SELECT r.received_at, r.flight_number,
       json_extract(j.value, '$.airport') AS airport,
       json_extract(j.value, '$.B')       AS bookings,
       json_extract(j.value, '$.R')       AS transfers,
       json_extract(j.value, '$.A')       AS air_to_air,
       json_extract(j.value, '$.L')       AS slta,
       json_extract(j.value, '$.T')       AS deadload_kg,
       json_extract(j.value, '$.nationalities') AS by_nationality
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id,
json_each(f.facts_json, '$.destinations') j
ORDER BY r.received_at DESC, j.key;
```

Transfer rows per hop:

```sql
SELECT r.received_at,
       json_extract(s.data_json, '$.hop')        AS hop,
       json_extract(s.data_json, '$.flight')     AS flight,
       json_extract(s.data_json, '$.destination') AS dest,
       json_extract(s.data_json, '$.detail')     AS detail
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
JOIN message_segments s ON s.message_id = r.id
WHERE r.msg_type = 'FWD'
ORDER BY r.received_at DESC, s.seq;
```

## 10. ASM muting state

```sql
SELECT r.received_at,
       json_extract(f.facts_json, '$.muted')  AS muted,
       json_extract(f.facts_json, '$.airline') AS airline
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type = 'ASM';
```

## 11. Cross-cutting

Full-text search over bodies:

```sql
SELECT id, received_at, msg_type, flight_number, message_text
FROM messages_readable
WHERE id IN (SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'PQC');
```

Daily volume + corrupted split:

```sql
SELECT substr(received_at, 1, 10) AS day,
       COUNT(*) AS total,
       SUM(status = 'corrupted') AS corrupted
FROM messages GROUP BY day ORDER BY day;
```

Extraction coverage sanity check:

```sql
SELECT family, COUNT(*) FROM message_facts GROUP BY family ORDER BY 2 DESC;
```

Line-limit violations (spec 1.2 monitoring):

```sql
SELECT COUNT(*) FROM message_facts
WHERE json_extract(facts_json, '$.line_limit_violations') > 0;
```

Messages with line-limit violations (for investigation):

```sql
SELECT r.received_at, r.msg_type, r.flight_number,
       json_extract(f.facts_json, '$.line_limit_violations') AS violations,
       r.message_text
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE json_extract(f.facts_json, '$.line_limit_violations') > 0;
```

Filter by flight number (1-4 digit flights per AHM 780):

```sql
SELECT received_at, msg_type, flight_number, message_text
FROM messages_readable
WHERE flight_number = 'CI5825'
ORDER BY received_at DESC;
```

## 12. Per-message-type queries

One query per family. Each `msg_type` maps to exactly one family; the family
(facts) schema is identical for every type it serves, so a single query covers
them:

| Family | Serves msg_type | Headline fields |
| --- | --- | --- |
| MOVEMENT | MVT, MVA | times (AD/EO/EL/...), destination, abp/adp |
| DIVERSION | DIV | dva, eta, can |
| LOAD | LDM | pax (AMG_PAX), px1-3, px6, px7, deadload, reg, crew |
| TRANSFER | PTM | per-segment transfers (flight, airports, cabin/bags) |
| ASSISTANCE | PSM, PAL, CAL | assist_codes, pax_total |
| NAME_LIST | PNL, ADL | flight element, pxe/px6, ssrs, per-leg pax |
| FORWARD | FWD | crew, components, nationalities, per-hop rows |
| SCHEDULE | ASM | airline, muted |

Every query appends `r.message_text` — the stored (framing-stripped) original —
so you can jump from a fact to the exact source message. Note PNL/ADL text is
redacted to `[REDACTED]` at storage by policy (see `redact_text` in
architecture.md); the structured facts below are extracted from the pre-redaction
text and remain PII-free. To see the un-redacted original instead, swap
`r.message_text` for `r.message_text_plain` (or select both side by side):

```sql
-- Example: interesting fields + both copies of the text
SELECT r.received_at, r.flight_number,
       json_extract(f.facts_json, '$.pxe') AS pxe,
       r.message_text,        -- redacted copy (PNL/ADL names -> [REDACTED])
       r.message_text_plain   -- un-redacted original (holds real names)
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type IN ('PNL', 'ADL');
```

Rows ingested before the plaintext column was added have NULL
`message_text_plain` until re-ingested.

### 12.1 MOVEMENT (MVT, MVA)

```sql
SELECT r.received_at, r.flight_number, r.flight_airport,
       json_extract(f.facts_json, '$.destination')     AS dest,
       json_extract(f.facts_json, '$.times.AD.time')   AS actual_dep,
       json_extract(f.facts_json, '$.times.EO.time')   AS est_off_block,
       json_extract(f.facts_json, '$.times.EL.time')   AS est_on_block,
       json_extract(f.facts_json, '$.times.TD.time')   AS actual_off_block,
       json_extract(f.facts_json, '$.times.AA.time')   AS actual_arrive,
       json_extract(f.facts_json, '$.adp')             AS adp,
       json_extract(f.facts_json, '$.abp')             AS abp,
       r.message_text
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type IN ('MVT', 'MVA')
ORDER BY r.received_at DESC;
```

### 12.2 DIVERSION (DIV)

```sql
SELECT r.received_at, r.flight_number,
       json_extract(f.facts_json, '$.dva')   AS diversion_airport,
       json_extract(f.facts_json, '$.eta')   AS eta,
       json_extract(f.facts_json, '$.can')   AS cancellation,
       r.message_text
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type = 'DIV'
ORDER BY r.received_at DESC;
```

### 12.3 LOAD (LDM)

```sql
SELECT r.received_at, r.flight_number, r.flight_airport,
       json_extract(f.facts_json, '$.AMG_REG')   AS reg,
       json_extract(f.facts_json, '$.AMG_PAX')   AS pax,
       json_extract(f.facts_json, '$.px1')       AS first,
       json_extract(f.facts_json, '$.px2')       AS business,
       json_extract(f.facts_json, '$.px3')       AS economy,
       json_extract(f.facts_json, '$.px6')       AS transit,
       json_extract(f.facts_json, '$.px7')       AS local,
       json_extract(f.facts_json, '$.ddl')       AS deadload,
       json_extract(f.facts_json, '$.crew')      AS crew,
       json_extract(f.facts_json, '$.local_station') AS local_station,
       r.message_text
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type = 'LDM'
ORDER BY r.received_at DESC;
```

### 12.4 TRANSFER (PTM)

```sql
SELECT r.received_at, r.flight_number,
       json_extract(s.data_json, '$.flight')      AS transfer_flight,
       json_extract(s.data_json, '$.airports')    AS to_airport,
       json_extract(s.data_json, '$.cabin_bags')  AS cabin_bags,
       json_extract(s.data_json, '$.day')         AS day,
       r.message_text
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
JOIN message_segments s ON s.message_id = r.id
WHERE r.msg_type = 'PTM'
ORDER BY r.received_at DESC, s.seq;
```

### 12.5 ASSISTANCE (PSM, PAL, CAL)

```sql
SELECT r.received_at, r.msg_type, r.flight_number,
       json_extract(f.facts_json, '$.assist_codes') AS assist_codes,
       json_extract(f.facts_json, '$.pax_total')    AS pax_total,
       r.message_text
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type IN ('PSM', 'PAL', 'CAL')
ORDER BY r.received_at DESC;
```

### 12.6 NAME_LIST (PNL, ADL)

```sql
SELECT r.received_at, r.msg_type, r.flight_number,
       json_extract(f.facts_json, '$.boarding_airport') AS boarding,
       json_extract(f.facts_json, '$.part_number')      AS part,
       json_extract(f.facts_json, '$.name_rows')        AS name_rows,
       json_extract(f.facts_json, '$.pxe')              AS pxe,
       json_extract(f.facts_json, '$.px6')              AS px6,
       json_extract(f.facts_json, '$.no_action')        AS no_action,
       json_extract(f.facts_json, '$.ssrs')             AS ssrs,
       r.message_text
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type IN ('PNL', 'ADL')
ORDER BY r.received_at DESC;
```

Per-leg pax for a NAME_LIST message (dest / cabin / declared vs parsed):

```sql
SELECT r.received_at, r.flight_number,
       json_extract(s.data_json, '$.dest')             AS dest,
       json_extract(s.data_json, '$.cabin_class')      AS cabin,
       json_extract(s.data_json, '$.declared_total')   AS declared,
       json_extract(s.data_json, '$.actual_parsed_pax') AS parsed,
       json_extract(s.data_json, '$.pad_total')        AS pad,
       r.message_text
FROM messages_readable r
JOIN message_segments s ON s.message_id = r.id
WHERE r.msg_type IN ('PNL', 'ADL')
ORDER BY r.received_at DESC, s.seq;
```

Flights split across multiple parts (e.g. KE2012 = PART1..18) are stored as one
row per part/message, each with its own `pxe`/`px6`. **Do not SUM per-part
rows** — corpus evidence shows parts repeat the destination-total blocks as
reference headers while only the name rows are partitioned, so a SUM massively
over-counts (KE2012: sum of per-part pxe = 4,849 vs true assembled total 317).

Use the burst assembly instead. It groups parts into bursts (flight identity
+ ADL revision `ana` + arrival hour), gates on the final terminator
(`ENDPNL`/`ENDADL` — a burst is `complete = 1` only once it arrives), assembles
per-(dest,cabin) totals as the most complete declaration seen in any part, and
re-derives burst-level `pxe`/`px6` from the assembled blocks (same HKG routing
rules as the extractor).

**Query the `pnl_bursts` cache table** (identical columns, refreshed
automatically at the end of every ingest — incrementally for just the flights
the ingest touched): it answers instantly. The `pnl_burst` view computes the
same assembly on demand and takes ~a minute over the full corpus — fine for a
one-off, wrong for repeated lookups.

```sql
-- One row per assembled (dest, cabin) block of each burst
SELECT * FROM pnl_bursts
WHERE flight_number = 'KE2012' AND complete = 1;
```

Latest complete burst per flight (ADLs supersede earlier PNL/ADL revisions —
`last_received_at` picks the winner):

```sql
SELECT *
FROM pnl_bursts b
WHERE b.complete = 1
  AND b.last_received_at = (
    SELECT MAX(b2.last_received_at)
    FROM pnl_bursts b2
    WHERE b2.flight_number = b.flight_number
      AND b2.boarding_airport = b.boarding_airport
      AND b2.dep_date = b.dep_date
      AND b2.complete = 1
  );
```

Flight-level totals only (no per-block rows):

```sql
SELECT DISTINCT flight_number, dep_date, ana, message_count, distinct_parts,
       max_part, complete, burst_pxe, burst_px6, action
FROM pnl_bursts
ORDER BY flight_number, last_received_at;
```

**Multi-part vs re-sends.** `message_count` counts all messages in the
transmission group; `distinct_parts`/`max_part` come from the PART numbers in
the flight elements. A true multi-part PNL (e.g. TK0071 PART1..52) shows
`distinct_parts > 1`; a cluster of re-sent single-part PNLs (e.g. CX841: nine
`PART1` messages within the hour, some partial) shows
`message_count > 1 AND distinct_parts = 1`. The burst assembly handles both the
same way - the most complete declaration per block wins:

```sql
-- true multi-part transmissions only
SELECT DISTINCT flight_number, dep_date, message_count, distinct_parts,
       max_part, complete, burst_pxe, burst_px6
FROM pnl_bursts
WHERE distinct_parts > 1
ORDER BY last_received_at DESC;

-- re-send clusters (separate complete transmissions, not parts)
SELECT DISTINCT flight_number, dep_date, message_count, burst_pxe, burst_px6
FROM pnl_bursts
WHERE message_count > 1 AND distinct_parts = 1;
```

**From a burst row back to its messages.** The `burst_key` is
`flight/boarding/dep_day+dep_month/ana/arrival_hour` — rebuild it to list the
message ids:

```sql
SELECT r.id, r.msg_type, r.part_number, r.received_at,
       json_extract(f.facts_json, '$.terminator') AS terminator,
       json_extract(f.facts_json, '$.pxe') AS pxe,
       json_extract(f.facts_json, '$.px6') AS px6
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.flight_number || '/' ||
      COALESCE(json_extract(f.facts_json, '$.boarding_airport'), '') || '/' ||
      COALESCE(json_extract(f.facts_json, '$.dep_day'), '') ||
      COALESCE(json_extract(f.facts_json, '$.dep_month'), '') || '/' ||
      COALESCE(json_extract(f.facts_json, '$.ana'), '') || '/' ||
      strftime('%Y%m%d%H', r.received_at) = 'CX841/JFK/08JUN//2026060915'
ORDER BY r.received_at;
```

Read any of them with `python -m amg show --db amg_messages.db <id>`
(`--plain` for the un-redacted copy).

### 12.7 FORWARD (FWD)

```sql
SELECT r.received_at, r.flight_number,
       json_extract(f.facts_json, '$.crew')            AS crew,
       json_extract(f.facts_json, '$.destination')     AS dest,
       json_extract(f.facts_json, '$.hops')            AS hops,
       json_extract(f.facts_json, '$.components')      AS components,
       json_extract(f.facts_json, '$.nationalities')   AS nationalities,
       r.message_text
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type = 'FWD'
ORDER BY r.received_at DESC;
```

Per-hop rows for a FWD message:

```sql
SELECT r.received_at, r.flight_number,
       json_extract(s.data_json, '$.hop')         AS hop,
       json_extract(s.data_json, '$.flight')      AS flight,
       json_extract(s.data_json, '$.destination') AS dest,
       json_extract(s.data_json, '$.detail')      AS detail,
       r.message_text
FROM messages_readable r
JOIN message_segments s ON s.message_id = r.id
WHERE r.msg_type = 'FWD'
ORDER BY r.received_at DESC, s.seq;
```

### 12.8 SCHEDULE (ASM)

```sql
SELECT r.received_at, r.flight_number,
       json_extract(f.facts_json, '$.airline') AS airline,
       json_extract(f.facts_json, '$.muted')   AS muted,
       r.message_text
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type = 'ASM'
ORDER BY r.received_at DESC;
```

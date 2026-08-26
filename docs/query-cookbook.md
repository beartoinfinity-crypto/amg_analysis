# SQL Query Cookbook

Ready-to-paste queries for DB Browser for SQLite (or any SQLite client) against
`amg_messages.db`. JSON helpers use SQLite's `json_extract`, which DB Browser
ships with.

Tables involved:

| Object | Purpose |
| --- | --- |
| `messages_readable` | view = `messages` + `message_text` (framing bytes stripped) |
| `message_facts` | one row per extracted message: `family`, `facts_json` |
| `message_segments` | repeating rows (PTM transfers, FWD hops): `seq`, `data_json` |

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

```sql
SELECT r.received_at, r.flight_number,
       json_extract(f.facts_json, '$.cabins')       AS cabins,
       json_extract(f.facts_json, '$.pax')          AS pax,
       json_extract(f.facts_json, '$.pad')          AS pad,
       json_extract(f.facts_json, '$.deadload')     AS deadload,
       json_extract(f.facts_json, '$.crew')         AS crew,
       json_extract(f.facts_json, '$.basic_weight') AS bw,
       json_extract(f.facts_json, '$.balance_index') AS bi
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE r.msg_type = 'LDM';
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

## 8. PNL / ADL - counts only (PII is stripped by policy)

Stored text is a `[REDACTED]` skeleton; the numbers live in facts.

```sql
SELECT received_at, flight_number, flight_date, part_number,
       json_extract(facts_json, '$.name_rows')        AS name_rows,
       json_extract(facts_json, '$.identifier_rows')  AS identifier_rows,
       json_extract(facts_json, '$.changes')          AS adl_changes
FROM messages_readable r
JOIN message_facts f ON f.message_id = r.id
WHERE msg_type IN ('PNL', 'ADL')
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

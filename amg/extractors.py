"""Per-family Type B message extractors.

Pure functions: message text in, structured facts out. No database access so
the logic stays independently testable and reusable. Storage shape:

- scalar findings  -> ``message_facts.facts_json`` (one JSON object per message)
- repeating rows   -> ``message_segments.data_json`` (TFI/FWD rows etc.)

Privacy: PNL/ADL text is fully redacted before storage (count-only policy);
PTM/PSM/PAL/CAL keep structure and assist codes but have name tokens
replaced. See ``redact_text``.
"""

import json
import re

LINE_LIMIT = 64
STRICT_LINE_VALIDATION = False

TIMES_RE = re.compile(
    r"(?<![A-Z0-9])(AD|AB|TD|AA|ED|EA|EL|EO|EAN|EDP|EB|RA)(\d{6}|\d{4})(?:/(\d{6}|\d{4}))?(?![0-9])"
)
PX_SLASH_RE = re.compile(r"(?<![A-Z0-9])PX(\d+)/(\d+)(?![0-9])")
PAX_TOTAL_RE = re.compile(r"\bPA?X(\d+)(?:\+(\d+)\s*INF)?", re.IGNORECASE)
DEST_TOKEN_RE = re.compile(r"^[A-Z]{3}$")
DELAY_SLOT_RE = re.compile(r"\d{1,2}")
DVA_ETA_RE = re.compile(r"^E[A-Z]?(\d{4})\s+([A-Z]{3})\s*$", re.MULTILINE)
CAN_RE = re.compile(r"(?<![A-Z])CAN(?![A-Z])")
POB_RE = re.compile(r"\bPOB(\d+)\b", re.IGNORECASE)
CABIN_RUN_RE = re.compile(r"\b((?:[JFCYG]\d{1,3}){2,})(?![A-Z0-9])")
CABIN_PAIR_RE = re.compile(r"([JFCYG])(\d{1,3})")
PAX_RE = re.compile(r"PAX/(\d+)/(\d+)/(\d+)")
PAD_RE = re.compile(r"PAD/(\d+)/(\d+)/(\d+)")
CREW_RE = re.compile(r"\bCRW[ /](\d+)[ /](\d+)\b")
BW_RE = re.compile(r"\bBW\s+(\d+)\b")
BI_RE = re.compile(r"\bBI\s+([\d.]+)\b")
DEADLOAD_RE = re.compile(r"\.T(\d+)(?![0-9])")
PTM_ROW_RE = re.compile(
    r"^([A-Z0-9]{2,3}\d+[A-Z]?)/(\d{1,2}(?:[A-Z]{3})?)\s+([A-Z]{3}(?:[A-Z]{3})?)\s+(.+)$",
    re.ASCII,
)
PX_RE = re.compile(r"\bPX(\d+)\b")
BG_RE = re.compile(r"\bBG(\d+)\b")
ASSIST_CODE_RE = re.compile(r"(?<![A-Z0-9])(WCHR|WCHC|WCHS|WCB|DEAF|BLND|MEDA|UMNR|MAAS|ESAN)(?![A-Z])")
NAME_ROW_RE = re.compile(r"^\d[A-Z]")
IDENTIFIER_ROW_RE = re.compile(r"^\.[A-Z][A-Z0-9]{0,2}/")
CFG_RE = re.compile(r"CFG/([A-Z0-9/]+)")
OP_MARKER_RE = re.compile(r"^(ADD|DEL|CHG)\s*$", re.MULTILINE)
FWD_CREW_RE = re.compile(
    r"^(?:FWD)?([A-Z0-9]{2,3}\d+[A-Z]?)/\d+\.[A-Z]{3}\.(\d+/\d+/\d+)", re.ASCII
)
FWD_DASH_DEST_RE = re.compile(r"-([A-Z]{3})((?:\.[BRLAT]\d+)+)")
FWD_COMPONENT_RE = re.compile(r"\.([BRLAT])(\d+)(?![0-9])")
NATIONALITY_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{3})/(\d+)(?![0-9])")

LDM_HEADER_RE = re.compile(
    r"^(?P<carrier>[A-Z0-9]{2,3})(?P<flight_num>\d{1,4})(?P<suffix>[A-Z])?/"
    r"(?P<day>\d{1,2}(?:[A-Z]{3}\d{2})?)\.(?P<reg>[A-Z0-9\-]+)"
    r"\.(?P<type>[A-Z0-9]+)?(?:\.(?P<crew_ckpt>\d+)/(?P<crew_cab>\d+)"
    r"(?:/(?P<crew_cab_f>\d+))?)?",
    re.ASCII,
)
LDM_NIL_RE = re.compile(r"^NIL$", re.IGNORECASE)
LDM_SEG_PAX_RE = re.compile(r"^\d+/\d+/\d+(?:/\d+)?$")
LDM_DEADLOAD_RE = re.compile(r"^T(\d+)$")
LDM_PAX_CLASS_RE = re.compile(r"^PAX/(\d+(?:/\d+){1,2})$")
LDM_PAD_CLASS_RE = re.compile(r"^PAD/(\d+(?:/\d+){1,2})$")
LDM_PAX_TOTAL_RE = re.compile(r"^PAX/(\d+)$")
LDM_PAD_TOTAL_RE = re.compile(r"^PAD/(\d+)$")
LDM_COMPARTMENT_RE = re.compile(r"^\d+/\d+$")
LDM_CATEGORY_RE = re.compile(r"^([A-Z]{3})/(\d+)(?:/(\d+))?$")
SI_BREAKDOWN_RE = re.compile(
    r"^(?P<station>[A-Z]{3})\s+FRE\s+(?P<fre>\d+)\s+POS\s+(?P<pos>\d+)\s+BAG\s+"
    r"(?P<bag>\d+)(?:\s*/\s*(?P<bag_weight>\d+))?\s+TRA\s+(?P<tra>\d+)"
)

ASSIST_CODES = ("WCHR", "WCHC", "WCHS", "WCB", "DEAF", "BLND", "MEDA", "UMNR", "MAAS", "ESAN")

# RP 1708 PNL/ADL (IATA PSCRM). Patterns tuned to the real corpus which matches
# the spec's canonical forms (e.g. "EK0380/12AUG DXB PART1", "-HKG213Y-PAD005").
PNL_FLIGHT_RE = re.compile(
    r"^([A-Z]{2,3})([0-9]{1,4})([A-Z]?)\/([0-9]{2})([A-Z]{3})\s+"
    r"([A-Z]{3})(?:\s+PART([0-9]+))?$",
    re.ASCII,
)
PNL_DEST_RE = re.compile(r"^-([A-Z]{3})([0-9]{1,3})([A-Z])(?:-PAD([0-9]{1,3}))?$", re.ASCII)
PNL_ANA_RE = re.compile(r"^ANA/([A-Z0-9]+)$", re.ASCII)
PNL_NAME_COUNT_RE = re.compile(r"^([0-9]+)")
SSR_SUMMARY_RE = re.compile(r"^(?:SSR|\.R/)\s*([A-Z]{2,4})(?=\s|/|$)", re.ASCII)

FAMILIES = {
    "MVT": "MOVEMENT", "MVA": "MOVEMENT",
    "DIV": "DIVERSION",
    "LDM": "LOAD",
    "PTM": "TRANSFER",
    "PSM": "ASSISTANCE", "PAL": "ASSISTANCE", "CAL": "ASSISTANCE",
    "PNL": "NAME_LIST", "ADL": "NAME_LIST",
    "FWD": "FORWARD",
    "ASM": "SCHEDULE",
}

ASM_AIRLINES_TO_PROCESS: set = set()

# Data segregation: LDM DB-facing fields that must be remapped to AODB target
# columns (AHM 583 spec section 4). These protect real-time FIDS values by
# staging them under AMG_*. Direct columns (CRW, DDL, PX1-PX7) take no remap,
# so they are intentionally absent — apply_column_mappings leaves their keys
# untouched. The ldm_remap view in cli.py is built from this mapping.
INTERFACE_COLUMN_MAPPINGS: dict = {
    "REG": "AMG_REG",
    "PAX": "AMG_PAX",
    "SI": "AMG_SIT",
    "SIT": "AMG_SIT",  # spec alias for the SI remarks field
}


class MalformedMessage(ValueError):
    pass


def validate_lines(raw_text, strict=STRICT_LINE_VALIDATION):
    lines = raw_text.replace("\r\n", "\n").split("\n")
    if strict:
        for line in lines:
            if len(line) > LINE_LIMIT:
                raise MalformedMessage(f"line exceeds {LINE_LIMIT} chars: {line[:40]!r}")
    return lines


def count_line_violations(raw_text):
    return sum(1 for line in validate_lines(raw_text) if len(line) > LINE_LIMIT)


TIME_CODE_MAP = {
    "AD": "AD", "AB": "AB", "TD": "TD", "AA": "AA",
    "EO": "EO", "EA": "EL", "EL": "EL", "RA": "RA",
    "EB": "EA", "ED": "ED", "EAN": "EAN", "EDP": "EDP",
}


def _split_time(value):
    if len(value) == 6:
        return {"time": value[2:], "date": value[:2]}
    return {"time": value, "date": None}


def _times(raw_text):
    """AHM 780 mapping: an AD pair is AD(off-blocks)+EO(airborne); an EA token
    maps to EL(estimated landing); an EB token maps to EA(estimated
    on-blocks); an AA pair is TD(touchdown)+AA(on-blocks); a 6-digit group is
    DDHHMM so date rides along."""
    times = {}
    destination = None
    for line in validate_lines(raw_text):
        tokens = line.split()
        for index, token in enumerate(tokens):
            match = TIMES_RE.match(token)
            if not match:
                continue
            raw_code, first, second = match.group(1), match.group(2), match.group(3)
            code = TIME_CODE_MAP[raw_code]
            if raw_code == "AA" and second:
                if "TD" not in times:
                    times["TD"] = _split_time(first)
                times["AA"] = _split_time(second)
                continue
            times[code] = _split_time(first)
            if second and raw_code == "AD":
                times["EO"] = _split_time(second)
        if destination is None:
            for i in range(len(tokens) - 1):
                m = TIMES_RE.match(tokens[i])
                if (m and TIME_CODE_MAP[m.group(1)] in ("EL", "RA")
                        and DEST_TOKEN_RE.match(tokens[i + 1])):
                    destination = tokens[i + 1]
                    break
    return times, destination


def _delay_slots(raw_text):
    """DL line fills IR1/DL1.., EDL line continues at IR3/DL3.., DLA adds
    reason codes only at IR5+. Within a line, slash-groups alternate
    reason-code then duration."""
    slots = {}
    base_for = {"DL": 1, "EDL": 3}
    dla_codes = []
    for line in validate_lines(raw_text):
        stripped = line.strip()
        if stripped.startswith("DLA"):
            dla_codes.extend(p for p in stripped[3:].split("/") if p)
            continue
        prefix = "EDL" if stripped.startswith("EDL") else (
            "DL" if stripped.startswith("DL") else None)
        if prefix is None:
            continue
        ordered = []
        for token in stripped[len(prefix):].split():
            parts = [re.sub(r"^DL", "", p) for p in token.split("/") if p]
            for position, part in enumerate(parts):
                ordered.append(("DL" if position % 2 else "IR", part))
        ir_next = dl_next = base_for[prefix]
        for role, value in ordered:
            if role == "IR":
                while ir_next <= 8 and f"IR{ir_next}" in slots:
                    ir_next += 1
                if ir_next > 8:
                    continue
                slots[f"IR{ir_next}"] = value
                ir_next += 1
            else:
                while dl_next <= 8 and f"DL{dl_next}" in slots:
                    dl_next += 1
                if dl_next > 8:
                    continue
                slots[f"DL{dl_next}"] = value.zfill(4)
                dl_next += 1
    for offset, code in enumerate(dla_codes[:4]):
        slots[f"IR{5 + offset}"] = code
    return slots


SI_VALUE_KEYS = {
    "FR": "fuel_remaining", "EET": "eet", "BO": "burn_off",
    "TOF": "takeoff_fuel", "PL": "payload", "ZFW": "zfw",
}
EVENT_TIME_RE = re.compile(r"^\d{4}$")
SI_MARKER_RE = re.compile(r"^SI\b")


def _si_value(text):
    if re.fullmatch(r"\d+", text):
        if len(text) > 1 and text.startswith("0"):
            return text
        return int(text)
    if re.fullmatch(r"\d+\.\d+", text):
        return float(text)
    return text


def _absorb_si_tokens(tokens, si, events):
    i = 0
    matched_any = False
    while i < len(tokens):
        token = tokens[i]
        for key, name in SI_VALUE_KEYS.items():
            if token == key and i + 1 < len(tokens):
                j = i + 1
                if "/" in tokens[j] and j + 1 < len(tokens):
                    j += 1
                si[name] = _si_value(tokens[j])
                i = j
                matched_any = True
                break
            if token.startswith(key) and len(token) > len(key) and not token.isalpha():
                si[name] = _si_value(token[len(key):])
                matched_any = True
                break
        i += 1
    if not matched_any and tokens and EVENT_TIME_RE.match(tokens[-1]):
        label = " ".join(tokens[:-1])
        if label:
            events.append({"label": label, "time": tokens[-1]})


def _si_section(raw_text):
    si, events = {}, []
    collecting = False
    for line in validate_lines(raw_text):
        stripped = line.strip()
        if SI_MARKER_RE.match(stripped):
            collecting = True
            rest = stripped[2:].strip()
            if rest:
                _absorb_si_tokens(rest.split(), si, events)
            continue
        if not stripped:
            collecting = False
            continue
        if collecting:
            if stripped.startswith("\x03") or stripped.startswith("END"):
                collecting = False
                continue
            _absorb_si_tokens(stripped.split(), si, events)
    if events:
        si["events"] = events
    return si


def extract_movement(raw_text):
    tokens_set = set(raw_text.replace("\r\n", " ").split())
    times, destination = _times(raw_text)
    facts = {
        "times": times,
        "adp": "ADP" in tokens_set,
        "abp": "ABP" in tokens_set,
    }
    if destination:
        facts["destination"] = destination
    si = _si_section(raw_text)
    if si:
        facts["si"] = si
    slots = _delay_slots(raw_text)
    if slots:
        facts["delays"] = slots
        facts["delay_codes"] = [v for k, v in sorted(slots.items()) if k.startswith("IR")]
        facts["delay_durations"] = [v for k, v in sorted(slots.items()) if k.startswith("DL")]
    pax = {}
    slash = PX_SLASH_RE.search(raw_text)
    if slash:
        pax["transit"] = int(slash.group(1))
        pax["disembarking"] = int(slash.group(2))
        pax["total"] = int(slash.group(1)) + int(slash.group(2))
    else:
        total = PAX_TOTAL_RE.search(raw_text)
        if total:
            pax["total"] = int(total.group(1))
            if total.group(2):
                pax["infants"] = int(total.group(2))
    if pax:
        facts["pax"] = pax
    return facts


def extract_diversion(raw_text):
    facts = {"can": bool(CAN_RE.search(raw_text))}
    pob = POB_RE.search(raw_text)
    if pob:
        facts["pob"] = int(pob.group(1))
    eta = DVA_ETA_RE.search(raw_text)
    if eta:
        facts["eta"] = eta.group(1)
        facts["dva"] = eta.group(2)
    return facts


def _split_pax_classes(values):
    nums = [int(v) for v in values.split("/")]
    if len(nums) == 3:
        return {"first": nums[0], "business": nums[1], "economy": nums[2]}
    return {"first": 0, "business": nums[0], "economy": nums[1]}


def _ldm_class_totals(segment):
    classes = segment.get("classes", {})
    return {"first": classes.get("first", 0),
            "business": classes.get("business", 0),
            "economy": classes.get("economy", 0)}


def _parse_ldm_segment_tokens(tokens, segment):
    for token in tokens:
        if not token:
            continue
        if LDM_NIL_RE.match(token):
            segment["nil_traffic"] = True
            continue
        deadload = LDM_DEADLOAD_RE.match(token)
        if deadload:
            segment["deadload"] = int(deadload.group(1))
            continue
        pax_class = LDM_PAX_CLASS_RE.match(token)
        if pax_class:
            segment["classes"] = _split_pax_classes(pax_class.group(1))
            continue
        pad_class = LDM_PAD_CLASS_RE.match(token)
        if pad_class:
            segment["pads"] = _split_pax_classes(pad_class.group(1))
            continue
        if LDM_PAX_TOTAL_RE.match(token) or LDM_PAD_TOTAL_RE.match(token):
            continue
        if LDM_SEG_PAX_RE.match(token):
            parts = [int(v) for v in token.split("/")]
            if len(parts) == 4:
                segment["adults"] = parts[0] + parts[1]
                segment["children"] = parts[2]
                segment["infants"] = parts[3]
            else:
                segment["adults"], segment["children"], segment["infants"] = parts
            segment["pax_total"] = segment["adults"] + segment["children"]
            continue
        if LDM_COMPARTMENT_RE.match(token):
            continue
        category = LDM_CATEGORY_RE.match(token)
        if category:
            segment["categories"].append({
                "code": category.group(1),
                "count": int(category.group(2)),
                "weight": int(category.group(3)) if category.group(3) else 0,
            })
            continue


def _parse_ldm_segments(raw_text):
    segments, current = [], None
    for line in validate_lines(raw_text):
        stripped = line.strip()
        if stripped.startswith("-") and len(stripped) >= 4 and stripped[1:4].isalpha():
            dest = stripped[1:4].upper()
            current = {
                "dest": dest,
                "nil_traffic": False,
                "adults": 0,
                "children": 0,
                "infants": 0,
                "pax_total": 0,
                "deadload": 0,
                "classes": {"first": 0, "business": 0, "economy": 0},
                "pads": {"first": 0, "business": 0, "economy": 0},
                "categories": [],
            }
            segments.append(current)
            _parse_ldm_segment_tokens(stripped[4:].split("."), current)
            continue
        if stripped.startswith(".") and current is not None:
            _parse_ldm_segment_tokens(stripped.split("."), current)
    return segments


def _ldm_header(raw_text):
    for line in validate_lines(raw_text):
        stripped = line.strip()
        match = LDM_HEADER_RE.match(stripped)
        if not match or match.group("day") is None:
            continue
        g = match.groupdict()
        crew_cab = (int(g["crew_cab"]) if g["crew_cab"] else 0) + (
            int(g["crew_cab_f"]) if g["crew_cab_f"] else 0
        )
        crew_ckpt = int(g["crew_ckpt"]) if g["crew_ckpt"] else 0
        facts = {
            "carrier": g["carrier"],
            "flight_num": g["flight_num"],
            "day_of_month": int(g["day"][:2]),
        }
        if g["suffix"]:
            facts["suffix"] = g["suffix"]
        if g["reg"]:
            facts["reg"] = g["reg"].upper()
        if g["type"]:
            facts["ac_type"] = g["type"].upper()
        if crew_ckpt or crew_cab:
            facts["crew"] = {"cockpit": crew_ckpt, "cabin": crew_cab, "total": crew_ckpt + crew_cab}
        cabins = {}
        for run in CABIN_RUN_RE.findall(stripped):
            for code, count in CABIN_PAIR_RE.findall(run):
                cabins[code] = int(count)
        if cabins:
            facts["cabins"] = cabins
        return facts
    return {}


def _ldm_si(raw_text):
    si_lines, collecting = [], False
    breakdown = None
    for line in validate_lines(raw_text):
        stripped = line.strip()
        if stripped.upper().startswith("SI") and (
            len(stripped) == 2 or stripped[2:3].isspace()
        ):
            collecting = True
            if len(stripped) > 2:
                si_lines.append(stripped[3:].strip())
            continue
        if not collecting:
            continue
        if re.match(r"^END", stripped, re.IGNORECASE):
            break
        if not stripped or stripped.startswith("\x03"):
            break
        if stripped:
            match = SI_BREAKDOWN_RE.match(stripped)
            if match and breakdown is None:
                breakdown = {
                    "station": match.group("station"),
                    "fre": int(match.group("fre")),
                    "pos": int(match.group("pos")),
                    "bag": int(match.group("bag")),
                    "tra": int(match.group("tra")),
                }
                if match.group("bag_weight"):
                    breakdown["bag_weight"] = int(match.group("bag_weight"))
            si_lines.append(stripped)
    # Collapse runs of whitespace to a single space across the whole SI block.
    si_text = " ".join(si_lines).strip()
    si_text = re.sub(r"\s{2,}", " ", si_text)
    return si_text, breakdown


def extract_load(raw_text):
    facts, segments = {}, []
    header = _ldm_header(raw_text)
    if header.get("reg"):
        facts["reg"] = header["reg"]
    if header.get("cabins"):
        facts["cabins"] = header["cabins"]
    if header.get("crew"):
        facts["crew"] = header["crew"]
    if header.get("ac_type"):
        facts["ac_type"] = header["ac_type"]

    parsed_segments = _parse_ldm_segments(raw_text)
    for seg in parsed_segments:
        segments.append({
            "dest": seg["dest"],
            "nil_traffic": seg["nil_traffic"],
            "adults": seg["adults"],
            "children": seg["children"],
            "infants": seg["infants"],
            "pax_total": seg["pax_total"],
            "deadload": seg["deadload"],
            "classes": seg["classes"],
            "pads": seg["pads"],
            "categories": seg["categories"],
        })

    si_text, breakdown = _ldm_si(raw_text)
    if si_text:
        facts["si"] = si_text
    if breakdown:
        facts["station_breakdown"] = breakdown

    flattened = _aggregate_load(parsed_segments)
    for key, value in flattened.items():
        facts[key] = value

    bw = BW_RE.search(raw_text)
    if bw:
        facts["basic_weight"] = int(bw.group(1))
    bi = BI_RE.search(raw_text)
    if bi:
        facts["balance_index"] = float(bi.group(1))
    return facts, segments


def _aggregate_load(segments, current_station="HKG"):
    if not segments:
        return {}
    route = []
    for seg in segments:
        if seg["dest"] not in route:
            route.append(seg["dest"])
    if current_station not in route:
        current_station = route[0]
    local = next((s for s in segments if s["dest"] == current_station), None)
    if local is None:
        return {}
    idx = route.index(current_station)
    downstream = [s for s in segments
                  if s["dest"] in route[idx + 1:] and not s["nil_traffic"]]

    def pax(s):
        return s["adults"] + s["children"]

    local_pax = pax(local) if not local["nil_traffic"] else 0
    transit_pax = sum(pax(s) for s in downstream)
    total_pax = local_pax + transit_pax

    local_classes = _ldm_class_totals(local)
    first = local_classes["first"]
    business = local_classes["business"]
    economy = local_classes["economy"]
    for s in downstream:
        c = _ldm_class_totals(s)
        first += c["first"]
        business += c["business"]
        economy += c["economy"]

    local_ddl = 0 if local["nil_traffic"] else local["deadload"]
    deadload = local_ddl + sum(s["deadload"] for s in downstream)

    return {
        "local_station": current_station,
        "px7": local_pax,
        "px6": transit_pax,
        "pax": total_pax,
        "px1": first,
        "px2": business,
        "px3": economy,
        "ddl": deadload,
    }


def _ptm_row(line):
    match = PTM_ROW_RE.match(line.strip())
    if not match:
        return None
    flight, day, airports, rest = match.groups()
    tokens = rest.split()
    detail_tokens = [t for t in tokens if "/" not in t]
    return {
        "flight": flight,
        "day": day,
        "airports": airports,
        "cabin_bags": " ".join(detail_tokens),
    }


def extract_transfer(raw_text):
    facts, segments = {}, []
    px = PX_RE.search(raw_text)
    if px:
        facts["total_transfers"] = int(px.group(1))
    bg = BG_RE.search(raw_text)
    if bg:
        facts["total_baggage"] = int(bg.group(1))
    for line in validate_lines(raw_text):
        if "PART" in line:
            continue
        row = _ptm_row(line)
        if row:
            segments.append(row)
    if segments:
        facts["segments"] = len(segments)
    return facts, segments


def _assistance_facts(raw_text):
    codes = sorted(set(code.upper() for code in ASSIST_CODE_RE.findall(raw_text)))
    delta = {op: 0 for op in ("ADD", "DEL", "CHG")}
    current = None
    for line in validate_lines(raw_text):
        marker = OP_MARKER_RE.match(line.strip())
        if marker:
            current = marker.group(1)
            continue
        if NAME_ROW_RE.match(line) and current:
            delta[current] += 1
    pax_total = sum(int(n) for n in re.findall(r"(\d+)PAX", raw_text))
    facts = {"assist_codes": codes}
    if any(delta.values()):
        facts["delta"] = {op: n for op, n in delta.items() if n}
    if pax_total:
        facts["pax_total"] = pax_total
    return facts


def extract_assistance(raw_text):
    return _assistance_facts(raw_text)


def extract_name_list(raw_text):
    """Parse an RP 1708 PNL/ADL passenger count message.

    Returns ``(facts, segments)``. Passenger names, record locators and SSR
    contact detail are consumed only to tally counts — they are never emitted,
    matching the count-only privacy policy for the NAME_LIST family.
    """
    facts = {"family_kind": "NAME_LIST"}
    lines = validate_lines(raw_text)

    cfg = CFG_RE.search(raw_text)
    if cfg:
        facts["cfg"] = cfg.group(1)

    for line in lines:
        flight = PNL_FLIGHT_RE.match(line.strip())
        if flight:
            facts["carrier"] = flight.group(1)
            facts["flight_number"] = flight.group(2)
            facts["suffix"] = flight.group(3) or ""
            facts["dep_day"] = flight.group(4)
            facts["dep_month"] = flight.group(5)
            facts["boarding_airport"] = flight.group(6)
            facts["part_number"] = int(flight.group(7)) if flight.group(7) else 1
            break

    for line in lines:
        ana = PNL_ANA_RE.match(line.strip())
        if ana:
            facts["ana"] = ana.group(1)
            break

    segments = []
    current = None
    for line in lines:
        stripped = line.strip()
        dest = PNL_DEST_RE.match(stripped)
        if dest:
            segments.append({
                "dest": dest.group(1),
                "declared_total": int(dest.group(2)),
                "cabin_class": dest.group(3),
                "pad_total": int(dest.group(4)) if dest.group(4) else 0,
                "actual_parsed_pax": 0,
            })
            current = len(segments) - 1
            continue
        if current is not None and NAME_ROW_RE.match(stripped):
            count = PNL_NAME_COUNT_RE.match(stripped)
            if count:
                segments[current]["actual_parsed_pax"] += int(count.group(1))

    facts["name_rows"] = sum(1 for l in lines if NAME_ROW_RE.match(l))
    facts["identifier_rows"] = sum(1 for l in lines if IDENTIFIER_ROW_RE.match(l))

    delta = {op: 0 for op in ("ADD", "DEL", "CHG")}
    current_op = None
    for line in lines:
        marker = OP_MARKER_RE.match(line.strip())
        if marker:
            current_op = marker.group(1)
            continue
        if NAME_ROW_RE.match(line) and current_op:
            delta[current_op] += 1
    if any(delta.values()):
        facts["changes"] = {op: n for op, n in delta.items() if n}

    ssr_codes = {}
    for line in lines:
        m = SSR_SUMMARY_RE.match(line.strip())
        if m:
            code = m.group(1)
            ssr_codes[code] = ssr_codes.get(code, 0) + 1
    if ssr_codes:
        facts["ssrs"] = ssr_codes

    boarding = facts.get("boarding_airport")
    if boarding is not None:
        agg = _aggregate_pnl(segments, boarding)
        facts.update(agg)

    return facts, segments


def _aggregate_pnl(segments, boarding):
    """Aggregate PXE/PX6 given the boarding (sending) station and the inbound
    destination legs, per RP 1708 section 4 for the HKG context.

    - boarding == HKG        : departure context, PXE = all on board, PX6 nil.
    - boarding upstream of HKG: arrival + departure, PXE = all, PX6 = downline.
    - boarding downstream     : no action.
    """
    ordered = list(dict.fromkeys(s["dest"] for s in segments))
    total = sum(s["declared_total"] for s in segments)
    if boarding == "HKG":
        return {"pxe": total, "px6": None,
                "arrival_action": False, "departure_action": True, "no_action": False}
    if "HKG" in ordered:
        downline = ordered[ordered.index("HKG") + 1:]
        px6 = sum(s["declared_total"] for s in segments if s["dest"] in downline)
        return {"pxe": total, "px6": px6,
                "arrival_action": True, "departure_action": True, "no_action": False}
    return {"pxe": None, "px6": None,
            "arrival_action": False, "departure_action": False, "no_action": True}


def extract_forward(raw_text):
    facts, segments = {}, []
    for line in validate_lines(raw_text):
        header = FWD_CREW_RE.match(line.strip())
        if header:
            facts["crew"] = header.group(2)
            break

    matches = list(FWD_DASH_DEST_RE.finditer(raw_text))
    destinations = []
    merged_nationalities = {}
    first_components = None
    for i, match in enumerate(matches):
        airport = match.group(1)
        components = {code: int(n) for code, n in FWD_COMPONENT_RE.findall(match.group(2))}
        block = {"airport": airport, **components}
        tail_end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
        chunk = raw_text[match.end():tail_end]
        nats = {code: int(n) for code, n in NATIONALITY_RE.findall(chunk)}
        if nats:
            block["nationalities"] = nats
            for code, n in nats.items():
                merged_nationalities[code] = merged_nationalities.get(code, 0) + n
        destinations.append(block)
        if first_components is None:
            first_components = components
    if destinations:
        facts["destination"] = destinations[-1]["airport"]
        facts["destinations"] = destinations
        facts["hops"] = len(destinations)
        facts["components"] = first_components
    if merged_nationalities:
        facts["nationalities"] = merged_nationalities

    current_hop = None
    in_rows = False
    for line in validate_lines(raw_text):
        stripped = line.strip()
        if stripped == "ENDFWD":
            break
        hop = FWD_DASH_DEST_RE.search(line)
        if hop and not stripped.startswith("FWD"):
            current_hop = hop.group(1)
            continue
        if stripped == ".P":
            in_rows = True
            continue
        if in_rows and stripped and stripped != "\x03":
            tokens = stripped.split()
            if len(tokens) >= 3 and not tokens[0].startswith("."):
                segments.append({
                    "hop": current_hop,
                    "flight": tokens[0],
                    "destination": tokens[1],
                    "detail": " ".join(tokens[2:]),
                })
    if segments:
        facts["rows"] = len(segments)
    return facts, segments


EXTRACTORS = {
    "MVT": lambda t: (extract_movement(t), []),
    "MVA": lambda t: (extract_movement(t), []),
    "DIV": lambda t: (extract_diversion(t), []),
    "LDM": extract_load,
    "PTM": lambda t: extract_transfer(t),
    "PSM": lambda t: (extract_assistance(t), []),
    "PAL": lambda t: (extract_assistance(t), []),
    "CAL": lambda t: (extract_assistance(t), []),
    "PNL": extract_name_list,
    "ADL": extract_name_list,
    "FWD": lambda t: extract_forward(t),
}


FULL_REDACT_TYPES = {"PNL", "ADL"}


def _redact_lines(raw_text):
    newline = "\r\n" if "\r\n" in raw_text else "\n"
    return raw_text.split(newline), newline


def redact_text(msg_type, raw_text):
    if msg_type in FULL_REDACT_TYPES:
        lines, newline = _redact_lines(raw_text)
        out = []
        for line in lines:
            if NAME_ROW_RE.match(line) or IDENTIFIER_ROW_RE.match(line):
                out.append("[REDACTED]")
            else:
                out.append(line)
        return newline.join(out)
    if msg_type in ("PTM", "PSM", "PAL", "CAL"):
        lines, newline = _redact_lines(raw_text)
        out = []
        for line in lines:
            stripped = line.strip()
            if NAME_ROW_RE.match(stripped):
                tokens = line.split()
                if tokens and not tokens[0].startswith("."):
                    tokens[0] = "[REDACTED]"
                line = " ".join(tokens)
            elif msg_type == "PTM" and "PART" not in stripped:
                tokens = line.split()
                for i in range(len(tokens) - 1, -1, -1):
                    if "/" in tokens[i] and not tokens[i].startswith("."):
                        tokens[i] = "[REDACTED]"
                        break
                line = " ".join(tokens)
            out.append(line)
        return newline.join(out)
    return None


def apply_column_mappings(facts, mappings=None):
    mappings = mappings if mappings is not None else INTERFACE_COLUMN_MAPPINGS
    remapped = {}
    for key, value in facts.items():
        target = mappings.get(key.upper(), key)
        if target is None:
            continue
        remapped[target] = value
    return remapped


def extract_message(msg_type, raw_text):
    family = FAMILIES.get(msg_type)
    if family is None:
        return None
    facts = {}
    segments = []
    if msg_type == "ASM":
        prefix = _asm_airline(raw_text)
        if prefix not in ASM_AIRLINES_TO_PROCESS:
            return {
                "family": family,
                "facts": {"muted": True, "airline": prefix},
                "segments": [],
            }
        facts["muted"] = False
        facts["airline"] = prefix
        info_line = next(
            (l.strip() for l in validate_lines(raw_text)
             if re.match(r"^[A-Z0-9]{2,3}\d+[A-Z]?/", l.strip())), ""
        )
        flight = re.match(r"^([A-Z0-9]+)", info_line)
        if flight:
            facts["flight_number"] = flight.group(1)
    else:
        facts, segments = EXTRACTORS[msg_type](raw_text)
    facts["line_limit_violations"] = count_line_violations(raw_text)
    # Data segregation applies to LDM load facts only (AHM 583 spec section 4);
    # other families keep their natural keys so the mapping can't corrupt them.
    if family == "LOAD":
        facts = apply_column_mappings(facts)
    return {"family": family, "facts": facts, "segments": segments}


def _asm_airline(raw_text):
    for line in validate_lines(raw_text):
        match = re.match(r"^[A-Z0-9]{2,3}\d+[A-Z]?/", line.strip())
        if match:
            prefix = re.match(r"([A-Z]+)", match.group(0))
            if prefix:
                return prefix.group(1)
    return None


def dumps(value):
    return json.dumps(value, sort_keys=True)

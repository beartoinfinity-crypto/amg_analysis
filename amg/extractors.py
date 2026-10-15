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
POB_RE = re.compile(r"\b(?:POB|PX)(\d+)\b", re.IGNORECASE)
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
ASSIST_CODE_RE = re.compile(r"(?<![A-Z0-9])(WCHR|WCHC|WCHS|WCB|DEAF|BLND|MEDA|UMNR|MAAS|ESAN|DPNA)(?![A-Z])")
NAME_ROW_RE = re.compile(r"^\d[A-Z]")
IDENTIFIER_ROW_RE = re.compile(r"^\.[A-Z][A-Z0-9]{0,2}/")
CFG_RE = re.compile(r"CFG/([A-Z0-9/]+)")
OP_MARKER_RE = re.compile(r"(?:^|\s)(ADD|DEL|CHG)\s*$", re.MULTILINE)
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
MVT_HEADER_RE = re.compile(
    r"^(?P<carrier>[A-Z]{2})(?P<flight_num>\d{1,4})(?P<suffix>[A-Z])?/"
    r"(?P<day>\d{2})\.(?P<reg>[A-Z0-9\-]+)\.(?P<apt>[A-Z]{3})$",
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
# Transmission terminator: ENDPARTn closes one part, ENDPNL/ENDADL close the
# whole multi-part transmission. A burst of parts is only complete once the
# final terminator arrives.
PNL_TERMINATOR_RE = re.compile(r"^(ENDPART[0-9]*|ENDPNL|ENDADL)$", re.ASCII)

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
    """Split ``raw_text`` into lines, validating line length if ``strict``.

    Normalizes CRLF to LF, splits on newline. In strict mode, any line
    exceeding ``LINE_LIMIT`` characters raises ``MalformedMessage``.

    Args:
        raw_text: Raw message text.
        strict: If True, raise on over-length lines; else silently accept.

    Returns:
        list[str]: Normalized lines.
    """
    lines = raw_text.replace("\r\n", "\n").split("\n")
    if strict:
        for line in lines:
            if len(line) > LINE_LIMIT:
                raise MalformedMessage(f"line exceeds {LINE_LIMIT} chars: {line[:40]!r}")
    return lines


def count_line_violations(raw_text):
    """Count lines in ``raw_text`` that exceed ``LINE_LIMIT`` characters.

    Non-strict; used to surface data-quality issues without aborting.

    Returns:
        int: Number of over-length lines.
    """
    return sum(1 for line in validate_lines(raw_text) if len(line) > LINE_LIMIT)


TIME_CODE_MAP = {
    "AD": "AD", "AB": "AB", "TD": "TD", "AA": "AA",
    "EO": "EO", "EA": "EL", "EL": "EL", "RA": "RA",
    "EB": "EA", "ED": "ED", "EAN": "EAN", "EDP": "EDP",
}


def _split_time(value):
    """Split a 6-char ``DDHHMM`` time value or pass a shorter one through.

    If ``value`` is 6 chars, returns ``{"time": value[2:], "date": value[:2]}``;
    otherwise returns ``{"time": value, "date": None}``.

    Args:
        value: Time token from a times line.

    Returns:
        dict: Keys ``time`` and ``date``.
    """
    if len(value) == 6:
        return {"time": value[2:], "date": value[:2]}
    return {"time": value, "date": None}


def _times(raw_text):
    """AHM 780 mapping: an AD pair is AD(off-blocks first)/AB(airborne
    second); a standalone EO token is estimated take-off; an EA token
    maps to EL(estimated landing); an EB token maps to EA(estimated
    on-blocks); an AA pair is AA(on-blocks first)/TD(touchdown second); a
    6-digit group is DDHHMM so date rides along."""
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
                times["AA"] = _split_time(first)
                if "TD" not in times:
                    times["TD"] = _split_time(second)
                continue
            times[code] = _split_time(first)
            if second and raw_code == "AD":
                times["AB"] = _split_time(second)
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
    reason codes only at IR5+. Within a DL/EDL line each space-separated
    token is either a two-group IR/DL pair or a four-group multi-form
    IR1/IR2/DL1/DL2; empty DLA groups skip an IR slot (so ``93//11/``
    yields IR5 and IR7)."""
    slots = {}
    base_for = {"DL": 1, "EDL": 3}
    dla_codes = []
    for line in validate_lines(raw_text):
        stripped = line.strip()
        if stripped.startswith("DLA"):
            dla_codes.extend(p.strip() for p in stripped[3:].split("/"))
            continue
        prefix = "EDL" if stripped.startswith("EDL") else (
            "DL" if stripped.startswith("DL") else None)
        if prefix is None:
            continue
        ir_next = dl_next = base_for[prefix]
        # Each space-separated token is one IR/DL pair or a multi-group form
        for token in stripped[len(prefix):].split():
            groups = [re.sub(r"^DL", "", p).strip() for p in token.split("/") if p]
            if len(groups) >= 4:
                # Multi-group: first half IRs, second half DLs
                mid = len(groups) // 2
                ordered = [("IR", g) for g in groups[:mid]] + [("DL", g) for g in groups[mid:]]
            else:
                # Two-group form: IR/DL pair
                ordered = [("IR", groups[0])] if groups else []
                if len(groups) >= 2:
                    ordered.append(("DL", groups[1]))
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
    slot_idx = 5
    for code in dla_codes:
        if code:
            slots[f"IR{slot_idx}"] = code
        slot_idx += 1
        if slot_idx > 8:
            break
    return slots


SI_VALUE_KEYS = {
    "FR": "fuel_remaining", "EET": "eet", "BO": "burn_off",
    "TOF": "takeoff_fuel", "PL": "payload", "ZFW": "zfw",
}
EVENT_TIME_RE = re.compile(r"^\d{4}$")
SI_MARKER_RE = re.compile(r"^SI\b")


def _si_value(text):
    """Coerce a SI-section token to int, float, or keep as str.

    Pure-integer tokens are returned as ``int`` unless they have a
    leading zero (preserving format). Decimal tokens become ``float``;
    anything else is returned unchanged as ``str``.

    Args:
        text: Token text from an SI section.

    Returns:
        int | float | str: Coerced value.
    """
    if re.fullmatch(r"\d+", text):
        if len(text) > 1 and text.startswith("0"):
            return text
        return int(text)
    if re.fullmatch(r"\d+\.\d+", text):
        return float(text)
    return text


def _absorb_si_tokens(tokens, si, events, free_text=None):
    """Parse SI-section tokens into structured ``si``/``events`` dicts.

    Walks a token list, matching known SI keys (FR/EET/BO/TOF/PL/ZFW etc.)
    and event-time patterns, populating ``si`` and appending ``(key, time)``
    tuples to ``events``. Unrecognized tokens accumulate in ``free_text``
    when provided. Returns True if any known key was matched.

    Args:
        tokens: Space-split tokens from an SI line.
        si: Mutable dict of SI values, updated in place.
        events: Mutable list of event tuples, appended to in place.
        free_text: Optional list collecting unmatched tokens.

    Returns:
        bool: True if at least one known SI key was recognized.
    """
    i = 0
    matched_any = False
    while i < len(tokens):
        token = tokens[i]
        claimed = False
        for key, name in SI_VALUE_KEYS.items():
            if token == key and i + 1 < len(tokens):
                j = i + 1
                if "/" in tokens[j] and j + 1 < len(tokens):
                    j += 1
                si[name] = _si_value(tokens[j])
                i = j
                matched_any = True
                claimed = True
                break
            if token.startswith(key) and len(token) > len(key) and not token.isalpha():
                si[name] = _si_value(token[len(key):])
                matched_any = True
                claimed = True
                break
        if not claimed and free_text is not None:
            free_text.append(token)
        i += 1
    if not matched_any and tokens and EVENT_TIME_RE.match(tokens[-1]):
        label = " ".join(tokens[:-1])
        if label:
            events.append({"label": label, "time": tokens[-1]})


def _si_section(raw_text):
    """Parse the SI (supplementary information) section of a message.

    Scans lines for an ``SI`` marker, then accumulates tokens via
    ``_absorb_si_tokens`` until a blank line, ``ETX``, or ``END`` ends
    the section. Events and free text are folded back into the returned
    dict.

    Args:
        raw_text: Raw message text.

    Returns:
        dict: SI name/value pairs. Includes an ``events`` key (list of
        event dicts) when events were found, and a ``text`` key (joined
        free-text tokens) when free text exists without events.
    """
    si, events = {}, []
    free_text = []
    collecting = False
    for line in validate_lines(raw_text):
        stripped = line.strip()
        if SI_MARKER_RE.match(stripped):
            collecting = True
            rest = stripped[2:].strip()
            if rest:
                _absorb_si_tokens(rest.split(), si, events, free_text)
            continue
        if not stripped:
            collecting = False
            continue
        if collecting:
            if stripped.startswith("\x03") or stripped.startswith("END"):
                collecting = False
                continue
            _absorb_si_tokens(stripped.split(), si, events, free_text)
    if events:
        si["events"] = events
    if free_text and not events:
        # Only store free text when it is not an event-label + time pair
        si["text"] = " ".join(free_text)
    return si


def _mvt_header(raw_text):
    """MVT/MVA flight header: ``BA123/16.AB1234.HKG`` (spec v3 §2.2)."""
    for line in validate_lines(raw_text):
        stripped = line.strip()
        match = MVT_HEADER_RE.match(stripped)
        if not match:
            continue
        g = match.groupdict()
        header = {
            "carrier": g["carrier"],
            "flight_num": g["flight_num"],
            "day": int(g["day"]),
            "reg": g["reg"],
            "apt": g["apt"],
        }
        if g["suffix"]:
            header["suffix"] = g["suffix"]
        return header
    return {}


def extract_movement(raw_text):
    """Extract movement (MVT/MVA) facts from a raw message.

    Parses flight header, times, ADP/ABP flags, SI section, delay
    slots, and destination from the message text. Returns a dict of
    facts suitable for the ``facts`` JSON column.

    Args:
        raw_text: Raw message text.

    Returns:
        dict: Movement facts including times, header, SI, delay slots.
    """
    tokens_set = set(raw_text.replace("\r\n", " ").split())
    times, destination = _times(raw_text)
    facts = {
        "times": times,
        "adp": "ADP" in tokens_set,
        "abp": "ABP" in tokens_set,
    }
    header = _mvt_header(raw_text)
    if header:
        facts["flight_header"] = header
        facts["AMG_REG"] = header["reg"]
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
    """Extract diversion (DVA) facts from a raw message.

    Parses CAN flag, POB (persons on board), ETA, and DVA code.
    Returns a dict of diversion facts.

    Args:
        raw_text: Raw message text.

    Returns:
        dict: Diversion facts including can, pob, eta, dva.
    """
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
    """Split a slash-delimited passenger class string into a dict.

    Accepts ``"F/J/Y"`` (first/business/economy) or ``"J/Y"``
    (business/economy, first defaults to 0).

    Args:
        values: Slash-delimited class counts.

    Returns:
        dict: Keys ``first``, ``business``, ``economy``.
    """
    nums = [int(v) for v in values.split("/")]
    if len(nums) == 3:
        return {"first": nums[0], "business": nums[1], "economy": nums[2]}
    return {"first": 0, "business": nums[0], "economy": nums[1]}


def _ldm_class_totals(segment):
    """Return first/business/economy totals for an LDM segment, defaulting to 0."""
    classes = segment.get("classes", {})
    return {"first": classes.get("first", 0),
            "business": classes.get("business", 0),
            "economy": classes.get("economy", 0)}


def _parse_ldm_segment_tokens(tokens, segment):
    """Parse LDM segment tokens into a segment dict.

    Recognizes NIL, deadload, pax-class, pad-class, segment-total,
    and compartment/category tokens, populating ``segment`` in place.
    Unrecognized tokens are collected under ``segment['extra']``.

    Args:
        tokens: Space-split tokens from one LDM segment.
        segment: Mutable dict updated in place.
    """
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
    """Parse all LDM segments from a raw message.

    Identifies segment lines starting with ``-XXX`` (three-letter
    destination) and continuation lines starting with ``.``, parsing
    each via ``_parse_ldm_segment_tokens``.

    Args:
        raw_text: Raw message text.

    Returns:
        list[dict]: Parsed segment dicts.
    """
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
    """Parse the LDM message header.

    Extracts carrier, flight number, day of month, aircraft registration,
    departure/arrival airports, and crew cabin/checkpoint counts from
    the header line.

    Args:
        raw_text: Raw message text.

    Returns:
        dict: Header facts or empty dict if no header matched.
    """
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
            facts["reg"] = g["reg"].upper().replace("-", "")
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
    """Parse the SI (supplementary information) section of an LDM message.

    Collects SI lines until a blank line, ``ETX``, or ``END``. Also
    parses a station breakdown line (FRE/POS/BAG/TRA) when present.
    Collapses whitespace runs in the returned SI text.

    Args:
        raw_text: Raw message text.

    Returns:
        tuple: ``(si_text, breakdown)`` where ``si_text`` is the
        collapsed SI text and ``breakdown`` is a dict or None.
    """
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
    """Extract load (LDM) facts and segments from a raw message.

    Parses header (reg, cabins, crew, type), segments, SI section,
    station breakdown, basic weight, and balance index. Also computes
    flattened local/transit totals via ``_aggregate_load``.

    Args:
        raw_text: Raw message text.

    Returns:
        tuple: ``(facts, segments)`` where ``facts`` is a dict of
        load facts and ``segments`` is a list of segment dicts.
    """
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
    """Aggregate LDM segments into local/transit passenger and deadload totals.

    Given a list of parsed LDM segments and the current station, computes
    local boarding pax (px7), transit pax (px6), total pax, cabin class
    totals (px1/px2/px3), and deadload (ddl). Segments beyond the current
    station on the route are transit; NIL segments are excluded.

    Args:
        segments: List of parsed LDM segment dicts.
        current_station: IATA code of the current station (default HKG).

    Returns:
        dict: Aggregated totals or empty dict if no matching segment.
    """
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
    """Parse a single PTM (passenger transfer) row.

    Matches the PTM line pattern, extracting flight, day, airports,
    and cabin/bag detail tokens. Returns None if the line does not
    match.

    Args:
        line: One line of PTM data.

    Returns:
        dict | None: Parsed row or None.
    """
    match = PTM_ROW_RE.match(line.strip())
    if not match:
        return None
    flight, day, airports, rest = match.groups()
    tokens = rest.split()
    detail_tokens = [t for t in tokens if "/" not in t]
    row = {
        "flight": flight,
        "day": day,
        "airports": airports,
        "cabin_bags": " ".join(detail_tokens),
    }
    for t in detail_tokens:
        seats_cls = re.match(r"^(\d+)([A-Z])$", t)
        if seats_cls:
            row["seats"] = int(seats_cls.group(1))
            row["class"] = seats_cls.group(2)
            continue
        bags = re.match(r"^(\d+)B(\d+)?([KL])?$", t)
        if bags:
            row["bags"] = int(bags.group(1))
            if bags.group(2):
                row["weight"] = int(bags.group(2))
    return row


def extract_transfer(raw_text):
    """Extract PTM (passenger transfer) facts and segments.

    Parses total transfers, total baggage, and per-segment rows.
    Falls back to summing segment seats/bags when totals are absent.

    Args:
        raw_text: Raw message text.

    Returns:
        tuple: ``(facts, segments)`` where ``facts`` is a dict of
        transfer totals and ``segments`` is a list of row dicts.
    """
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
        if "total_transfers" not in facts:
            facts["total_transfers"] = sum(s.get("seats", 0) for s in segments)
        if "total_baggage" not in facts:
            facts["total_baggage"] = sum(s.get("bags", 0) for s in segments)
    return facts, segments


def _assistance_facts(raw_text):
    """Extract assistance (SSR/assist) facts from a raw message.

    Parses assist codes, ADD/DEL/CHG delta counts, and pax_total.
    Returns a dict of assistance facts.

    Args:
        raw_text: Raw message text.

    Returns:
        dict: Assistance facts including assist_codes, delta, pax_total.
    """
    codes = sorted(set(code.upper() for code in ASSIST_CODE_RE.findall(raw_text)))
    delta = {op: 0 for op in ("ADD", "DEL", "CHG")}
    current = None
    for line in validate_lines(raw_text):
        marker = OP_MARKER_RE.search(line.strip())
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
    """Extract assistance (SSR/assist) facts. Delegates to ``_assistance_facts``."""
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

    terminator = next(
        (l.strip() for l in reversed(lines) if l.strip() and
         PNL_TERMINATOR_RE.match(l.strip())),
        None,
    )
    if terminator:
        facts["terminator"] = terminator
        facts["final"] = terminator in ("ENDPNL", "ENDADL")

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
    """Extract FWD (forwarded traffic) facts and segments from a raw message.

    Parses crew, destination blocks with component counts, nationalities,
    and passenger rows. Returns ``(facts, segments)`` where ``facts``
    aggregates destinations, hops, and nationalities, and ``segments``
    is the list of parsed passenger rows.

    Args:
        raw_text: Raw message text.

    Returns:
        tuple: ``(facts, segments)``.
    """
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
    """Split raw text into lines, detecting the newline convention.

    Returns ``(lines, newline)`` where ``newline`` is the original
    line-ending string used to rejoin the lines later.
    """
    newline = "\r\n" if "\r\n" in raw_text else "\n"
    return raw_text.split(newline), newline


def redact_text(msg_type, raw_text):
    """Redact passenger names and identifiers per the privacy policy.

    Full redaction for PNL/ADL (name and identifier rows → ``[REDACTED]``).
    Partial redaction for PTM/PSM/PAL/CAL (passenger name token and PNR
    locator redacted, other fields preserved). Returns ``None`` for
    message types with no redaction requirement.

    Args:
        msg_type: Message type code.
        raw_text: Raw message text.

    Returns:
        str or None: Redacted text, or ``None`` if no redaction applies.
    """
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
    """Apply interface column-name mappings to a facts dict.

    Remaps fact keys via ``INTERFACE_COLUMN_MAPPINGS`` (uppercased lookup);
    keys mapped to ``None`` are dropped. Non-LOAD families are unaffected
    because mappings only contain LOAD-specific keys.

    Args:
        facts: Facts dict to remap.
        mappings: Optional mapping override (defaults to module constant).

    Returns:
        dict: Remapped facts.
    """
    mappings = mappings if mappings is not None else INTERFACE_COLUMN_MAPPINGS
    remapped = {}
    for key, value in facts.items():
        target = mappings.get(key.upper(), key)
        if target is None:
            continue
        remapped[target] = value
    return remapped


def extract_message(msg_type, raw_text):
    """Dispatch to the correct family extractor and return a result dict.

    For ASM, checks the airline prefix against ``ASM_AIRLINES_TO_PROCESS``;
    non-target airlines return a muted result. LOAD-family facts are passed
    through ``apply_column_mappings`` for data segregation. All other
    families delegate to ``EXTRACTORS[msg_type]``.

    Args:
        msg_type: Message type code (e.g. ``"MVT"``, ``"LDM"``).
        raw_text: Raw message text.

    Returns:
        dict or None: ``{"family", "facts", "segments"}`` or ``None``
            if ``msg_type`` is not a known family.
    """
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
    """Extract the airline prefix from an ASM message.

    Scans lines for a flight-info pattern (``XXXnnn/``) and returns
    the leading alphabetic prefix. Returns ``None`` if not found.

    Args:
        raw_text: Raw message text.

    Returns:
        str or None: Airline prefix (e.g. ``"CX"``) or ``None``.
    """
    for line in validate_lines(raw_text):
        match = re.match(r"^[A-Z0-9]{2,3}\d+[A-Z]?/", line.strip())
        if match:
            prefix = re.match(r"([A-Z]+)", match.group(0))
            if prefix:
                return prefix.group(1)
    return None


def dumps(value):
    """Serialize a value to a sorted, deterministic JSON string."""
    return json.dumps(value, sort_keys=True)

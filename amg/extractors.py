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
    r"(?<![A-Z0-9])(AD|AB|TD|AA|ED|EA|EL|EO|EAN|EDP)(\d{4}|\d{6})(?:/(\d{4}|\d{6}))?(?![0-9])"
)
DELAY_LINE_RE = re.compile(r"^DL[ /](.+)$")
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

ASSIST_CODES = ("WCHR", "WCHC", "WCHS", "WCB", "DEAF", "BLND", "MEDA", "UMNR", "MAAS", "ESAN")

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

INTERFACE_COLUMN_MAPPINGS: dict = {}


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


def _times(text):
    times = {}
    for code, first, second in TIMES_RE.findall(text):
        times[code] = f"{first}/{second}" if second else first
    return times


def _delays(text):
    codes, durations = [], []
    for line in validate_lines(text):
        stripped = line.strip()
        if not stripped.startswith("DL") or len(stripped) <= 2:
            continue
        for token in stripped[2:].split():
            parts = [re.sub(r"^DL", "", p) for p in token.split("/") if p]
            if len(parts) >= 2:
                codes.append(parts[0])
                durations.append(parts[1])
            elif parts:
                value = parts[0]
                (durations if value.isdigit() and len(value) >= 3 else codes).append(value)
    return codes[:8], durations[:4]


def extract_movement(raw_text):
    tokens = set(raw_text.replace("\r\n", " ").split())
    facts = {
        "times": _times(raw_text),
        "adp": "ADP" in tokens,
        "abp": "ABP" in tokens,
    }
    codes, durations = _delays(raw_text)
    facts["delay_codes"] = codes
    facts["delay_durations"] = durations
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


def extract_load(raw_text):
    facts = {}
    info_line = next((l for l in validate_lines(raw_text)
                      if re.match(r"^[A-Z0-9]{2,3}\d+[A-Z]?/", l.strip())), "")
    cabins = {}
    for run in CABIN_RUN_RE.findall(info_line):
        for code, count in CABIN_PAIR_RE.findall(run):
            cabins[code] = int(count)
    if cabins:
        facts["cabins"] = cabins
    pax = PAX_RE.search(raw_text)
    if pax:
        facts["pax"] = {"adults": int(pax.group(1)), "children": int(pax.group(2)),
                        "infants": int(pax.group(3))}
    pad = PAD_RE.search(raw_text)
    if pad:
        facts["pad"] = {"adults": int(pad.group(1)), "children": int(pad.group(2)),
                        "infants": int(pad.group(3))}
    deadload = DEADLOAD_RE.search(raw_text)
    if deadload:
        facts["deadload"] = int(deadload.group(1))
    crew = CREW_RE.search(raw_text)
    if crew:
        facts["crew"] = {"cockpit": int(crew.group(1)), "cabin": int(crew.group(2))}
    bw = BW_RE.search(raw_text)
    if bw:
        facts["basic_weight"] = int(bw.group(1))
    bi = BI_RE.search(raw_text)
    if bi:
        facts["balance_index"] = float(bi.group(1))
    return facts


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
    facts = {"family_kind": "NAME_LIST"}
    cfg = CFG_RE.search(raw_text)
    if cfg:
        facts["cfg"] = cfg.group(1)
    facts["name_rows"] = sum(1 for l in validate_lines(raw_text) if NAME_ROW_RE.match(l))
    facts["identifier_rows"] = sum(
        1 for l in validate_lines(raw_text) if IDENTIFIER_ROW_RE.match(l)
    )
    delta = {op: 0 for op in ("ADD", "DEL", "CHG")}
    current = None
    for line in validate_lines(raw_text):
        marker = OP_MARKER_RE.match(line.strip())
        if marker:
            current = marker.group(1)
            continue
        if NAME_ROW_RE.match(line) and current:
            delta[current] += 1
    if any(delta.values()):
        facts["changes"] = {op: n for op, n in delta.items() if n}
    return facts


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
    "LDM": lambda t: (extract_load(t), []),
    "PTM": lambda t: extract_transfer(t),
    "PSM": lambda t: (extract_assistance(t), []),
    "PAL": lambda t: (extract_assistance(t), []),
    "CAL": lambda t: (extract_assistance(t), []),
    "PNL": lambda t: (extract_name_list(t), []),
    "ADL": lambda t: (extract_name_list(t), []),
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

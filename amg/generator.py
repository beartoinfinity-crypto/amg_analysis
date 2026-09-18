import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path


HEADER_RE = re.compile(
    r"^(?:(?:PNL|ADL|MVT|MVA|LDM|FWD|ASM)\s*)?"
    r"(?P<flight>[A-Z0-9]{2,3}\d{1,4}[A-Z]?)/"
    r"(?P<date>\d{1,2}(?:[A-Z]{3}(?:\d{2})?)?)(?=[.\s]|$)",
    re.MULTILINE,
)
DEST_RE = re.compile(r"^-(?P<airport>[A-Z]{3})(?=[.\d])", re.MULTILINE)
PNL_BLOCK_RE = re.compile(r"^-[A-Z]{3}(?P<pax>\d{1,3})[A-Z](?:-PAD(?P<pad>\d{1,3}))?$", re.MULTILINE)
LDM_PAX_RE = re.compile(r"^-[A-Z]{3}\.(?P<adults>\d+)/(?P<children>\d+)/(?P<infants>\d+)(?=[./]|$)", re.MULTILINE)
PAX_RE = re.compile(r"(?<![A-Z])(?:PAX|PX|POB)(?P<pax>\d+)(?!\d)")
AIRPORT_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{3})(?![A-Z0-9])")
MONTHS = ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')
SUPPORTED = {'PNL', 'ADL', 'MVT', 'MVA', 'LDM', 'FWD', 'ASM'}
MESSAGE_TYPES = SUPPORTED | {'PTM', 'PSM', 'PAL', 'CAL', 'DIV'}


@dataclass(frozen=True)
class Field:
    label: str
    kind: str
    start: int
    end: int
    value: str


def default_template_path():
    return Path(__file__).with_name('message_templates.json')


def read_template_library(path):
    with Path(path).open(encoding='utf-8') as source:
        library = json.load(source)
    if not isinstance(library, dict) or library.get('version') != 1:
        raise ValueError('Template library must have version 1.')
    rows = library.get('templates')
    if not isinstance(rows, list):
        raise ValueError('Template library must contain a templates list.')
    ids = set()
    required = ('msg_type', 'flight_number', 'flight_date', 'flight_airport', 'text')
    for row in rows:
        if not isinstance(row, dict) or type(row.get('id')) is not int:
            raise ValueError('Each template needs an integer id.')
        if row['id'] in ids:
            raise ValueError('Template IDs must be unique.')
        ids.add(row['id'])
        if any(not isinstance(row.get(key), str) or not row[key].strip() for key in required):
            raise ValueError('Template metadata and text must be non-empty strings.')
        if not re.fullmatch(r'\d{8}', row['flight_date']):
            raise ValueError('Template flight_date must be YYYYMMDD.')
        date.fromisoformat(row['flight_date'])
        if 'part_number' in row and row['part_number'] is not None and type(row['part_number']) is not int:
            raise ValueError('Template part_number must be an integer or null.')
    return rows


def connect_database(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=3)


def message_types(path):
    if Path(path).suffix.lower() == '.json':
        return sorted({row['msg_type'] for row in read_template_library(path)})
    con = connect_database(path)
    try:
        return [row[0] for row in con.execute(
            'SELECT DISTINCT msg_type FROM messages ORDER BY msg_type'
        )]
    finally:
        con.close()


def templates(path, msg_type, flight='', scheduled_date='', limit=100):
    if Path(path).suffix.lower() == '.json':
        scheduled = date.fromisoformat(scheduled_date.strip()).strftime('%Y%m%d') if scheduled_date.strip() else ''
        rows = read_template_library(path)
        return [
            (row['id'], row['flight_number'], row['flight_date'], row['flight_airport'],
             row.get('name', 'Synthetic template'), row.get('part_number'))
            for row in rows
            if row['msg_type'] == msg_type
            and (not flight.strip() or row['flight_number'] == flight.strip().upper())
            and (not scheduled or row['flight_date'] == scheduled)
        ][:limit]
    where = ['msg_type = ?']
    params = [msg_type]
    if flight.strip():
        where.append('flight_number = ?')
        params.append(flight.strip().upper())
    if scheduled_date.strip():
        where.append('flight_date = ?')
        params.append(date.fromisoformat(scheduled_date.strip()).strftime('%Y%m%d'))
    con = connect_database(path)
    try:
        return con.execute(
            'SELECT id, flight_number, flight_date, flight_airport, received_at, part_number '
            'FROM messages WHERE ' + ' AND '.join(where)
            + ' ORDER BY received_at DESC, id DESC LIMIT ?', params + [limit]
        ).fetchall()
    finally:
        con.close()


def load_template(path, message_id, plain=False):
    if Path(path).suffix.lower() == '.json':
        row = next((row for row in read_template_library(path) if row['id'] == message_id), None)
        if row is None:
            raise ValueError('Template no longer exists.')
        return row['msg_type'], row['text']
    column = 'raw_text_plain' if plain else 'raw_text'
    con = connect_database(path)
    try:
        row = con.execute(
            f'SELECT msg_type, {column} FROM messages WHERE id = ?', (message_id,)
        ).fetchone()
        if row is None:
            raise ValueError('Template no longer exists.')
        if not row[1]:
            raise ValueError('This message has no stored text in the selected mode.')
        return row[0], row[1]
    finally:
        con.close()


def normalize_text(text):
    text = text.replace('\r\r\n', '\n').replace('\r\n', '\n').replace('\r', '\n')
    return text.replace('\x01', '').replace('\x02', '').replace('\x03', '')


def editable_fields(text, msg_type):
    if msg_type not in SUPPORTED:
        return []
    fields = []

    def add(match, group, kind, label):
        if match.group(group) is not None:
            start, end = match.span(group)
            fields.append(Field(label, kind, start, end, text[start:end]))

    header = HEADER_RE.search(text)
    if header:
        add(header, 'flight', 'flight', 'Flight ID')
        add(header, 'date', 'date', 'Scheduled date (YYYY-MM-DD)')
        end = text.find('\n', header.end())
        end = len(text) if end < 0 else end
        for match in AIRPORT_RE.finditer(text, header.end(), end):
            add(match, 1, 'airport', 'Header airport')
    for i, match in enumerate(DEST_RE.finditer(text), 1):
        add(match, 'airport', 'airport', f'Destination block {i}')
    if msg_type in {'PNL', 'ADL'}:
        for i, match in enumerate(PNL_BLOCK_RE.finditer(text), 1):
            add(match, 'pax', 'count3', f'Block {i} declared pax')
            add(match, 'pad', 'count3', f'Block {i} PAD')
    if msg_type == 'LDM':
        for i, match in enumerate(LDM_PAX_RE.finditer(text), 1):
            for group in ('adults', 'children', 'infants'):
                add(match, group, 'count', f'Block {i} {group}')
    if msg_type in {'MVT', 'MVA'}:
        for i, match in enumerate(PAX_RE.finditer(text), 1):
            add(match, 'pax', 'count', f'Pax field {i}')
        for match in re.finditer(r'\b(?:EA|ED|AA|AD|TD|EO)\d{4}(?:/\d{4})?\s+([A-Z]{3})\b', text):
            add(match, 1, 'airport', 'Movement airport')
    return sorted(fields, key=lambda field: field.start)


def field_value(field, value):
    value = value.strip().upper()
    if field.kind == 'date':
        day = date.fromisoformat(value)
        if len(field.value) <= 2:
            return f'{day.day:02}'
        result = f'{day.day:02}{MONTHS[day.month - 1]}'
        return result + (f'{day.year % 100:02}' if len(field.value) > 5 else '')
    if field.kind == 'flight' and not re.fullmatch(r'[A-Z0-9]{2,3}\d{1,4}[A-Z]?', value):
        raise ValueError('Flight ID must contain a carrier and flight digits, e.g. CX841 or 3U3959.')
    if field.kind == 'airport' and not re.fullmatch(r'[A-Z]{3}', value):
        raise ValueError('Airport must be three letters.')
    if field.kind in {'count', 'count3'}:
        maximum = 999 if field.kind == 'count3' else 9999
        if not value.isascii() or not value.isdigit() or int(value) > maximum:
            raise ValueError(f'Count must be 0–{maximum}.')
        return value.zfill(len(field.value))
    return value


def apply_fields(text, fields, values):
    if len(fields) != len(values):
        raise ValueError('Field values do not match the template.')
    patches = []
    for field, value in zip(fields, values):
        if not value.strip() or value == field.value:
            continue
        patches.append((field.start, field.end, field_value(field, value)))
    for start, end, value in sorted(patches, reverse=True):
        text = text[:start] + value + text[end:]
    return text


def review_warnings(text, msg_type):
    warnings = ['Historical text may contain personal or operational data. Review before sharing.']
    if not HEADER_RE.search(text):
        warnings.append('No supported flight header found; edit this format manually.')
    if msg_type in {'PNL', 'ADL'}:
        warnings.append('Declared counts do not regenerate passenger names. Review name rows, PAD and totals.')
        if re.search(r'\bPART\d*\b', text) and not re.search(r'\bENDPNL\b|\bENDADL\b', text):
            warnings.append('This is a historical part, not an assembled transmission. Review all related parts.')
    if msg_type == 'LDM':
        warnings.append('Changing a pax field does not recalculate cabin totals, weights or SI details.')
    header = HEADER_RE.search(text)
    if header and len(header.group('date')) <= 2:
        warnings.append('This header stores only the scheduled day; month/year must come from test context.')
    warnings.append('Direction is test-case metadata; verify the route and scheduled date in the body.')
    return warnings


def save_message(path, text, framed=False):
    body = normalize_text(text).strip('\n')
    if not body.strip():
        raise ValueError('Message is empty.')
    if framed:
        lines = body.split('\n')
        index = next((i for i, line in enumerate(lines) if line.strip() in MESSAGE_TYPES), None)
        if index is None:
            raise ValueError('Framed export needs a standalone message-type line. Use plain export for this template.')
        lines[index] = '\x02' + lines[index]
        body = '\x01' + '\n'.join(lines) + '\n\x03'
    payload = (body.replace('\n', '\r\n') + '\r\n').encode('latin-1')
    Path(path).write_bytes(payload)

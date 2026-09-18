import json
import sqlite3
import time
import tkinter as tk

import pytest

from amg import generator
from amg.gen_gui import MessageGenerator


PNL = 'QD HKGTSXH\n.TESTAAA 221053\nPNL\nCX841/23AUG JFK PART1\n-HKG010Y-PAD000\n-SYD020J\nENDPNL\n'


def make_database(tmp_path):
    path = tmp_path / 'templates.db'
    con = sqlite3.connect(path)
    con.execute(
        'CREATE TABLE messages (id INTEGER PRIMARY KEY, msg_type TEXT, '
        'flight_number TEXT, flight_date TEXT, flight_airport TEXT, received_at TEXT, '
        'part_number INTEGER, raw_text TEXT, raw_text_plain TEXT)'
    )
    con.execute('INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (1, 'PNL', 'CX841', '20260823', 'JFK', '2026-08-22T22:30:00', 1, PNL, PNL + 'TEST ONLY\n'))
    con.commit()
    con.close()
    return path


def test_database_search_and_load_are_read_only(tmp_path):
    path = make_database(tmp_path)
    before = path.read_bytes()
    assert generator.message_types(path) == ['PNL']
    assert len(generator.templates(path, 'PNL', 'cx841', '2026-08-23')) == 1
    assert generator.templates(path, 'PNL', 'CX841', '2026-08-24') == []
    assert generator.load_template(path, 1) == ('PNL', PNL)
    assert generator.load_template(path, 1, plain=True)[1].endswith('TEST ONLY\n')
    con = generator.connect_database(path)
    with pytest.raises(sqlite3.OperationalError):
        con.execute('DELETE FROM messages')
    con.close()
    assert path.read_bytes() == before
    with pytest.raises(sqlite3.OperationalError):
        generator.templates(tmp_path / 'missing.db', 'PNL')
    assert not (tmp_path / 'missing.db').exists()


def test_bundled_library_filters_and_exports_every_type(tmp_path):
    library = generator.default_template_path()
    rows = generator.read_template_library(library)
    assert len(rows) == 17
    assert len(generator.message_types(library)) == 12
    assert len(generator.templates(library, 'PNL', 'ZZ102', '2026-09-17')) == 2
    assert generator.templates(library, 'PNL', '', '2026-09-18') == []
    for row in rows:
        msg_type, text = generator.load_template(library, row['id'])
        assert msg_type == row['msg_type']
        assert generator.load_template(library, row['id'], plain=True)[1] == text
        generator.save_message(tmp_path / f"{row['id']}.rcv", text, framed=True)
    with pytest.raises(ValueError):
        generator.load_template(library, -1)


@pytest.mark.parametrize('payload', [
    {}, {'version': 2, 'templates': []}, {'version': 1, 'templates': [{}]},
    {'version': 1, 'templates': [{'id': '1'}]},
])
def test_invalid_json_library_is_rejected(tmp_path, payload):
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValueError):
        generator.read_template_library(path)


def test_structured_pnl_edits_are_local_not_global():
    text = PNL + 'SI CX841 23AUG JFK HKG010Y\n'
    fields = generator.editable_fields(text, 'PNL')
    values = [{'Flight ID': '3U3959', 'Scheduled date (YYYY-MM-DD)': '2027-01-03',
               'Header airport': 'LHR', 'Destination block 1': 'BKK',
               'Block 1 declared pax': '25'}.get(field.label, '') for field in fields]
    result = generator.apply_fields(text, fields, values)
    assert '3U3959/03JAN LHR PART1' in result
    assert '-BKK025Y-PAD000' in result
    assert '-SYD020J' in result
    assert 'SI CX841 23AUG JFK HKG010Y' in result
    assert generator.apply_fields(text, fields, [''] * len(fields)) == text


@pytest.mark.parametrize('old,new', [('04', '09'), ('04SEP', '09FEB'), ('04SEP26', '09FEB28')])
def test_date_preserves_header_format_and_uses_new_year(old, new):
    text = f'LDM\n3U3959/{old}.B8500.C8Y156.03/06\n-HKG.85/1/0.0.T634\n'
    fields = generator.editable_fields(text, 'LDM')
    values = ['2028-02-09' if field.kind == 'date' else '' for field in fields]
    assert f'3U3959/{new}.' in generator.apply_fields(text, fields, values)


@pytest.mark.parametrize('kind,old,value', [
    ('date', '04SEP26', '2026-02-30'), ('flight', 'CX841', 'BAD\nPNL'),
    ('airport', 'HKG', 'HKG1'), ('count3', '010', '1000'), ('count', '1', '-1'),
])
def test_invalid_fields_are_rejected(kind, old, value):
    with pytest.raises(ValueError):
        generator.field_value(generator.Field('test', kind, 0, len(old), old), value)


def test_ldm_and_movement_count_fields():
    ldm = 'LDM\n3U3959/04SEP26.B8500.C8Y156.03/06\n-HKG.85/1/0.0.T634\n'
    fields = generator.editable_fields(ldm, 'LDM')
    result = generator.apply_fields(ldm, fields, ['90' if f.label == 'Block 1 adults' else '' for f in fields])
    assert '-HKG.90/1/0.0.T634' in result
    mvt = 'MVT\nCX841/04.BTEST.JFK\nEA1234 HKG PX85\n'
    fields = generator.editable_fields(mvt, 'MVT')
    assert any(f.value == 'HKG' and f.kind == 'airport' for f in fields)
    result = generator.apply_fields(mvt, fields, ['86' if f.kind == 'count' else '' for f in fields])
    assert 'PX86' in result
    assert generator.editable_fields('UNKNOWN\nCX841', 'UNKNOWN') == []


def test_export_newlines_framing_and_failures(tmp_path):
    path = tmp_path / 'test.rcv'
    generator.save_message(path, PNL, framed=True)
    payload = path.read_bytes()
    assert payload.startswith(b'\x01QD HKGTSXH\r\n')
    assert b'\x02PNL\r\n' in payload
    assert payload.endswith(b'ENDPNL\r\n\x03\r\n')
    assert b'\n' not in payload.replace(b'\r\n', b'')
    generator.save_message(path, PNL)
    assert b'\x01' not in path.read_bytes()
    before = path.read_bytes()
    with pytest.raises(UnicodeEncodeError):
        generator.save_message(path, 'TEST\n\u4e00')
    assert path.read_bytes() == before
    with pytest.raises(ValueError):
        generator.save_message(path, 'UNKNOWN\nTEST', framed=True)
    assert generator.normalize_text('\x01PNL\r\r\nTEST\r\n\x03') == 'PNL\nTEST\n'


@pytest.mark.parametrize('bundled', [False, True])
def test_gui_load_apply_and_manual_preview(tmp_path, monkeypatch, bundled):
    path = generator.default_template_path() if bundled else make_database(tmp_path)
    expected = generator.load_template(path, 1)[1]
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip('Tk display unavailable')
    root.withdraw()
    errors = []
    monkeypatch.setattr('amg.gen_gui.messagebox.showerror', lambda *args: errors.append(args))
    monkeypatch.setattr('amg.gen_gui.messagebox.askyesno', lambda *args: True)
    app = MessageGenerator(root, path)
    try:
        deadline = time.monotonic() + 5
        while app.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert not app.busy
        children = app.tree.get_children()
        assert '1' in children
        app.tree.selection_set('1')
        app.on_select()
        assert app.preview.get('1.0', 'end-1c') == expected
        assert app.plain_checkbox.instate(['disabled']) == bundled
        index = next(i for i, field in enumerate(app.fields) if field.kind == 'flight')
        app.entries[index].insert(0, 'CX999')
        app.update_preview()
        expected_date = '17SEP' if bundled else '23AUG'
        assert f'CX999/{expected_date}' in app.preview.get('1.0', 'end-1c')
        app.entries[index].delete(0, 'end')
        app.entries[index].insert(0, 'INVALID')
        before = app.preview.get('1.0', 'end-1c')
        app.update_preview()
        assert errors
        assert app.preview.get('1.0', 'end-1c') == before
        app.preview.insert('end', 'SI TEST ONLY\n')
        export = tmp_path / 'gui-test.txt'
        monkeypatch.setattr('amg.gen_gui.filedialog.asksaveasfilename', lambda **kwargs: str(export))
        app.save_message(False)
        assert b'SI TEST ONLY\r\n' in export.read_bytes()
        app.search_templates()
        assert app.preview.get('1.0', 'end-1c') == ''
    finally:
        app.close()

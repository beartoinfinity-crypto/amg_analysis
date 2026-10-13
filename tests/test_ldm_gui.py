import tkinter as tk

import pytest

from amg.ldm_gui import MessageExtractor

LDM_BODY = (
    "\r\n\x01QD HKGTSXH\r\n"
    ".SELWB7C 052051\r\n"
    "\x02LDM\r\n"
    "7C6013/05.HL8594.Y189.2/4\r\n"
    "-HKG.147/2/0.T4399.1/541.2/1191.3/2667.PAX/149.PAD/0\r\n"
    "-SFO.10/2/0/0.T1000.PAX/0/12\r\n"
    "\x03\r\n"
)

MVT_BODY = (
    "\r\n\x01QU HKGTSXH\r\n"
    ".TYOXKJL 070132\r\n"
    "\x02MVT\r\n"
    "JL0029/07.JA872J.HND\r\n"
    "AD1654/1712 EA1834 HKG\r\n"
    "TD1708 AA1721/1734\r\n"
    "DL81/0015 DL34/0020 RA/0120\r\n"
    "PX142\r\n"
    "\x03\r\n"
)


@pytest.fixture
def app():
    root = tk.Tk()
    root.withdraw()
    gui = MessageExtractor(root)
    yield gui
    root.destroy()


def test_ldm_tab_extracts_pax_totals(app):
    app.ldm_tab.input_text.insert('1.0', LDM_BODY)
    app.ldm_tab.extract()
    output = app.ldm_tab.results.get('1.0', 'end-1c')
    assert 'PX7 (local): 149' in output
    assert 'PX6 (transit): 12' in output
    assert 'PAX (total): 161' in output
    assert 'dest=HKG' in output
    assert 'dest=SFO' in output


def test_ldm_tab_shows_reg_and_crew(app):
    app.ldm_tab.input_text.insert('1.0', LDM_BODY)
    app.ldm_tab.extract()
    output = app.ldm_tab.results.get('1.0', 'end-1c')
    assert 'REG: HL8594' in output
    assert 'cockpit=2' in output


def test_mvt_tab_extracts_times_and_pax(app):
    app.mvt_tab.input_text.insert('1.0', MVT_BODY)
    app.mvt_tab.extract()
    output = app.mvt_tab.results.get('1.0', 'end-1c')
    assert 'AD (actual off-blocks): 1654' in output
    assert 'EO (estimated airborne): 1712' in output
    assert 'EL (estimated landing): 1834' in output
    assert 'TD (actual touchdown): 1708' in output
    assert 'AA (actual on-blocks): 1734' in output
    assert 'Destination: HKG' in output
    assert 'total=142' in output


def test_mvt_tab_extracts_delay_slots(app):
    app.mvt_tab.input_text.insert('1.0', MVT_BODY)
    app.mvt_tab.extract()
    output = app.mvt_tab.results.get('1.0', 'end-1c')
    assert 'IR1: 81' in output
    assert 'DL1: 0015' in output
    assert 'IR2: 34' in output
    assert 'DL2: 0020' in output


def test_clear_all_resets_active_tab(app):
    app.ldm_tab.input_text.insert('1.0', LDM_BODY)
    app.ldm_tab.extract()
    app.ldm_tab.clear_all()
    assert app.ldm_tab.input_text.get('1.0', 'end-1c').strip() == ''
    assert app.ldm_tab.results.get('1.0', 'end-1c').strip() == ''


def test_both_tabs_exist(app):
    assert app.ldm_tab is not None
    assert app.mvt_tab is not None

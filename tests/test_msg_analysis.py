import tkinter as tk

import pytest

from amg.msg_analysis import MessageAnalyzer

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

FWD_BODY = (
    "\r\n\x01QU HKGTSXH\r\n"
    "\x02FWD\r\n"
    "BA123/27.HKG.4/4/8\r\n"
    "-ATL.B88.R42.A15.L6.T4368.GBR/150.CHN/23\r\n"
    ".P\r\n"
    "DL254 SFO 1F 1B22K\r\n"
    "ENDFWD\r\n"
    "\x03\r\n"
)

DIV_BODY = (
    "\r\n\x01QU HKGTSXH\r\n"
    "\x02DIV\r\n"
    "GF165/17.AB1234.HKG\r\n"
    "EA1210 PVG\r\n"
    "PX145\r\n"
    "SI PAX MEDICAL ATTN REQD\r\n"
    "EOT\r\n"
    "\x03\r\n"
)

PTM_BODY = (
    "\r\n\x01QU HKGTSXH\r\n"
    "\x02PTM\r\n"
    "GF165/17JUN BAHHKG PART1\r\n"
    "GF167/18 MAN 1J 2B30K POKHREL/ARYADEV.CHD1\r\n"
    "GF167/18 LHR 1J 2B35K POKHREL/NETRAPRASAD\r\n"
    "ENDPTM\r\n"
    "\x03\r\n"
)

PSM_BODY = (
    "\r\n\x01QU HKGTSXH\r\n"
    "\x02PSM\r\n"
    "AF556/27NOV ORY PART1\r\n"
    "-HKG 1PAX/1SSR\r\n"
    "1MILLER/JACKMR 12D WCHR NEEDS WHEELCHAIR AT GATE\r\n"
    "ENDPSM\r\n"
    "\x03\r\n"
)

CAL_BODY = (
    "\r\n\x01QU HKGTSXH\r\n"
    "\x02CAL\r\n"
    "UW234/12NOV BRU PART1\r\n"
    "-HKG ADD\r\n"
    "1BROWN/WILLIAMMR .R/WCHS NEEDS ASSISTANCE FOR STAIRS\r\n"
    "-HKG DEL\r\n"
    "1ZIMMER/EMMAMRS .R/DPNA\r\n"
    "ENDCAL\r\n"
    "\x03\r\n"
)

ASM_BODY = (
    "\r\n\x01QU HKGTSXH\r\n"
    "\x02ASM\r\n"
    "NEW\r\n"
    "BA123/27.HKG.LHR\r\n"
    "\x03\r\n"
)


@pytest.fixture
def app():
    root = tk.Tk()
    root.withdraw()
    gui = MessageAnalyzer(root)
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
    assert 'AB (actual airborne): 1712' in output
    assert 'EL (estimated landing): 1834' in output
    assert 'TD (actual touchdown): 1708' in output
    assert 'AA (actual on-blocks): 1721' in output
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


def test_fwd_tab_extracts_destinations_and_nationalities(app):
    app.fwd_tab.input_text.insert('1.0', FWD_BODY)
    app.fwd_tab.extract()
    output = app.fwd_tab.results.get('1.0', 'end-1c')
    assert 'Final destination: ATL' in output
    assert 'Hops: 1' in output
    assert 'B=88' in output
    assert 'R=42' in output
    assert 'A=15' in output
    assert 'L=6' in output
    assert 'T=4368' in output
    assert 'GBR=150' in output
    assert 'CHN=23' in output


def test_fwd_tab_extracts_transfer_rows(app):
    app.fwd_tab.input_text.insert('1.0', FWD_BODY)
    app.fwd_tab.extract()
    output = app.fwd_tab.results.get('1.0', 'end-1c')
    assert 'Transfer rows: 1' in output
    assert 'flight=DL254' in output
    assert 'dest=SFO' in output


def test_div_tab_extracts_diversion_fields(app):
    app.div_tab.input_text.insert('1.0', DIV_BODY)
    app.div_tab.extract()
    output = app.div_tab.results.get('1.0', 'end-1c')
    assert 'PX (passengers on board): 145' in output
    assert 'EA (estimated arrival): 1210' in output
    assert 'DVA (diverted airport): PVG' in output


def test_div_tab_detects_can_flag(app):
    body = "\x02DIV\r\nGF165/17.AB1234.HKG\r\nCAN\r\nEA1210 PVG\r\nPX145\r\n\x03\r\n"
    app.div_tab.input_text.insert('1.0', body)
    app.div_tab.extract()
    output = app.div_tab.results.get('1.0', 'end-1c')
    assert 'CAN (cancelled/diverted): yes' in output


def test_ptm_tab_extracts_transfer_totals(app):
    app.ptm_tab.input_text.insert('1.0', PTM_BODY)
    app.ptm_tab.extract()
    output = app.ptm_tab.results.get('1.0', 'end-1c')
    assert 'PX5 (total transfers): 2' in output
    assert 'BG2 (total bags): 4' in output
    assert 'Rows: 2' in output


def test_ptm_tab_extracts_transfer_rows(app):
    app.ptm_tab.input_text.insert('1.0', PTM_BODY)
    app.ptm_tab.extract()
    output = app.ptm_tab.results.get('1.0', 'end-1c')
    assert 'flight=GF167' in output
    assert 'dest=MAN' in output
    assert 'detail=1J 2B30K' in output


def test_psm_tab_extracts_assist_codes(app):
    app.assist_tab.input_text.insert('1.0', PSM_BODY)
    app.assist_tab.extract()
    output = app.assist_tab.results.get('1.0', 'end-1c')
    assert 'WCHR' in output
    assert 'PXR (PRM pax total): 1' in output


def test_cal_tab_extracts_delta_counts(app):
    app.assist_tab.input_text.insert('1.0', CAL_BODY)
    app.assist_tab.extract()
    output = app.assist_tab.results.get('1.0', 'end-1c')
    assert 'ADD=1' in output
    assert 'DEL=1' in output
    assert 'WCHS' in output
    assert 'DPNA' in output


def test_asm_tab_shows_muted_note(app):
    app.asm_tab.input_text.insert('1.0', ASM_BODY)
    app.asm_tab.extract()
    output = app.asm_tab.results.get('1.0', 'end-1c')
    assert 'muted by default' in output
    assert 'Raw payload' in output
    assert 'BA123/27.HKG.LHR' in output


def test_all_tabs_exist(app):
    assert app.ldm_tab is not None
    assert app.mvt_tab is not None
    assert app.fwd_tab is not None
    assert app.div_tab is not None
    assert app.ptm_tab is not None
    assert app.assist_tab is not None
    assert app.asm_tab is not None

import tkinter as tk

import pytest

from amg.ldm_gui import LDMExtractor

LDM_BODY = (
    "\r\n\x01QD HKGTSXH\r\n"
    ".SELWB7C 052051\r\n"
    "\x02LDM\r\n"
    "7C6013/05.HL8594.Y189.2/4\r\n"
    "-HKG.147/2/0.T4399.1/541.2/1191.3/2667.PAX/149.PAD/0\r\n"
    "-SFO.10/2/0/0.T1000.PAX/0/12\r\n"
    "\x03\r\n"
)


@pytest.fixture
def app():
    root = tk.Tk()
    root.withdraw()
    gui = LDMExtractor(root)
    yield gui
    root.destroy()


def test_extract_ldm_pastes_and_extracts(app):
    app.input_text.insert('1.0', LDM_BODY)
    app.extract()
    output = app.results.get('1.0', 'end-1c')
    assert 'PX7 (local): 149' in output
    assert 'PX6 (transit): 12' in output
    assert 'PAX (total): 161' in output
    assert 'dest=HKG' in output
    assert 'dest=SFO' in output


def test_extract_shows_reg_and_crew(app):
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".SELWB7C 052051\r\n"
        "\x02LDM\r\n"
        "7C6013/05.HL8594.Y189.2/4\r\n"
        "-HKG.147/2/0.T4399.1/541.2/1191.3/2667.PAX/149.PAD/0\r\n"
        "\x03\r\n"
    )
    app.input_text.insert('1.0', body)
    app.extract()
    output = app.results.get('1.0', 'end-1c')
    assert 'REG:        HL8594' in output
    assert 'cockpit=2' in output


def test_clear_all_resets_everything(app):
    app.input_text.insert('1.0', LDM_BODY)
    app.extract()
    app.clear_all()
    assert app.input_text.get('1.0', 'end-1c').strip() == ''
    assert app.results.get('1.0', 'end-1c').strip() == ''


def test_copy_results_puts_output_on_clipboard(app):
    app.input_text.insert('1.0', LDM_BODY)
    app.extract()
    app.copy_results()
    assert app.root.clipboard_get() != ''

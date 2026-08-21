import sqlite3

from amg.cli import main


def ingest_one(tmp_path, make_archive, text):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    make_archive(
        archive_dir / "PROCESSED_20260610_0025.tar.Z",
        {"HKG/260607002540778.rcv": text},
    )
    db = tmp_path / "index.db"
    assert main(["ingest", str(archive_dir), "--db", str(db)]) == 0
    con = sqlite3.connect(db)
    return con.execute(
        "SELECT msg_type, priority, destination, origin, flight_number, aircraft_reg"
        " FROM messages"
    ).fetchone()


def test_movement_message_parses_envelope_and_flight(tmp_path, make_archive):
    row = ingest_one(
        tmp_path,
        make_archive,
        "QD HKGTSXH\n"
        ".HKGODCI 061625/AMAMQ\n"
        "MVT\n"
        "CI5825/06.B18778.HKG\n"
        "AA1612/1624\n"
        "SI\n"
        "FR 50500\n",
    )
    assert row == ("MVT", "QD", "HKGTSXH", "HKGODCI", "CI5825", "B18778")


def test_baggage_message_parses_type_without_flight(tmp_path, make_archive):
    row = ingest_one(
        tmp_path,
        make_archive,
        "QU HKGTSXH\n"
        ".ISTKMTK 081625 BMD-094-081625\n"
        "BSM\n"
        ".V/1XHKG\n"
        ".P/FRYDA/PATRYKDAWID\n"
        "ENDBSM\n",
    )
    assert row == ("BSM", "QU", "HKGTSXH", "ISTKMTK", None, None)


def test_movement_with_distribution_list_finds_origin(tmp_path, make_archive):
    row = ingest_one(
        tmp_path,
        make_archive,
        "QU HKGTSXH\n"
        ".     \n"
        "QU HKGAE8X HKGAF8X HKGAI8X\n"
        ".TYOFSNH 061627 Z\n"
        "MVA\n"
        "NH814/06.JA808A.HKG\n",
    )
    assert row == ("MVA", "QU", "HKGTSXH", "TYOFSNH", "NH814", "JA808A")


def test_unrecognised_body_typed_other_without_fields(tmp_path, make_archive):
    row = ingest_one(tmp_path, make_archive, "hello world\nno envelope here\n")
    assert row == ("OTHER", None, None, None, None, None)


def test_real_type_b_control_character_framing_parses(tmp_path, make_archive):
    row = ingest_one(
        tmp_path,
        make_archive,
        "\r\n\x01QU HKGTSXH\r\n"
        ".TYOXKJL 070132\r\n"
        "\x02MVT\r\n"
        "JL0029/07.JA872J.HND\r\n"
        "AD070110/070132 EA070527 HKG\r\n"
        "DL81/0015\r\n"
        "PX191\r\n"
        "TOF104922\r\n"
        "SI CONFE91/CC3/CA9/DH1\r\n"
        "\x03\r\n",
    )
    assert row == ("MVT", "QU", "HKGTSXH", "TYOXKJL", "JL0029", "JA872J")


def test_ldm_inline_flight_on_keyword_line_parses(tmp_path, make_archive):
    row = ingest_one(
        tmp_path,
        make_archive,
        "\r\n\x01QU HKGTSXH\r\n"
        ".TYOOZNH 070132\r\n"
        "\x02LDM NH0813/08.JA838A.42/198.2/8\r\n"
        "SI\r\n"
        "BW 141087 BI 39.5\r\n"
        "\x03\r\n",
    )
    assert row == ("LDM", "QU", "HKGTSXH", "TYOOZNH", "NH0813", "JA838A")


def test_unknown_three_letter_keyword_is_typed_with_flight(tmp_path, make_archive):
    row = ingest_one(
        tmp_path,
        make_archive,
        "\r\n\x01QU HKGTSXH\r\n"
        ".HKGNHQS 080015\r\n"
        "\x02ADL\r\n"
        "NH0814/08.JA839A.42/C\r\n"
        "\x03\r\n",
    )
    assert row == ("ADL", "QU", "HKGTSXH", "HKGNHQS", "NH0814", "JA839A")


def test_soh_address_continuation_lines_still_find_origin(tmp_path, make_archive):
    row = ingest_one(
        tmp_path,
        make_archive,
        "\r\n\x01QN HKGTSXH\r\n"
        ".     \r\n"
        "\x01QN BKKDBXH FRASACR HKGAMXH\r\n"
        "HKGKIKA HKGKRCX\r\n"
        ".HDQOPTG 070133/JUN26\r\n"
        "\x02MVT\r\n"
        "TG600/07.HSTKY.BKK\r\n",
    )
    assert row == ("MVT", "QN", "HKGTSXH", "HDQOPTG", "TG600", "HSTKY")

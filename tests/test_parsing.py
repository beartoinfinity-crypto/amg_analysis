import sqlite3

from amg.cli import main


def ingest_one(tmp_path, make_archive, text, archive_name="PROCESSED_20260610_0025.tar.Z"):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    make_archive(
        archive_dir / archive_name,
        {"HKG/260607002540778.rcv": text},
    )
    db = tmp_path / "index.db"
    assert main(["ingest", str(archive_dir), "--db", str(db)]) == 0
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return dict(
        con.execute(
            "SELECT msg_type, priority, destination, origin, flight_number,"
            " aircraft_reg, flight_airport, flight_date, part_number FROM messages"
        ).fetchone()
    )


def envelope(
    msg_type,
    priority=None,
    destination=None,
    origin=None,
    flight_number=None,
    aircraft_reg=None,
    flight_airport=None,
    flight_date=None,
    part_number=None,
):
    return {
        "msg_type": msg_type,
        "priority": priority,
        "destination": destination,
        "origin": origin,
        "flight_number": flight_number,
        "aircraft_reg": aircraft_reg,
        "flight_airport": flight_airport,
        "flight_date": flight_date,
        "part_number": part_number,
    }


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
    assert row == envelope("MVT", "QD", "HKGTSXH", "HKGODCI", "CI5825", "B18778", "HKG")


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
    assert row == envelope("BSM", "QU", "HKGTSXH", "ISTKMTK")


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
    assert row == envelope("MVA", "QU", "HKGTSXH", "TYOFSNH", "NH814", "JA808A", "HKG")


def test_unrecognised_body_typed_other_without_fields(tmp_path, make_archive):
    row = ingest_one(tmp_path, make_archive, "hello world\nno envelope here\n")
    assert row == envelope("OTHER")


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
    assert row == envelope("MVT", "QU", "HKGTSXH", "TYOXKJL", "JL0029", "JA872J", "HND")


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
    assert row == envelope("MVT", "QN", "HKGTSXH", "HDQOPTG", "TG600", "HSTKY", "BKK")


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
    assert row == envelope("LDM", "QU", "HKGTSXH", "TYOOZNH", "NH0813", "JA838A")


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
    assert row == envelope("ADL", "QU", "HKGTSXH", "HKGNHQS", "NH0814", "JA839A")


def test_pnl_info_line_parses_flight_date_airport_and_part(tmp_path, make_archive):
    row = ingest_one(
        tmp_path,
        make_archive,
        "\r\n\x01QU HKGTSXH\r\n"
        ".HKGUKBA 130825\r\n"
        "\x02PNL\r\n"
        "LJ805/13MAY MAN PART1\r\n"
        "\x03\r\n",
    )
    assert row == envelope(
        "PNL", "QU", "HKGTSXH", "HKGUKBA", "LJ805",
        flight_airport="MAN", flight_date="20260513", part_number=1,
    )


def test_pnl_without_part_still_parses_date_and_airport(tmp_path, make_archive):
    row = ingest_one(
        tmp_path,
        make_archive,
        "\r\n\x01QU HKGTSXH\r\n"
        ".HKGUKBA 130825\r\n"
        "\x02PNL\r\n"
        "CX841/08JUN JFK\r\n"
        "\x03\r\n",
    )
    assert row == envelope(
        "PNL", "QU", "HKGTSXH", "HKGUKBA", "CX841",
        flight_airport="JFK", flight_date="20260608",
    )


def test_flight_date_year_wraps_to_previous_year(tmp_path, make_archive):
    row = ingest_one(
        tmp_path,
        make_archive,
        "\r\n\x01QU HKGTSXH\r\n"
        ".HKGUKBA 020015\r\n"
        "\x02PNL\r\n"
        "LJ805/28DEC MAN\r\n"
        "\x03\r\n",
        archive_name="PROCESSED_20260102_0025.tar.Z",
    )
    assert row == envelope(
        "PNL", "QU", "HKGTSXH", "HKGUKBA", "LJ805",
        flight_airport="MAN", flight_date="20251228",
    )


def test_adl_info_line_parses_flight_date_airport_and_part(tmp_path, make_archive):
    row = ingest_one(
        tmp_path,
        make_archive,
        "\r\n\x01QK HKGTSXH\r\n"
        ".MUCPNTG 300306\r\n"
        "\x02ADL\r\n"
        "TG600/02MAY BKK PART1\r\n"
        "ANA/965096\r\n"
        "-HKG031C\r\n"
        "\x03\r\n",
    )
    assert row == envelope(
        "ADL", "QK", "HKGTSXH", "MUCPNTG", "TG600",
        flight_airport="BKK", flight_date="20260502", part_number=1,
    )


def test_ptm_info_line_parses_city_pair_and_part(tmp_path, make_archive):
    row = ingest_one(
        tmp_path,
        make_archive,
        "\r\n\x01QD HKGTSXH\r\n"
        ".PEKKMCA HB/301623\r\n"
        "\x02PTM\r\n"
        "UO251/30APR SYXHKG PART1\r\n"
        "CX566/01 KIX 1K 1B12K MA/LI MS\r\n"
        "\x03\r\n",
    )
    assert row == envelope(
        "PTM", "QD", "HKGTSXH", "PEKKMCA", "UO251",
        flight_airport="SYXHKG", flight_date="20260430", part_number=1,
    )


def test_flight_line_third_dot_segment_stores_airport(tmp_path, make_archive):
    row = ingest_one(
        tmp_path,
        make_archive,
        "\r\n\x01QU HKGTSXH\r\n"
        ".HKGODCI 121625\r\n"
        "\x02MVT\r\n"
        "CI5825/12.B18778.HKG\r\n"
        "\x03\r\n",
    )
    assert row == envelope("MVT", "QU", "HKGTSXH", "HKGODCI", "CI5825", "B18778", "HKG")

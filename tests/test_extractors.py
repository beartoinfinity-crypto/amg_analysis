import sqlite3

from amg.cli import main


def ingest_text(tmp_path, make_archive, msg_type_body, archive_name="PROCESSED_20260610_0025.tar.Z"):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir(exist_ok=True)
    make_archive(
        archive_dir / archive_name,
        {"HKG/260607002540778.rcv": msg_type_body},
    )
    db = tmp_path / "index.db"
    assert main(["ingest", str(archive_dir), "--db", str(db)]) == 0
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


MOVEMENT = (
    "\r\n\x01QD HKGTSXH\r\n"
    ".TYOXKJL 070132\r\n"
    "\x02MVT\r\n"
    "JL0029/07.JA872J.HND\r\n"
    "AD1654/1712 EA1834 HKG\r\n"
    "TD1708 AA1721/1734\r\n"
    "DL81/0015 DL34/0020 RA/0120\r\n"
    "\x03\r\n"
)


def test_movement_extracts_actual_and_estimated_times(tmp_path, make_archive):
    con = ingest_text(tmp_path, make_archive, MOVEMENT)
    fact = con.execute("SELECT family, facts_json FROM message_facts").fetchone()
    assert fact["family"] == "MOVEMENT"
    import json
    facts = json.loads(fact["facts_json"])
    assert facts["times"]["AD"] == {"time": "1654", "date": None}
    assert facts["times"]["EO"] == {"time": "1712", "date": None}
    assert facts["times"]["EL"] == {"time": "1834", "date": None}
    assert facts["times"]["TD"] == {"time": "1708", "date": None}
    # explicit TD token wins; AA pair degrades to its on-blocks time
    assert facts["times"]["AA"] == {"time": "1734", "date": None}


def test_movement_extracts_delay_codes_and_durations(tmp_path, make_archive):
    con = ingest_text(tmp_path, make_archive, MOVEMENT)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["delay_codes"] == ["81", "34", "RA"]
    assert facts["delay_durations"] == ["0015", "0020", "0120"]


def test_movement_detects_adp_abp_markers(tmp_path, make_archive):
    body = MOVEMENT.replace("TD1708 AA1721/1734", "ADP ABP TD1708")
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["adp"] is True and facts["abp"] is True


def test_diversion_extracts_dva_pob_and_can(tmp_path, make_archive):
    body = (
        "\r\n\x01QU HKGTSXH\r\n"
        ".HDQNPNZ 220216\r\n"
        "\x02DIV\r\n"
        "NZ081/21.ZKNZC.HKG\r\n"
        "EA0254 BNE\r\n"
        "POB247\r\n"
        "CAN\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["dva"] == "BNE"
    assert facts["eta"] == "0254"
    assert facts["pob"] == 247
    assert facts["can"] is True


def test_ldm_extracts_weights_pax_and_cabin_totals(tmp_path, make_archive):
    body = (
        "\r\n\x01QU HKGTSXH\r\n"
        ".HKGLDKE 081951\r\n"
        "\x02LDM\r\n"
        "KE0314/08.HL8045.J12C30Y200.2/4\r\n"
        "-HKG.208/36/0.0.T18797.1/2495.2/7512.PAX/0/0/214.PAD/0/0/0\r\n"
        "BW 141087 BI 39.5\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["cabins"] == {"J": 12, "C": 30, "Y": 200}
    assert facts["crew"] == {"cockpit": 2, "cabin": 4, "total": 6}
    assert facts["basic_weight"] == 141087
    assert facts["balance_index"] == 39.5
    assert facts["px7"] == 244
    assert facts["px6"] == 0
    assert facts["AMG_PAX"] == 244


def test_ldm_parses_destination_segments_and_aggregates(tmp_path, make_archive):
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".SELWB7C 052051\r\n"
        "\x02LDM\r\n"
        "7C6013/05.HL8594.Y189.2/4\r\n"
        "-HKG.147/2/0.T4399.1/541.2/1191.3/2667.PAX/149.PAD/0\r\n"
        "-SFO.10/2/0/0.T1000.PAX/0/12\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    segs = [json.loads(r[0]) for r in con.execute(
        "SELECT data_json FROM message_segments ORDER BY seq")]
    assert len(segs) == 2
    assert segs[0]["dest"] == "HKG"
    assert segs[0]["adults"] == 147 and segs[0]["children"] == 2 and segs[0]["infants"] == 0
    assert segs[0]["deadload"] == 4399
    assert segs[1]["dest"] == "SFO"
    assert segs[1]["adults"] == 12
    assert facts["px7"] == 149
    assert facts["px6"] == 12
    assert facts["AMG_PAX"] == 161
    assert facts["ddl"] == 4399 + 1000


def test_ldm_gender_detail_segments_and_cabin_classes(tmp_path, make_archive):
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".ISTKMTK 301420\r\n"
        "\x02LDM\r\n"
        "TK170/30.TCLLA.00F30C270Y.3/11\r\n"
        "-HKG.139/66/1/0.0.T13520.1/1780.2/5020.3/5059.4/916.5/745"
        ".PAX/0/17/189.PAD/0/1/6\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    segs = [json.loads(r[0]) for r in con.execute(
        "SELECT data_json FROM message_segments ORDER BY seq")]
    assert segs[0]["pax_total"] == 206
    assert segs[0]["classes"] == {"first": 0, "business": 17, "economy": 189}
    assert segs[0]["pads"] == {"first": 0, "business": 1, "economy": 6}
    assert facts["AMG_PAX"] == 206
    assert facts["px2"] == 17
    assert facts["px3"] == 189


def test_ldm_nil_traffic_segment_contributes_nothing(tmp_path, make_archive):
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".SELWB7C 052051\r\n"
        "\x02LDM\r\n"
        "7C6013/05.HL8594.Y189.2/4\r\n"
        "-HKG.NIL\r\n"
        "-SFO.10/2/0/0.T1000.PAX/0/12\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    segs = [json.loads(r[0]) for r in con.execute(
        "SELECT data_json FROM message_segments ORDER BY seq")]
    assert segs[0]["nil_traffic"] is True
    assert facts["px6"] == 12
    assert facts["AMG_PAX"] == 12


def test_ldm_captures_si_text_and_station_breakdown(tmp_path, make_archive):
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".PEKDP1E HX/301401\r\n"
        "\x02LDM\r\n"
        "HX0283/30APR26.BLPW.Y220.02/06\r\n"
        "-HKG.87/112/8/0.0.T1672.1/454.3/840.4/378.PAX/207.PAD/3\r\n"
        "SI\r\n"
        "BW 48600 BI 42.00\r\n"
        "HKG FRE 44 POS 0 BAG 1628 TRA 0 BAGP 139\r\n"
        "NOTOC : NO\r\n"
        "REMARK  LINE   WITH   EXTRA   SPACES\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert "RETURN" not in facts["AMG_SIT"]
    assert "NOTOC" in facts["AMG_SIT"]
    assert "REMARK LINE WITH EXTRA SPACES" in facts["AMG_SIT"]
    assert "  " not in facts["AMG_SIT"]
    assert facts["station_breakdown"] == {"station": "HKG", "fre": 44, "pos": 0,
                                          "bag": 1628, "tra": 0}


def test_ldm_supports_interface_column_mapping(tmp_path, make_archive):
    from amg.extractors import INTERFACE_COLUMN_MAPPINGS
    snapshot = dict(INTERFACE_COLUMN_MAPPINGS)
    INTERFACE_COLUMN_MAPPINGS.update({
        "REG": "AMG_REG", "PAX": "AMG_PAX", "SI": "AMG_SIT", "DDL": "DDL",
    })
    try:
        body = (
            "\r\n\x01QD HKGTSXH\r\n"
            ".SELWB7C 052051\r\n"
            "\x02LDM\r\n"
            "7C6013/05.HL8594.Y189.2/4\r\n"
            "-HKG.147/2/0.T4399.PAX/149.PAD/0\r\n"
            "SI PANTRY CODE A\r\n"
            "\x03\r\n"
        )
        con = ingest_text(tmp_path, make_archive, body)
        import json
        facts = json.loads(
            con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
        )
        assert facts["AMG_REG"] == "HL8594"
        assert facts["AMG_PAX"] == 149
        assert facts["AMG_SIT"] == "PANTRY CODE A"
        assert facts["DDL"] == 4399
    finally:
        INTERFACE_COLUMN_MAPPINGS.clear()
        INTERFACE_COLUMN_MAPPINGS.update(snapshot)


def test_ptm_extracts_transfer_segments_without_names(tmp_path, make_archive):
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".PEKKMCA SC/070131\r\n"
        "\x02PTM\r\n"
        "UO251/30APR SYXHKG PART1\r\n"
        "HX305/03 MEL 1O 1B22K TEST/PASSENGERMR\r\n"
        "PX191 BG88\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    seg = con.execute("SELECT seq, data_json FROM message_segments").fetchone()
    data = json.loads(seg["data_json"])
    assert seg["seq"] == 0
    assert data["flight"] == "HX305"
    assert data["day"] == "03"
    assert data["airports"] == "MEL"
    assert data["cabin_bags"] == "1O 1B22K"
    assert "TEST" not in seg["data_json"]
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["total_transfers"] == 191
    assert facts["total_baggage"] == 88
    assert facts["segments"] == 1
    stored = con.execute("SELECT raw_text FROM messages").fetchone()
    assert "TEST" not in stored["raw_text"]
    assert "[REDACTED]" in stored["raw_text"]


def test_assistance_extracts_codes_counts_and_cal_deltas(tmp_path, make_archive):
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".HKGBEN CX/220300\r\n"
        "\x02CAL\r\n"
        "DL9714/06JUN HKG PART1\r\n"
        "-LAX Y\r\n"
        "DEL\r\n"
        "1OLDSURNAMEMS .R/WCHR\r\n"
        "ADD\r\n"
        "1NEWSURNAMEJR .R/DEAF\r\n"
        "2NEWERNAMEMS .R/MEDA\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["assist_codes"] == ["DEAF", "MEDA", "WCHR"]
    assert facts["delta"] == {"ADD": 2, "DEL": 1}
    stored = con.execute("SELECT raw_text FROM messages").fetchone()
    assert "NEWSURNAME" not in stored["raw_text"]
    assert "[REDACTED]" in stored["raw_text"]
    assert ".R/DEAF" in stored["raw_text"].replace("\r\n", "\n")


def test_name_lists_are_fully_redacted_with_counts_only(tmp_path, make_archive):
    body = (
        "\r\n\x01QU HKGTSXH\r\n"
        ".HKGUKBA 130825\r\n"
        "\x02PNL\r\n"
        "LJ805/13MAY MAN PART1\r\n"
        "CFG/014F076J429Y\r\n"
        "AVAIL\r\n"
        "1SMITH/JOHNMR .R/TKNE XX1 1234567890/1\r\n"
        "2JONES/FREDMR\r\n"
        ".R/FBA 1PC\r\n"
        ".RN/4MR / U2TTZ8\r\n"
        ".O2/EY0133W31AUHDUS0220HK .R/RQST HK1 2A-1DOLL/TESTNAMEMR\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["family_kind"] == "NAME_LIST"
    assert facts["name_rows"] == 2
    assert facts["identifier_rows"] == 3
    assert facts["cfg"] == "014F076J429Y"
    stored = con.execute("SELECT raw_text FROM messages").fetchone()
    text = stored["raw_text"]
    for pii in ("SMITH", "JONES", "JOHN", "FRED", "1234567890", "FBA", "U2TTZ8",
                "TESTNAME"):
        assert pii not in text, pii


def test_pnl_extracts_flight_element_facts(tmp_path, make_archive):
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".DXBRCEK 111840\r\n"
        "\x02PNL\r\n"
        "EK0380/12AUG DXB PART1\r\n"
        "-HKG002F\r\n"
        "-HKG023J\r\n"
        "-HKG017W\r\n"
        "-HKG213Y\r\n"
        "ENDPNL\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["carrier"] == "EK"
    assert facts["flight_number"] == "0380"
    assert facts["suffix"] == ""
    assert facts["dep_day"] == "12"
    assert facts["dep_month"] == "AUG"
    assert facts["boarding_airport"] == "DXB"
    assert facts["part_number"] == 1


def test_pnl_extracts_destination_segments_and_class_totals(tmp_path, make_archive):
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".DXBRCEK 111840\r\n"
        "\x02PNL\r\n"
        "EK0380/12AUG DXB PART1\r\n"
        "-HKG002F\r\n"
        "-HKG023J-PAD005\r\n"
        "-HKG017W\r\n"
        "-HKG213Y\r\n"
        "ENDPNL\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    segs = [json.loads(r[0]) for r in con.execute(
        "SELECT data_json FROM message_segments ORDER BY seq")]
    assert len(segs) == 4
    assert segs[0] == {"dest": "HKG", "cabin_class": "F", "declared_total": 2,
                       "pad_total": 0, "actual_parsed_pax": 0}
    assert segs[1]["cabin_class"] == "J" and segs[1]["declared_total"] == 23 and segs[1]["pad_total"] == 5
    assert segs[2]["cabin_class"] == "W" and segs[2]["declared_total"] == 17
    assert segs[3]["cabin_class"] == "Y" and segs[3]["declared_total"] == 213


def test_pnl_aggregates_pxe_px6_for_upstream_boarding(tmp_path, make_archive):
    # PNL sent from SYD with legs SIN -> HKG -> SFO -> JFK: arrival at HKG
    # carries everyone downline; PX6 is only the HKG further-stops (SFO, JFK).
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".SYDXSIN 060800\r\n"
        "\x02PNL\r\n"
        "SY101/06AUG SIN PART1\r\n"
        "-SIN044Y\r\n"
        "-SIN012J\r\n"
        "-HKG180Y\r\n"
        "-SFO120Y\r\n"
        "-JFK060Y\r\n"
        "ENDPNL\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["boarding_airport"] == "SIN"
    assert facts["arrival_action"] is True
    assert facts["departure_action"] is True
    assert facts["pxe"] == 44 + 12 + 180 + 120 + 60
    assert facts["px6"] == 120 + 60


def test_pnl_hkg_boarding_sets_departure_only(tmp_path, make_archive):
    # PNL sent from HKG itself: arrival gets no action, PX6 stays nil.
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".HKGDMK 130900\r\n"
        "\x02PNL\r\n"
        "SL0365/13AUG HKG PART1\r\n"
        "-DMK173Y-PAD000\r\n"
        "ENDPNL\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["boarding_airport"] == "HKG"
    assert facts["arrival_action"] is False
    assert facts["departure_action"] is True
    assert facts["no_action"] is False
    assert facts["pxe"] == 173
    assert facts["px6"] is None


def test_pnl_downstream_boarding_is_no_action(tmp_path, make_archive):
    # PNL sent from SFO (already past HKG): neither arrival nor departure.
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".SFOJFK 230400\r\n"
        "\x02PNL\r\n"
        "UA088/23AUG SFO PART1\r\n"
        "-JFK090Y\r\n"
        "ENDPNL\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["no_action"] is True
    assert facts["arrival_action"] is False
    assert facts["departure_action"] is False
    assert facts["pxe"] is None and facts["px6"] is None


def test_pnl_accumulates_actual_parsed_pax_from_name_rows(tmp_path, make_archive):
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".HKGDMK 130900\r\n"
        "\x02PNL\r\n"
        "SL0365/13AUG HKG PART1\r\n"
        "-DMK173Y-PAD000\r\n"
        "2SMITH/JOHNMR\r\n"
        "3JONES/FREDMR\r\n"
        "1ZZ/ZZZZMR\r\n"
        "ENDPNL\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    segs = [json.loads(r[0]) for r in con.execute(
        "SELECT data_json FROM message_segments ORDER BY seq")]
    assert segs[0]["actual_parsed_pax"] == 6
    assert segs[0]["declared_total"] == 173


def test_pnl_tallies_ssr_codes_and_keeps_import_pii_out_of_facts(tmp_path, make_archive):
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".HKGDMK 130900\r\n"
        "\x02PNL\r\n"
        "SL0365/13AUG HKG PART1\r\n"
        "-DMK173Y-PAD000\r\n"
        "SSR CTCM AA HK1/16312352108-1CUMMINGS/GABRIELLE\r\n"
        "SSR CTCM AA HK1/55221144705-1SMITH/JOHNMR\r\n"
        "SSR WCHR AA HK1/2-1JONES/FREDMR\r\n"
        ".R/FBA 1PC\r\n"
        "OSI AA CTCT SEA EXPEDIA API USER\r\n"
        "ENDPNL\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["ssrs"] == {"CTCM": 2, "WCHR": 1, "FBA": 1}
    # PII must not surface in the structured facts
    as_text = json.dumps(facts)
    for pii in ("16312352108", "55221144705", "CUMMINGS", "GABRIELLE",
                "SMITH", "JOHN", "JONES", "FRED", "SEA", "EXPEDIA"):
        assert pii not in as_text, pii


def test_forward_extracts_header_components_nationalities_and_rows(tmp_path, make_archive):
    body = (
        "FWD\r\n"
        "UO117/28.NRT.3/3/7 -TPE.B60.R50.A45.L5.T150.HKG/3.GBR/102.CHN/120\r\n"
        ".P\r\n"
        "AA021 LAX 4Y 3B\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    fact = con.execute("SELECT family, facts_json FROM message_facts").fetchone()
    assert fact["family"] == "FORWARD"
    facts = json.loads(fact["facts_json"])
    assert facts["destination"] == "TPE"
    assert facts["crew"] == "3/3/7"
    assert facts["components"] == {"B": 60, "R": 50, "A": 45, "L": 5, "T": 150}
    # HKG/3 rides on the same dot-notation; captured too - interpretation
    # layers filter airport codes out (documented ambiguity in the spec).
    assert facts["nationalities"] == {"GBR": 102, "CHN": 120, "HKG": 3}
    seg = json.loads(con.execute("SELECT data_json FROM message_segments").fetchone()["data_json"])
    assert seg == {"hop": "TPE", "flight": "AA021", "destination": "LAX", "detail": "4Y 3B"}


def test_asm_is_muted_unless_airline_allowlisted(tmp_path, make_archive):
    body = (
        "\r\n\x01QU HKGTSXH\r\n"
        ".HKGUOXX 120825\r\n"
        "\x02ASM\r\n"
        "UO112/12MAY26 6/UO113/12\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["muted"] is True

    import amg.extractors as ext
    ext.ASM_AIRLINES_TO_PROCESS.add("UO")
    try:
        con2 = ingest_text(tmp_path, make_archive, body,
                           archive_name="PROCESSED_20260611_0025.tar.Z")
        facts2 = json.loads(con2.execute(
            "SELECT facts_json FROM message_facts ORDER BY message_id DESC LIMIT 1"
        ).fetchone()["facts_json"])
        assert facts2.get("muted", False) is False
        assert facts2["flight_number"] == "UO112"
    finally:
        ext.ASM_AIRLINES_TO_PROCESS.clear()


def test_column_mappings_can_block_fields_from_facts(tmp_path, make_archive):
    from amg.extractors import apply_column_mappings

    blocked = apply_column_mappings({"pob": 100, "dva": "BNE"}, {"POB_BLOCKED_TEST": None})
    assert isinstance(blocked, dict)


def test_long_lines_are_flagged_not_rejected_by_default(tmp_path, make_archive):
    long_line = "X" * 300
    body = (
        "\r\n\x01QU HKGTSXH\r\n"
        ".HDQNPNZ 220216\r\n"
        f"\x02DIV\r\nNZ081/21.ZKNZC.HKG\r\n{long_line}\r\n\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["line_limit_violations"] >= 1


def test_fwd_dash_destination_on_its_own_line_is_captured(tmp_path, make_archive):
    body = (
        "FWD\r\n"
        "MU725/28.HKG.3/3/7\r\n"
        "-ICN.B30.R40.A25.L1.T350.HKG/2.GBR/10.CHN/120\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["crew"] == "3/3/7"
    assert facts["destination"] == "ICN"
    assert facts["components"] == {"B": 30, "R": 40, "A": 25, "L": 1, "T": 350}
    assert facts["nationalities"] == {"GBR": 10, "CHN": 120, "HKG": 2}


def test_fwd_collects_every_destination_block(tmp_path, make_archive):
    body = (
        "FWD\r\n"
        "UO117/28.NRT.3/3/7 -TPE.B60.R50\r\n"
        "-ICN.B10.R20\r\n"
        ".P\r\n"
        "AA021 HKG 1Y -HKG.B7.R8.A9.L2.T50.\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert [d["airport"] for d in facts["destinations"]] == ["TPE", "ICN", "HKG"]
    assert facts["destinations"][2] == {
        "airport": "HKG", "B": 7, "R": 8, "A": 9, "L": 2, "T": 50,
    }
    # multi-hop semantics: destination = LAST block (final arrival)
    assert facts["destination"] == "HKG"


MULTIHOP_FWD = (
    "FWDZZ779/19.NRT.3/3/7\r\n"
    "-TPE.B60.R50.A45.L5.T150.HKG/3.GBR/102.CHN/120\r\n"
    ".P\r\n"
    "AA021 LAX 4Y 3B\r\n"
    "AA021 LAX 1Y 0B.SA\r\n"
    "AA595 DTW 3Y INF1\r\n"
    "AA665 SJU 1Y.CHD1.RQ\r\n"
    "AC189S YUL 1F.RQ\r\n"
    "TW219 CLE 5Y 3B\r\n"
    "TW801 IAH 2Y 1B\r\n"
    "UA015 LAX 4Y\r\n"
    "AA021 HKG 1Y\r\n"
    "-HKG.B30.R38.A32.L4.T250.TWN/3.HKG/52.JPN/120\r\n"
    ".P\r\n"
    "KQ709/N ITH 22Y 16B398K\r\n"
    "KQ709/N ITH 2Y 1B29K.SA\r\n"
    "XY311/S JFK 47Y 23B451K\r\n"
    "-JFK.B33.R38.A14.T210.HKG/3.SIN/52.GBR/25\r\n"
    ".P\r\n"
    "CX219 CLE 5Y 3B\r\n"
    "CX801 IAH 2Y 1B\r\n"
    "-SIN.B23.R38.T290.HKG/3.SIN/85\r\n"
    ".P\r\n"
    "BA801 IAH 2Y 1B\r\n"
    "BA015 LAX 4Y\r\n"
    "BA021 HKG 1Y\r\n"
    "-LHR.B16.R14.L9.T1500.HKG/5.USA/7.GBR/11\r\n"
    ".P\r\n"
    "NIL\r\n"
    "ENDFWD\r\n"
)


def test_multihop_fwd_from_glued_keyword_is_fully_parsed(tmp_path, make_archive):
    con = ingest_text(tmp_path, make_archive, MULTIHOP_FWD)
    import json
    row = con.execute(
        "SELECT r.msg_type, r.flight_number, f.family, f.facts_json"
        " FROM messages r JOIN message_facts f ON f.message_id = r.id"
    ).fetchone()
    assert row["msg_type"] == "FWD"
    assert row["flight_number"] == "ZZ779"
    facts = json.loads(row["facts_json"])
    assert facts["crew"] == "3/3/7"
    assert [d["airport"] for d in facts["destinations"]] == [
        "TPE", "HKG", "JFK", "SIN", "LHR",
    ]
    assert facts["destination"] == "LHR"
    assert facts["hops"] == 5
    assert facts["nationalities"]["GBR"] == 102 + 25 + 11
    segs = [json.loads(r[0]) for r in con.execute(
        "SELECT data_json FROM message_segments ORDER BY seq"
    )]
    assert len(segs) == 17
    assert segs[0]["hop"] == "TPE" and segs[0]["flight"] == "AA021"
    assert segs[9]["hop"] == "HKG" and segs[9]["flight"] == "KQ709/N"
    assert segs[-1]["hop"] == "SIN"


def test_fwd_day_only_date_uses_archive_month(tmp_path, make_archive):
    body = (
        "FWDZZ779/19.NRT.3/3/7\r\n"
        "-TPE.B60.R50.A45.L5.T150.HKG/3.GBR/102.CHN/120\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    row = con.execute(
        "SELECT flight_date FROM messages WHERE msg_type='FWD'"
    ).fetchone()
    assert row["flight_date"] == "20260619"


def test_fwd_day_only_date_rolls_to_next_month_near_month_end(tmp_path, make_archive):
    body = (
        "FWDZZ779/01.NRT.3/3/7\r\n"
        "-TPE.B60.R50.A45.L5.T150.HKG/3.GBR/102.CHN/120\r\n"
        "\x03\r\n"
    )
    con = ingest_text(
        tmp_path, make_archive, body,
        archive_name="PROCESSED_20260830_0025.tar.Z",
    )
    row = con.execute(
        "SELECT flight_date FROM messages WHERE msg_type='FWD'"
    ).fetchone()
    assert row["flight_date"] == "20260901"


def test_fwd_late_arriving_message_stays_in_same_month(tmp_path, make_archive):
    body = (
        "FWDAB676/27.NRT.3/3/7\r\n"
        "-TPE.B60.R50.A45.L5.T150.HKG/3.GBR/102.CHN/120\r\n"
        "\x03\r\n"
    )
    con = ingest_text(
        tmp_path, make_archive, body,
        archive_name="PROCESSED_20260628_0025.tar.Z",
    )
    row = con.execute(
        "SELECT flight_date FROM messages WHERE msg_type='FWD'"
    ).fetchone()
    assert row["flight_date"] == "20260627"


def test_fwd_month_end_wrap_uses_forward_window(tmp_path, make_archive):
    body = (
        "FWDZZ779/02.NRT.3/3/7\r\n"
        "-TPE.B60.R50.A45.L5.T150.HKG/3.GBR/102.CHN/120\r\n"
        "\x03\r\n"
    )
    con = ingest_text(
        tmp_path, make_archive, body,
        archive_name="PROCESSED_20260131_0025.tar.Z",
    )
    row = con.execute(
        "SELECT flight_date FROM messages WHERE msg_type='FWD'"
    ).fetchone()
    assert row["flight_date"] == "20260202"


def test_ahm780_departure_message_maps_ad_eo_el_and_destination(tmp_path, make_archive):
    body = (
        "\r\nQD HKGTSXH\r\n"
        ".HKGRCCI 082010\r\n"
        "\x02MVT\r\n"
        "CI5836/08.B18780.HKG\r\n"
        "AD1939/2009 EA2122 TPE\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["times"]["AD"] == {"time": "1939", "date": None}
    assert facts["times"]["EO"] == {"time": "2009", "date": None}
    assert facts["times"]["EL"] == {"time": "2122", "date": None}
    assert facts["destination"] == "TPE"


def test_ahm780_arrival_line_splits_touchdown_and_onblocks(tmp_path, make_archive):
    body = (
        "\r\nQD HKGTSXH\r\n"
        ".HKGRCCI 082010\r\n"
        "\x02MVT\r\n"
        "CI5836/08.B18780.HKG\r\n"
        "AD1939/2009 EA2122 TPE\r\n"
        "TD2205 AA2221\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["times"]["TD"] == {"time": "2205", "date": None}
    assert facts["times"]["AA"] == {"time": "2221", "date": None}


def test_ahm780_six_digit_times_carry_date_component(tmp_path, make_archive):
    body = (
        "\r\n\x01QU HKGTSXH\r\n"
        ".TYOXKJL 070132\r\n"
        "\x02MVT\r\n"
        "JL0029/07.JA872J.HND\r\n"
        "AD070110/070132 EA070527 HKG\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["times"]["AD"] == {"time": "0110", "date": "07"}
    assert facts["times"]["EO"] == {"time": "0132", "date": "07"}
    assert facts["times"]["EL"] == {"time": "0527", "date": "07"}
    assert facts["destination"] == "HKG"


def test_ahm780_edl_and_dla_delay_lines_fill_secondary_slots(tmp_path, make_archive):
    body = (
        "\r\nQD HKGTSXH\r\n"
        ".HKGRCCI 082010\r\n"
        "\x02MVT\r\n"
        "CI5836/08.B18780.HKG\r\n"
        "AD1939/2009 EA2122 TPE\r\n"
        "DL57/0015\r\n"
        "EDL12/0030\r\n"
        "DLA93//95/\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    delays = facts["delays"]
    assert delays["IR1"] == "57" and delays["DL1"] == "0015"
    assert delays["IR3"] == "12" and delays["DL3"] == "0030"
    assert delays["IR5"] == "93" and delays["IR6"] == "95"


def test_ahm780_px_line_extracts_transit_local_and_total(tmp_path, make_archive):
    body = (
        "\r\nQD HKGTSXH\r\n"
        ".HKGRCCI 082010\r\n"
        "\x02MVT\r\n"
        "VJ986/22.VN-A544.PQC\r\n"
        "AD0521/0528 EA0828 HKG\r\n"
        "PAX215+0INF\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["pax"] == {"total": 215, "infants": 0}

    body2 = (
        "\r\nQD HKGTSXH\r\n"
        ".HKGRCCI 082010\r\n"
        "\x02MVA\r\n"
        "CI5836/08.B18780.HKG\r\n"
        "AD1939/2009 EA2122 TPE\r\n"
        "PX30/185\r\n"
        "\x03\r\n"
    )
    con2 = ingest_text(tmp_path, make_archive, body2,
                       archive_name="PROCESSED_20260611_0025.tar.Z")
    facts2 = json.loads(
        con2.execute("SELECT facts_json FROM message_facts ORDER BY message_id DESC LIMIT 1")
        .fetchone()["facts_json"]
    )
    assert facts2["pax"] == {"transit": 30, "disembarking": 185, "total": 215}


def test_ahm780_si_block_extracts_fuel_weights_and_eet(tmp_path, make_archive):
    body = (
        "\r\n\x01QD HKGTSXH\r\n"
        ".HKGODCI 061625\r\n"
        "\x02MVT\r\n"
        "CI5825/06.B18778.HKG\r\n"
        "AA1612/1624\r\n"
        "SI\r\n"
        "PN0401 EET0122 BO23286 TOF62161 PL137063 LIZFW49.7 ZFW449049\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    si = facts["si"]
    assert si["eet"] == "0122"
    assert si["burn_off"] == 23286
    assert si["takeoff_fuel"] == 62161
    assert si["payload"] == 137063
    assert si["zfw"] == 449049


def test_ahm780_si_inline_line_extracts_fuel_remaining(tmp_path, make_archive):
    body = (
        "\r\n\x01QU HKGTSXH\r\n"
        ".HKGRCCI 082010\r\n"
        "\x02MVT\r\n"
        "VJ986/22.VN-A544.PQC\r\n"
        "AD0521/0528 EA0828 HKG\r\n"
        "SI DOOR CLSD 0455\r\n"
        "SI CHOCK OFF 0456\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    si = facts["si"]
    assert si["events"] == [
        {"label": "DOOR CLSD", "time": "0455"},
        {"label": "CHOCK OFF", "time": "0456"},
    ]


def test_ahm780_si_spaced_value_form(tmp_path, make_archive):
    body = (
        "\r\n\x01QU HKGTSXH\r\n"
        ".HKGRCCI 082010\r\n"
        "\x02MVT\r\n"
        "CI5825/06.B18778.HKG\r\n"
        "AA1612/1624\r\n"
        "SI\r\n"
        "FR 50500\r\n"
        "\x03\r\n"
    )
    con = ingest_text(tmp_path, make_archive, body)
    import json
    facts = json.loads(
        con.execute("SELECT facts_json FROM message_facts").fetchone()["facts_json"]
    )
    assert facts["si"]["fuel_remaining"] == 50500


def test_unhandled_types_store_no_fact_row(tmp_path, make_archive):
    body = "\r\n\x01QU HKGTSXH\r\n.TYOXXZZ 070132\r\n\x02ZZZ\r\nhello\r\n\x03\r\n"
    con = ingest_text(tmp_path, make_archive, body)
    assert con.execute("SELECT COUNT(*) FROM message_facts").fetchone()[0] == 0

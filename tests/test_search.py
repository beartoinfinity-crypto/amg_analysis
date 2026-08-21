import sqlite3

from amg.cli import main

THREE_MESSAGES = {
    "HKG/260607002540778.rcv": (
        "QD HKGTSXH\n.HKGODCI 061625/AMAMQ\nMVT\nCI5825/06.B18778.HKG\nFR 50500\n"
    ),
    "HKG/260608101112111.rcv": (
        "QU HKGTSXH\n.HKGOPXH 061026\nMVT\nNH814/06.JA808A.HKG\nSI\n"
    ),
    "HKG/260609002526404.COR": (
        "QU HKGTSXH\n.ISTKMTK 081625 BMD-094-081625\nBSM\n.P/FRYDA/PATRYKDAWID\nENDBSM\n"
    ),
}


def ingest_fixture(tmp_path, make_archive):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    make_archive(archive_dir / "PROCESSED_20260610_0025.tar.Z", THREE_MESSAGES)
    db = tmp_path / "index.db"
    assert main(["ingest", str(archive_dir), "--db", str(db)]) == 0
    return db


def run(capsys, db, *argv):
    code = main(["search", "--db", str(db), *argv])
    out = capsys.readouterr().out
    return code, out.splitlines()


def test_search_without_filters_lists_all_newest_first(tmp_path, make_archive, capsys):
    db = ingest_fixture(tmp_path, make_archive)

    code, lines = run(capsys, db)

    assert code == 0
    ids = [line.split()[0] for line in lines[1:]]
    assert len(ids) == 3
    received = [line.split()[1] for line in lines[1:]]
    assert received == sorted(received, reverse=True)


def test_search_combines_type_flight_and_date_filters(tmp_path, make_archive, capsys):
    db = ingest_fixture(tmp_path, make_archive)

    code, lines = run(capsys, db, "--type", "MVT", "--flight", "CI5825")
    assert code == 0
    assert len(lines) == 2 and "CI5825" in lines[1]

    code, lines = run(capsys, db, "--type", "MVT")
    assert len(lines) == 3

    code, lines = run(capsys, db, "--from", "2026-06-08", "--to", "2026-06-08")
    assert len(lines) == 2 and "NH814" in lines[1]

    code, lines = run(capsys, db, "--origin", "ISTKMTK")
    assert len(lines) == 2 and "BSM" in lines[1]


def test_search_free_text_matches_body(tmp_path, make_archive, capsys):
    db = ingest_fixture(tmp_path, make_archive)

    code, lines = run(capsys, db, "--q", "50500")

    assert code == 0
    assert len(lines) == 2 and "CI5825" in lines[1]


def test_search_csv_export_round_trips_columns(tmp_path, make_archive, capsys):
    db = ingest_fixture(tmp_path, make_archive)

    code, lines = run(capsys, db, "--csv")

    assert code == 0
    assert lines[0].startswith("id,received_at,station,status,msg_type")
    data_rows = [line for line in lines[1:] if line.strip()]
    assert len(data_rows) == 3
    assert any("CI5825" in row for row in data_rows)


def test_show_prints_stored_raw_text_verbatim(tmp_path, make_archive, capsys):
    db = ingest_fixture(tmp_path, make_archive)
    con = sqlite3.connect(db)
    msg_id = con.execute("SELECT id FROM messages WHERE msg_type = 'MVT'").fetchone()[0]

    code = main(["show", "--db", str(db), str(msg_id)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == THREE_MESSAGES["HKG/260607002540778.rcv"]

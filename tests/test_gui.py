import sqlite3

from amg.cli import main, rebuild_archives, scan_archives


def make_two_archives(tmp_path, make_archive):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    make_archive(
        archive_dir / "PROCESSED_20260610_0025.tar.Z",
        {"HKG/260607002540778.rcv": "QU HKGTSXH\nMVT\nCI5825/06.B18778.HKG\n"},
    )
    make_archive(
        archive_dir / "CORRUPTED_20260612_0025.tar.Z",
        {"HKG/260609002526404.COR": "PNL \nENDPNL\n"},
    )
    return archive_dir


def test_ingest_only_flag_imports_just_the_named_archive(tmp_path, make_archive, capsys):
    archive_dir = make_two_archives(tmp_path, make_archive)
    db = tmp_path / "index.db"

    exit_code = main([
        "ingest", str(archive_dir), "--db", str(db),
        "--only", "PROCESSED_20260610_0025.tar.Z",
    ])

    assert exit_code == 0
    assert "1 ingested, 0 skipped, 0 failed" in capsys.readouterr().err
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1


def test_scan_archives_reports_indexed_and_pending_with_sizes(tmp_path, make_archive):
    archive_dir = make_two_archives(tmp_path, make_archive)
    db = tmp_path / "index.db"
    main(["ingest", str(archive_dir), "--db", str(db)])

    entries = scan_archives(archive_dir, db)

    assert [(e["name"], e["state"]) for e in entries] == [
        ("CORRUPTED_20260612_0025.tar.Z", "indexed"),
        ("PROCESSED_20260610_0025.tar.Z", "indexed"),
    ]
    assert all(e["size_bytes"] > 0 for e in entries)


def test_scan_archives_without_db_marks_everything_pending(tmp_path, make_archive):
    archive_dir = make_two_archives(tmp_path, make_archive)

    entries = scan_archives(archive_dir, tmp_path / "missing.db")

    assert {e["state"] for e in entries} == {"pending"}


def test_rebuild_replaces_rows_parsed_with_older_rules(tmp_path, make_archive):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    archive_path = archive_dir / "PROCESSED_20260610_0025.tar.Z"
    make_archive(archive_path, {"HKG/260607002540778.rcv": "\x02PNL\r\nLJ805/13MAY MAN PART1\r\n"})
    db = tmp_path / "index.db"
    main(["ingest", str(archive_dir), "--db", str(db)])
    make_archive(
        archive_path,
        {"HKG/260607002540778.rcv": "\x02PNL\r\nLJ805/13MAY MAN PART2\r\n"},
    )

    ingested, skipped, failed = rebuild_archives(sorted(archive_dir.glob("*.tar.Z")), db)

    assert (ingested, skipped, failed) == (1, 0, 0)
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT flight_airport, part_number FROM messages"
    ).fetchone()
    assert row == ("MAN", 2)

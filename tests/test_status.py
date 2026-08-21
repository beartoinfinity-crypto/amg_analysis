import sqlite3

from amg.cli import main


def make_two_archives(tmp_path, make_archive):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    make_archive(
        archive_dir / "PROCESSED_20260610_0025.tar.Z",
        {"HKG/260607002540778.rcv": "QU HKGTSXH\nMVT\nCI5825/06.B18778.HKG\n"},
    )
    make_archive(
        archive_dir / "CORRUPTED_20260612_0025.tar.Z",
        {"HKG/260609002526404.COR": "BSM\nENDBSM\n"},
    )
    return archive_dir


def test_status_lists_indexed_and_pending_archives(tmp_path, make_archive, capsys):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    make_archive(
        archive_dir / "PROCESSED_20260610_0025.tar.Z",
        {"HKG/260607002540778.rcv": "QU HKGTSXH\nMVT\nCI5825/06.B18778.HKG\n"},
    )
    db = tmp_path / "index.db"
    main(["ingest", str(archive_dir), "--db", str(db)])
    make_archive(
        archive_dir / "CORRUPTED_20260612_0025.tar.Z",
        {"HKG/260609002526404.COR": "BSM\nENDBSM\n"},
    )
    capsys.readouterr()

    code = main(["status", "--db", str(db), "--archive-dir", str(archive_dir)])
    out = capsys.readouterr().out.splitlines()

    assert code == 0
    assert out == [
        "CORRUPTED_20260612_0025.tar.Z pending",
        "PROCESSED_20260610_0025.tar.Z indexed",
    ]


def test_clean_ingest_prints_summary_and_exits_zero(tmp_path, make_archive, capsys):
    archive_dir = make_two_archives(tmp_path, make_archive)
    db = tmp_path / "index.db"

    code = main(["ingest", str(archive_dir), "--db", str(db)])
    err = capsys.readouterr().err.splitlines()

    assert code == 0
    assert err[-1] == "ingest summary: 2 ingested, 0 skipped, 0 failed"

    code = main(["ingest", str(archive_dir), "--db", str(db)])
    err = capsys.readouterr().err.splitlines()

    assert code == 0
    assert err[-1] == "ingest summary: 0 ingested, 2 skipped, 0 failed"


def test_unreadable_archive_fails_alone_with_exit_three(tmp_path, make_archive, capsys):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    (archive_dir / "GARBAGE_20260601_0025.tar.Z").write_bytes(b"definitely not a tar")
    make_archive(
        archive_dir / "PROCESSED_20260610_0025.tar.Z",
        {"HKG/260607002540778.rcv": "QU HKGTSXH\nMVT\nCI5825/06.B18778.HKG\n"},
    )
    db = tmp_path / "index.db"

    code = main(["ingest", str(archive_dir), "--db", str(db)])
    err = capsys.readouterr().err.splitlines()

    assert code == 3
    assert err[-1] == "ingest summary: 1 ingested, 0 skipped, 1 failed"
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1


def test_all_archives_unreadable_exits_one(tmp_path, capsys):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    (archive_dir / "GARBAGE_20260601_0025.tar.Z").write_bytes(b"definitely not a tar")
    db = tmp_path / "index.db"

    code = main(["ingest", str(archive_dir), "--db", str(db)])

    assert code == 1

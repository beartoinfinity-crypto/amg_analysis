import sqlite3
from pathlib import Path

import pytest

from amg.cli import main


def test_ingest_stores_raw_messages_with_derived_columns(tmp_path, make_archive):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    make_archive(
        archive_dir / "PROCESSED_20260610_0025.tar.Z",
        {
            "HKG/260607002540778.rcv": (
                "QU HKGTSXH\n.HKGODCI 061625/AMAMQ\nMVT\nCI5825/06.B18778.HKG\n"
            ),
            "HKG/260609002526404.COR": "PNL \nCX841/08JUN JFK PART1 \nENDPNL\n",
        },
    )
    db = tmp_path / "index.db"

    exit_code = main(["ingest", str(archive_dir), "--db", str(db)])

    assert exit_code == 0
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT received_at, station, status, raw_text, source_archive, source_file"
        " FROM messages ORDER BY source_file"
    ).fetchall()
    assert rows == [
        (
            "2026-06-07T00:25:40.778",
            "HKG",
            "processed",
            "QU HKGTSXH\n.HKGODCI 061625/AMAMQ\nMVT\nCI5825/06.B18778.HKG\n",
            "PROCESSED_20260610_0025.tar.Z",
            "HKG/260607002540778.rcv",
        ),
        (
            "2026-06-09T00:25:26.404",
            "HKG",
            "corrupted",
            "PNL \nCX841/08JUN JFK PART1 \nENDPNL\n",
            "PROCESSED_20260610_0025.tar.Z",
            "HKG/260609002526404.COR",
        ),
    ]


def test_reingesting_the_same_archives_changes_nothing(tmp_path, make_archive):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    make_archive(
        archive_dir / "PROCESSED_20260610_0025.tar.Z",
        {"HKG/260607002540778.rcv": "QU HKGTSXH\nMVT\nCI5825/06.B18778.HKG\n"},
    )
    db = tmp_path / "index.db"
    main(["ingest", str(archive_dir), "--db", str(db)])

    exit_code = main(["ingest", str(archive_dir), "--db", str(db)])

    assert exit_code == 0
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM archives").fetchone()[0] == 1


def test_reingesting_a_replaced_archive_of_different_size_reingests(tmp_path, make_archive):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    archive_path = archive_dir / "PROCESSED_20260610_0025.tar.Z"
    make_archive(archive_path, {"HKG/260607002540778.rcv": "QU HKGTSXH\nMVT\nCI5825/06.B18778.HKG\n"})
    db = tmp_path / "index.db"
    main(["ingest", str(archive_dir), "--db", str(db)])
    make_archive(
        archive_path,
        {
            "HKG/260607002540778.rcv": "QU HKGTSXH\nMVT\nCI5825/06.B18778.HKG\n",
            "HKG/260609002526404.COR": "PNL \nENDPNL\n",
        },
    )

    exit_code = main(["ingest", str(archive_dir), "--db", str(db)])

    assert exit_code == 0
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
    assert con.execute(
        "SELECT COUNT(*) FROM messages WHERE source_file = 'HKG/260609002526404.COR'"
    ).fetchone()[0] == 1
    assert (
        con.execute("SELECT size FROM archives WHERE name = ?", (archive_path.name,)).fetchone()[0]
        == archive_path.stat().st_size
    )


def test_ingest_leaves_source_archives_byte_identical(tmp_path, make_archive):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    archive = make_archive(
        archive_dir / "PROCESSED_20260610_0025.tar.Z",
        {"HKG/260607002540778.rcv": "QU HKGTSXH\nMVT\nCI5825/06.B18778.HKG\n"},
    )
    before = archive.read_bytes()
    db = tmp_path / "index.db"

    exit_code = main(["ingest", str(archive_dir), "--db", str(db)])

    assert exit_code == 0
    assert archive.read_bytes() == before


REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_ARCHIVES = REPO_ROOT / "AMG_msg"


@pytest.mark.integration
def test_real_corpus_ingests_completely(tmp_path):
    if not REAL_ARCHIVES.is_dir():
        pytest.skip("real archive corpus not present")
    db = tmp_path / "index.db"

    exit_code = main(["ingest", str(REAL_ARCHIVES), "--db", str(db)])

    assert exit_code == 0
    con = sqlite3.connect(db)
    assert (
        con.execute(
            "SELECT COUNT(*) FROM messages WHERE source_archive = ?",
            ("PROCESSED_20260610_0025.tar.Z",),
        ).fetchone()[0]
        == 5595
    )
    assert (
        con.execute(
            "SELECT COUNT(*) FROM messages WHERE source_archive = ?",
            ("CORRUPTED_20260612_0025.tar.Z",),
        ).fetchone()[0]
        == 1727
    )
    raw = con.execute(
        "SELECT raw_text FROM messages WHERE source_file = ?",
        ("HKG/260607002540778.rcv",),
    ).fetchone()[0]
    assert raw == (
        "\r\n\x01QD HKGTSXH\r\n"
        ".HKGODCI 061625/AMAMQ\r\n"
        "\x02MVT\r\n"
        "CI5825/06.B18778.HKG\r\n"
        "AA1612/1624\r\n"
        "SI\r\n"
        "FR 50500\r\n"
        "\x03\r\n"
    )


def test_readable_view_strips_control_characters(tmp_path, make_archive):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    make_archive(
        archive_dir / "PROCESSED_20260610_0025.tar.Z",
        {"HKG/260607002540778.rcv": "\x01QU HKGTSXH\r\n\x02MVT\r\nCI5825/06.B18778.HKG\r\n\x03"},
    )
    db = tmp_path / "index.db"

    exit_code = main(["ingest", str(archive_dir), "--db", str(db)])

    assert exit_code == 0
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT message_text FROM messages_readable WHERE id = 1"
    ).fetchone()
    assert row[0] == "QU HKGTSXH\r\nMVT\r\nCI5825/06.B18778.HKG\r\n"


def test_ingest_survives_nonstandard_filename_shapes(tmp_path, make_archive):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    make_archive(
        archive_dir / "PROCESSED_20260516_0025.tar.Z",
        {
            "HKG/260509002655086.rcv": "QU HKGTSXH\nMVA\nNH814/06.JA808A.HKG\n",
            "HKG/202605120000001.COR": "BSM\nENDBSM\n",
            "HKG/347000002222.rcv": "QU HKGTSXH\nSVC\n",
        },
    )
    db = tmp_path / "index.db"

    exit_code = main(["ingest", str(archive_dir), "--db", str(db)])

    assert exit_code == 0
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT received_at, status FROM messages ORDER BY source_file"
    ).fetchall()
    assert rows == [
        ("2026-05-12T00:00:00.100", "corrupted"),
        ("2026-05-09T00:26:55.086", "processed"),
        (None, "processed"),
    ]

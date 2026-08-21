import pytest

from amg.cli import main

FIXTURE = {
    "HKG/260607002540778.rcv": (
        "QD HKGTSXH\n.HKGODCI 061625\nMVT\nCI5825/06.B18778.HKG\n"
    ),
    "HKG/260607114511222.rcv": "QU HKGTSXH\n.HKGOPXH 061145\nMVT\nNH814/06.JA808A.HKG\n",
    "HKG/260608002526404.COR": "QU HKGTSXH\n.ISTKMTK 081625\nBSM\nENDBSM\n",
    "HKG/347000002222.rcv": "QU HKGTSXH\nSVC\n",
}


def run_stats(capsys, tmp_path, make_archive, *argv):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    make_archive(archive_dir / "PROCESSED_20260610_0025.tar.Z", FIXTURE)
    db = tmp_path / "index.db"
    assert main(["ingest", str(archive_dir), "--db", str(db)]) == 0
    code = main(["stats", "--db", str(db), *argv])
    return code, capsys.readouterr().out.splitlines()


def test_stats_by_day_splits_processed_and_corrupted(tmp_path, make_archive, capsys):
    code, lines = run_stats(capsys, tmp_path, make_archive, "--by", "day")

    assert code == 0
    assert lines == [
        "day total processed corrupted",
        "2026-06-07 2 2 0",
        "2026-06-08 1 0 1",
        "- 1 1 0",
    ]


def test_stats_by_hour_buckets_within_a_day(tmp_path, make_archive, capsys):
    code, lines = run_stats(capsys, tmp_path, make_archive, "--by", "hour")

    assert code == 0
    assert "2026-06-07T00 1 1 0" in lines
    assert "2026-06-07T11 1 1 0" in lines


def test_stats_by_type_counts_messages_per_type(tmp_path, make_archive, capsys):
    code, lines = run_stats(capsys, tmp_path, make_archive, "--by", "type")

    assert code == 0
    assert lines == ["type total", "MVT 2", "BSM 1", "SVC 1"]


def test_stats_by_airline_attributes_flight_prefix(tmp_path, make_archive, capsys):
    code, lines = run_stats(capsys, tmp_path, make_archive, "--by", "airline")

    assert code == 0
    assert lines == ["airline total", "CI 1", "NH 1", "- 2"]


def test_stats_by_airline_keeps_three_letter_carrier_codes(tmp_path, make_archive, capsys):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    make_archive(
        archive_dir / "PROCESSED_20260610_0025.tar.Z",
        {"HKG/260607002540778.rcv": "QU HKGTSXH\nMVT\nDLH123/45.DAIXY.FRA\n"},
    )
    db = tmp_path / "index.db"
    main(["ingest", str(archive_dir), "--db", str(db)])

    code = main(["stats", "--db", str(db), "--by", "airline"])
    lines = capsys.readouterr().out.splitlines()

    assert code == 0
    assert lines == ["airline total", "DLH 1"]


def test_stats_supports_csv_output(tmp_path, make_archive, capsys):
    code, lines = run_stats(capsys, tmp_path, make_archive, "--by", "type", "--csv")

    assert code == 0
    assert lines[0] == "type,total"
    assert "MVT,2" in lines


@pytest.mark.parametrize("bad", [["--by", "week"], []])
def test_stats_rejects_unknown_grouping(tmp_path, make_archive, capsys, bad):
    archive_dir = tmp_path / "AMG_msg"
    archive_dir.mkdir()
    make_archive(archive_dir / "PROCESSED_20260610_0025.tar.Z", FIXTURE)
    db = tmp_path / "index.db"
    main(["ingest", str(archive_dir), "--db", str(db)])

    code = main(["stats", "--db", str(db), *bad])

    assert code == 2

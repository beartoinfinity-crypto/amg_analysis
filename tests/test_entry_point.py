import subprocess
import sys


def test_python_dash_m_amg_entry_point_works():
    result = subprocess.run(
        [sys.executable, "-m", "amg", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "ingest" in result.stdout

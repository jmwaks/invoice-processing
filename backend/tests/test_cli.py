import subprocess
import sys
from pathlib import Path
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BACKEND_DIR / "data" / "inventory.db"
VENV_PYTHON = BACKEND_DIR.parent / ".venv" / "bin" / "python"


@pytest.mark.skipif(not DB_PATH.exists(), reason="run `make seed` first")
def test_cli_help_runs():
    python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    result = subprocess.run(
        [python, "-m", "app.main", "--help"],
        capture_output=True, text=True, cwd=str(BACKEND_DIR),
    )
    assert result.returncode == 0
    assert "--invoice_path" in result.stdout

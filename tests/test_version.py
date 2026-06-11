import sys, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def test_version_import():
    from __version__ import __version__
    assert __version__ == "0.3.5"

def test_version_cli():
    result = subprocess.run(
        [sys.executable, "main.py", "--version"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    output = result.stdout.strip() + result.stderr.strip()
    assert "ChatScreen2PDF 0.3.5" in output

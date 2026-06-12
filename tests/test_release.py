import sys, subprocess, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_release.py"

def test_build_release_creates_zip():
    zip_path = PROJECT_ROOT / "ChatScreen2PDF-v1.0.0-ocr-ready-source.zip"
    if zip_path.exists(): zip_path.unlink()
    result = subprocess.run([sys.executable, str(BUILD_SCRIPT)], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    assert result.returncode == 0, result.stderr
    assert zip_path.exists()
    zip_path.unlink()

def test_zip_contents_clean():
    zip_path = PROJECT_ROOT / "ChatScreen2PDF-v1.0.0-ocr-ready-source.zip"
    if zip_path.exists(): zip_path.unlink()
    subprocess.run([sys.executable, str(BUILD_SCRIPT)], capture_output=True, cwd=str(PROJECT_ROOT))
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
    for name in names:
        assert "__pycache__" not in name
        assert not name.endswith(".pyc")
    assert "chatScreen2pdf/gui_app.py" in names or "chatScreen2pdf/web_app.py" in names
    assert "chatScreen2pdf/utils/open_folder.py" in names
    zip_path.unlink()

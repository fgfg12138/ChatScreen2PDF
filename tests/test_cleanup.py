import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.cleanup import TempDir


def test_temp_dir_created_and_removed():
    tmp_path = None
    with TempDir() as tmp:
        tmp_path = tmp
        assert tmp.exists() and tmp.is_dir()
        (tmp / "test.txt").write_text("hello")
        assert (tmp / "test.txt").exists()
    assert not tmp_path.exists()


def test_temp_dir_cleanup_on_exception():
    tmp_path = None
    try:
        with TempDir() as tmp:
            tmp_path = tmp
            assert tmp.exists()
            raise ValueError("test")
    except ValueError:
        pass
    assert tmp_path is not None and not tmp_path.exists()


def test_temp_dir_prefix():
    with TempDir(prefix="myapp_") as tmp:
        assert tmp.name.startswith("myapp_")


def test_temp_dir_is_unique():
    paths = []
    for _ in range(3):
        with TempDir() as tmp:
            paths.append(tmp)
    assert len(set(str(p) for p in paths)) == 3

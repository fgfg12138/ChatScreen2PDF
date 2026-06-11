import sys
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.scanner import scan_videos


def _touch(base, relative):
    p = base / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    return p


def test_finds_all_supported_formats(tmp_path):
    files = sorted([
        _touch(tmp_path, "a.mp4"),
        _touch(tmp_path, "b.MOV"),
        _touch(tmp_path, "sub/c.avi"),
        _touch(tmp_path, "sub/d.MKV"),
        _touch(tmp_path, "e.webm"),
    ])
    assert scan_videos(tmp_path) == files


def test_ignores_non_video_files(tmp_path):
    _touch(tmp_path, "readme.txt")
    _touch(tmp_path, "photo.jpg")
    _touch(tmp_path, "video.mp4")
    result = scan_videos(tmp_path)
    assert len(result) == 1 and result[0].name == "video.mp4"


def test_recursive_scan(tmp_path):
    _touch(tmp_path, "a.mp4")
    _touch(tmp_path, "sub1/b.mp4")
    _touch(tmp_path, "sub1/sub2/c.mov")
    assert len(scan_videos(tmp_path)) == 3


def test_returns_sorted_paths(tmp_path):
    _touch(tmp_path, "z.mp4")
    _touch(tmp_path, "a.mp4")
    _touch(tmp_path, "m.mp4")
    result = scan_videos(tmp_path)
    assert result == sorted(result)


def test_empty_folder_returns_empty_list(tmp_path):
    assert scan_videos(tmp_path) == []


def test_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_videos(tmp_path / "does_not_exist")


def test_raises_not_a_directory(tmp_path):
    f = _touch(tmp_path, "video.mp4")
    with pytest.raises(NotADirectoryError):
        scan_videos(f)

import sys
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image, ImageDraw
from core.dedup import dedup_frames, _compute_ahash, _hamming


def _make_chat_frame(path, scroll_y=0):
    img = Image.new("RGB", (320, 720), "white")
    d = ImageDraw.Draw(img)
    for i in range(30):
        y = i * 24 - scroll_y
        if 0 <= y < 720:
            d.text((10, y), "User: message " + str(i), fill="black")
    img.save(path, "JPEG", quality=90)


def test_consecutive_removes_identical(tmp_path):
    _make_chat_frame(tmp_path / "f1.jpg", 0)
    _make_chat_frame(tmp_path / "f2.jpg", 0)
    _make_chat_frame(tmp_path / "f3.jpg", 0)
    _make_chat_frame(tmp_path / "f4.jpg", 200)
    result = dedup_frames([tmp_path/"f1.jpg", tmp_path/"f2.jpg", tmp_path/"f3.jpg", tmp_path/"f4.jpg"], threshold=10)
    assert len(result) == 2


def test_consecutive_keeps_scrolled(tmp_path):
    _make_chat_frame(tmp_path / "f1.jpg", 0)
    _make_chat_frame(tmp_path / "f2.jpg", 200)
    assert len(dedup_frames([tmp_path/"f1.jpg", tmp_path/"f2.jpg"], threshold=10)) == 2


def test_global_removes_distant_duplicate(tmp_path):
    _make_chat_frame(tmp_path / "a.jpg", 0)
    _make_chat_frame(tmp_path / "b.jpg", 200)
    _make_chat_frame(tmp_path / "a2.jpg", 0)
    result = dedup_frames([tmp_path/"a.jpg", tmp_path/"b.jpg", tmp_path/"a2.jpg"], threshold=10, mode="global")
    assert len(result) == 2


def test_empty_input():
    assert dedup_frames([], threshold=10) == []


def test_single_frame(tmp_path):
    _make_chat_frame(tmp_path / "only.jpg", 0)
    assert len(dedup_frames([tmp_path/"only.jpg"], threshold=10)) == 1


def test_invalid_mode(tmp_path):
    _make_chat_frame(tmp_path / "a.jpg", 0)
    with pytest.raises(ValueError):
        dedup_frames([tmp_path/"a.jpg"], threshold=10, mode="bad")


def test_ahash_identical_images(tmp_path):
    _make_chat_frame(tmp_path / "a.jpg", 0)
    _make_chat_frame(tmp_path / "b.jpg", 0)
    assert _hamming(_compute_ahash(tmp_path/"a.jpg"), _compute_ahash(tmp_path/"b.jpg")) == 0


def test_ahash_different_images(tmp_path):
    _make_chat_frame(tmp_path / "a.jpg", 0)
    _make_chat_frame(tmp_path / "b.jpg", 200)
    assert _hamming(_compute_ahash(tmp_path/"a.jpg"), _compute_ahash(tmp_path/"b.jpg")) > 10

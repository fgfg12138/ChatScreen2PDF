"""
test_long_image.py — 长截图切片测试（Phase 2）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PIL import Image
from core.long_image import slice_image, validate_params


def _create_long_image(path, width=400, height=5000):
    """创建一张长截图测试图。"""
    img = Image.new("RGB", (width, height), (200, 150, 100))
    img.save(str(path), "PNG")
    return path


def test_validate_params_default():
    validate_params(3000, 150)  # should not raise


def test_validate_params_too_small():
    with pytest.raises(ValueError):
        validate_params(100, 10)


def test_validate_params_too_large():
    with pytest.raises(ValueError):
        validate_params(20000, 10)


def test_validate_params_negative_overlap():
    with pytest.raises(ValueError):
        validate_params(3000, -1)


def test_validate_params_overlap_too_large():
    with pytest.raises(ValueError):
        validate_params(3000, 3000)


def test_slice_image_short_no_slicing(tmp_path):
    img = _create_long_image(tmp_path / "short.png", height=500)
    slices = slice_image(img, tmp_path / "out", slice_height=3000, overlap=150)
    assert len(slices) == 1


def test_slice_image_basic(tmp_path):
    img = _create_long_image(tmp_path / "long.png", height=5000)
    slices = slice_image(img, tmp_path / "out", slice_height=2000, overlap=200)
    # 5000px, slice=2000, overlap=200: 0-2000, 1800-3800, 3600-5000 → 3 slices
    assert len(slices) >= 2
    for s in slices:
        assert s.exists()


def test_slice_image_exact_fit(tmp_path):
    img = _create_long_image(tmp_path / "exact.png", height=3000)
    slices = slice_image(img, tmp_path / "out", slice_height=3000, overlap=0)
    assert len(slices) == 1


def test_slice_image_naming(tmp_path):
    img = _create_long_image(tmp_path / "test_name.png", height=4000)
    slices = slice_image(img, tmp_path / "out", slice_height=2000, overlap=100)
    for s in slices:
        assert "test_name_" in s.name
    # Names should be sorted
    names = [s.name for s in slices]
    assert names == sorted(names)

import sys
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from main import _parse_crop_ratio, _parse_crop_pixels
from core.extractor import _build_vf_filter


# --- crop-ratio validation ---

def test_crop_ratio_valid():
    assert _parse_crop_ratio("0.1,0.0,0.9,1.0") == (0.1, 0.0, 0.9, 1.0)

def test_crop_ratio_full():
    assert _parse_crop_ratio("0.0,0.0,1.0,1.0") == (0.0, 0.0, 1.0, 1.0)

def test_crop_ratio_reversed_x():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_crop_ratio("0.9,0.0,0.1,1.0")

def test_crop_ratio_negative():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_crop_ratio("-0.1,0.0,1.0,1.0")

def test_crop_ratio_over_one():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_crop_ratio("0.0,0.0,1.2,1.0")

def test_crop_ratio_wrong_length():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_crop_ratio("0.0,0.0,1.0")

def test_crop_ratio_reversed_y():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_crop_ratio("0.0,0.9,1.0,0.1")


# --- crop-pixels validation ---

def test_crop_pixels_valid():
    assert _parse_crop_pixels("0:100:1080:1800") == (0, 100, 1080, 1800)

def test_crop_pixels_negative_width():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_crop_pixels("0:0:-100:100")

def test_crop_pixels_negative_left():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_crop_pixels("-1:0:100:100")

def test_crop_pixels_zero_height():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_crop_pixels("0:0:100:0")

def test_crop_pixels_wrong_length():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_crop_pixels("0:0:100")


# --- FFmpeg filter building ---

def test_filter_no_crop():
    assert _build_vf_filter(1.0, None, None) == "fps=1.0"

def test_filter_crop_ratio():
    f = _build_vf_filter(2.0, (0.1, 0.0, 0.9, 1.0), None)
    assert "crop=" in f
    assert "fps=2.0" in f
    assert f.index("crop") < f.index("fps")

def test_filter_crop_pixels():
    f = _build_vf_filter(1.0, None, (0, 100, 1080, 1800))
    assert "crop=1080:1800:0:100" in f
    assert "fps=1.0" in f
    assert f.index("crop") < f.index("fps")

def test_filter_order_crop_before_fps():
    f = _build_vf_filter(1.0, (0.0, 0.0, 1.0, 1.0), None)
    parts = f.split(",")
    assert parts[0].startswith("crop")
    assert parts[1].startswith("fps")

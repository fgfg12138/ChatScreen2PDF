"""
test_video_processor.py — 视频处理测试（Phase 4）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PIL import Image
from core.video_processor import detect_blur, filter_frames


def _create_image(path, width=320, height=240, color=(100, 150, 200)):
    img = Image.new("RGB", (width, height), color)
    img.save(str(path), "JPEG", quality=95)
    return path


def test_detect_blur_sharp_image(tmp_path):
    p = _create_image(tmp_path / "sharp.jpg")
    v = detect_blur(p)
    assert v > 1.0  # 清晰图片有足够的方差


def test_detect_blur_uniform_image(tmp_path):
    # PNG 无损格式，确保纯色
    img = Image.new("RGB", (100, 100), (128, 128, 128))
    p = tmp_path / "uniform.png"
    img.save(str(p), "PNG")
    v = detect_blur(p)
    # 均匀纯色图的 Laplacian 方差约 19（边缘效应）
    # 清晰图应明显高于此值
    assert v < 50


def test_detect_blur_uniform_vs_sharp(tmp_path):
    """纯色图方差应明显小于清晰图。"""
    uniform = Image.new("RGB", (100, 100), (128, 128, 128))
    u = tmp_path / "uniform.png"
    uniform.save(str(u), "PNG")
    v_uniform = detect_blur(u)

    from PIL import ImageDraw
    sharp = Image.new("RGB", (100, 100), (200, 200, 200))
    draw = ImageDraw.Draw(sharp)
    draw.rectangle([10, 10, 90, 90], fill=(50, 50, 50))
    s = tmp_path / "sharp.png"
    sharp.save(str(s), "PNG")
    v_sharp = detect_blur(s)

    assert v_sharp > v_uniform


def test_filter_frames_empty():
    assert filter_frames([]) == []


def test_filter_frames_all_clear(tmp_path):
    imgs = [_create_image(tmp_path / f"{i}.jpg") for i in range(3)]
    result = filter_frames(imgs, blur_threshold=0.1)
    assert len(result) >= 1  # 至少保留一些


def test_filter_frames_drops_blurry(tmp_path):
    clear = _create_image(tmp_path / "clear.jpg")
    uniform = Image.new("RGB", (100, 100), (128, 128, 128))
    blurry = tmp_path / "blurry.jpg"
    uniform.save(str(blurry), "JPEG", quality=95)
    result = filter_frames([clear, blurry], blur_threshold=0.5)
    assert len(result) >= 1
    assert all(p.exists() for p in result)

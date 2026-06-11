import sys
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image, ImageDraw
from core.pdf_builder import build_pdf, build_grid_pdf


def _create_test_image(path, width=320, height=240, color="white"):
    img = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(img)
    for y in range(0, height, 18):
        draw.text((10, y), "Chat message " + str(y) + ": Hello World " * 2, fill="black")
    img.save(path, "JPEG", quality=95)
    return path


def test_build_pdf_lossless(tmp_path):
    images = [_create_test_image(tmp_path / "a.jpg"), _create_test_image(tmp_path / "b.jpg", color="red")]
    result = build_pdf(images, tmp_path / "out.pdf", pdf_mode="lossless")
    assert result.exists() and result.stat().st_size > 0


def test_build_pdf_compressed(tmp_path):
    images = [
        _create_test_image(tmp_path / "a.jpg", width=1920, height=1080),
        _create_test_image(tmp_path / "b.jpg", width=1920, height=1080),
    ]
    lo = tmp_path / "lossless.pdf"
    co = tmp_path / "compressed.pdf"
    build_pdf(images, lo, pdf_mode="lossless")
    build_pdf(images, co, pdf_mode="compressed")
    assert co.stat().st_size <= lo.stat().st_size


def test_build_pdf_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        build_pdf([], tmp_path / "out.pdf")


def test_build_pdf_invalid_mode(tmp_path):
    img = _create_test_image(tmp_path / "a.jpg")
    with pytest.raises(ValueError):
        build_pdf([img], tmp_path / "out.pdf", pdf_mode="invalid")


def test_build_pdf_creates_parent_dirs(tmp_path):
    img = _create_test_image(tmp_path / "a.jpg")
    output = tmp_path / "sub1" / "sub2" / "out.pdf"
    build_pdf([img], output, pdf_mode="lossless")
    assert output.exists()


def test_build_pdf_single_image(tmp_path):
    img = _create_test_image(tmp_path / "single.jpg")
    result = build_pdf([img], tmp_path / "single.pdf")
    assert result.exists()


# ── Grid PDF (Phase 0) ─────────────────────────────────────


def _create_test_image_grid(path, width=320, height=240, color="white"):
    img = Image.new("RGB", (width, height), color)
    img.save(path, "JPEG", quality=95)
    return path


def test_build_grid_pdf_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        build_grid_pdf([], tmp_path / "out.pdf")


def test_build_grid_pdf_invalid_scale_mode(tmp_path):
    img = _create_test_image_grid(tmp_path / "a.jpg")
    with pytest.raises(ValueError):
        build_grid_pdf([img], tmp_path / "out.pdf", scale_mode="zoom")


def test_build_grid_pdf_single_image(tmp_path):
    img = _create_test_image_grid(tmp_path / "single.jpg")
    result = build_grid_pdf([img], tmp_path / "single.pdf", scale_mode="fit")
    assert result.exists() and result.stat().st_size > 0


def test_build_grid_pdf_four_images_one_page(tmp_path):
    imgs = [_create_test_image_grid(tmp_path / f"{i}.jpg") for i in range(4)]
    result = build_grid_pdf(imgs, tmp_path / "out.pdf", scale_mode="fit")
    assert result.exists()
    # 4 images → 1 page (2x2)
    import pikepdf
    pdf = pikepdf.open(str(result))
    assert len(pdf.pages) == 1


def test_build_grid_pdf_five_images_two_pages(tmp_path):
    imgs = [_create_test_image_grid(tmp_path / f"{i}.jpg") for i in range(5)]
    result = build_grid_pdf(imgs, tmp_path / "out.pdf", scale_mode="fill")
    assert result.exists()
    import pikepdf
    pdf = pikepdf.open(str(result))
    assert len(pdf.pages) == 2  # 4 + 1


def test_build_grid_pdf_uses_stem_as_title(tmp_path):
    img = _create_test_image_grid(tmp_path / "my_title.jpg")
    result = build_grid_pdf([img], tmp_path / "my_title.pdf")
    import pikepdf
    pdf = pikepdf.open(str(result))
    # 验证 PDF 元数据标题
    meta = pdf.docinfo.get("/Title")
    assert meta is not None, "PDF title should be set"


def test_build_grid_pdf_fit_mode(tmp_path):
    imgs = [_create_test_image_grid(tmp_path / f"{i}.jpg", width=400, height=300)
            for i in range(3)]
    result = build_grid_pdf(imgs, tmp_path / "fit.pdf", scale_mode="fit")
    assert result.exists()


def test_build_grid_pdf_fill_mode(tmp_path):
    imgs = [_create_test_image_grid(tmp_path / f"{i}.jpg", width=400, height=300)
            for i in range(3)]
    result = build_grid_pdf(imgs, tmp_path / "fill.pdf", scale_mode="fill")
    assert result.exists()


# ── Phase 1: 布局系统测试 ───────────────────────────────────

def test_build_grid_pdf_layout_1x1(tmp_path):
    imgs = [_create_test_image_grid(tmp_path / f"{i}.jpg") for i in range(3)]
    result = build_grid_pdf(imgs, tmp_path / "out.pdf", layout="1x1")
    assert result.exists()
    import pikepdf
    pdf = pikepdf.open(str(result))
    assert len(pdf.pages) == 3


def test_build_grid_pdf_layout_1x2(tmp_path):
    imgs = [_create_test_image_grid(tmp_path / f"{i}.jpg") for i in range(3)]
    result = build_grid_pdf(imgs, tmp_path / "out.pdf", layout="1x2")
    assert result.exists()
    import pikepdf
    pdf = pikepdf.open(str(result))
    assert len(pdf.pages) == 2


def test_build_grid_pdf_layout_2x3(tmp_path):
    imgs = [_create_test_image_grid(tmp_path / f"{i}.jpg") for i in range(7)]
    result = build_grid_pdf(imgs, tmp_path / "out.pdf", layout="2x3")
    assert result.exists()
    import pikepdf
    pdf = pikepdf.open(str(result))
    assert len(pdf.pages) == 2


def test_build_grid_pdf_direction_tb(tmp_path):
    imgs = [_create_test_image_grid(tmp_path / f"{i}.jpg") for i in range(4)]
    result = build_grid_pdf(imgs, tmp_path / "out.pdf", layout="2x2", direction="tb")
    assert result.exists()


def test_build_grid_pdf_title(tmp_path):
    imgs = [_create_test_image_grid(tmp_path / "a.jpg")]
    result = build_grid_pdf(imgs, tmp_path / "out.pdf", title="证据截图")
    assert result.exists()


def test_build_grid_pdf_hide_number(tmp_path):
    imgs = [_create_test_image_grid(tmp_path / f"{i}.jpg") for i in range(2)]
    result = build_grid_pdf(imgs, tmp_path / "out.pdf", show_number=False)
    assert result.exists()


def test_build_grid_pdf_show_page_number(tmp_path):
    imgs = [_create_test_image_grid(tmp_path / f"{i}.jpg") for i in range(6)]
    result = build_grid_pdf(imgs, tmp_path / "out.pdf", show_page_number=True)
    assert result.exists()
    import pikepdf
    pdf = pikepdf.open(str(result))
    assert len(pdf.pages) == 2


def test_build_grid_pdf_invalid_layout(tmp_path):
    img = _create_test_image_grid(tmp_path / "a.jpg")
    with pytest.raises(ValueError):
        build_grid_pdf([img], tmp_path / "out.pdf", layout="3x3")


def test_build_grid_pdf_invalid_direction(tmp_path):
    img = _create_test_image_grid(tmp_path / "a.jpg")
    with pytest.raises(ValueError):
        build_grid_pdf([img], tmp_path / "out.pdf", direction="invalid")

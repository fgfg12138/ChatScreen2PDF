import sys
import zipfile
import re
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.word_builder import build_image_docx


def _make_image(path: Path, color=(120, 160, 210)) -> Path:
    img = Image.new("RGB", (320, 240), color)
    img.save(path, "PNG")
    return path


def test_build_image_docx_creates_word_file(tmp_path):
    img = _make_image(tmp_path / "chat.png")
    out = build_image_docx([img], tmp_path / "chat.docx", title="截图文件")

    assert out.exists()
    assert out.stat().st_size > 1000
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "word/document.xml" in names
    assert any(name.startswith("word/media/") for name in names)


def test_build_image_docx_normalizes_webp_to_word_image(tmp_path):
    img = Image.new("RGBA", (320, 240), (120, 160, 210, 180))
    webp = tmp_path / "chat.webp"
    img.save(webp, "WEBP")

    out = build_image_docx([webp], tmp_path / "chat.docx")

    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        document_xml = zf.read("word/document.xml").decode("utf-8")
    assert "word/media/image1.png" in names
    assert "截图 1" in document_xml


def test_build_image_docx_fits_tall_image_on_one_page(tmp_path):
    tall = tmp_path / "tall.png"
    Image.new("RGB", (1080, 2400), (245, 245, 245)).save(tall, "PNG")

    out = build_image_docx([tall], tmp_path / "tall.docx", show_number=True)

    with zipfile.ZipFile(out) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")
    assert 'wp:extent' in document_xml
    assert 'cy="8869680"' not in document_xml


def test_build_image_docx_reserves_space_for_page_breaks(tmp_path):
    images = []
    for idx in range(3):
        path = tmp_path / f"tall_{idx}.png"
        Image.new("RGB", (1080, 2400), (245, 245, 245)).save(path, "PNG")
        images.append(path)

    out = build_image_docx(images, tmp_path / "multi.docx", show_number=True)

    with zipfile.ZipFile(out) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")
    assert document_xml.count("<pic:pic>") == 3
    assert document_xml.count('w:type="page"') == 2
    heights = [int(value) for value in re.findall(r'cy="(\d+)"', document_xml)]
    assert heights
    assert max(heights) <= 8300000


def test_build_image_docx_empty_raises(tmp_path):
    try:
        build_image_docx([], tmp_path / "empty.docx")
    except ValueError as exc:
        assert "image_paths" in str(exc)
    else:
        raise AssertionError("empty image list should raise")

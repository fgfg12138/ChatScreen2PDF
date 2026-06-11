"""
pdf_builder.py - Image-to-PDF conversion, lossless / compressed modes.
Supports searchable PDF with Chinese text layer via ReportLab.
"""

from __future__ import annotations
import hashlib
import io
import logging
import os
import time
from pathlib import Path

import img2pdf
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color

logger = logging.getLogger(__name__)

DEFAULT_MAX_LONG_EDGE = 1920
DEFAULT_JPEG_QUALITY = 80


def _compress_image(image_path: Path, max_long_edge: int, jpeg_quality: int) -> bytes:
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        w, h = img.size
        long_edge = max(w, h)
        if long_edge > max_long_edge:
            scale = max_long_edge / long_edge
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
        return buf.getvalue()


def _find_cjk_font() -> str:
    """Find a CJK font on the system for Chinese text layer."""
    candidates = [
        # Windows
        "C:/Windows/Fonts/msyh.ttc",      # Microsoft YaHei
        "C:/Windows/Fonts/simsun.ttc",     # SimSun
        "C:/Windows/Fonts/simhei.ttf",     # SimHei
        # Linux
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return ""


def build_pdf(
    image_paths: list[Path], output_path: Path,
    pdf_mode: str = "compressed",
    max_long_edge: int = DEFAULT_MAX_LONG_EDGE,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> Path:
    if not image_paths:
        raise ValueError("image_paths cannot be empty")
    if pdf_mode not in ("lossless", "compressed"):
        raise ValueError("pdf_mode must be lossless or compressed, got: " + str(pdf_mode))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if pdf_mode == "lossless":
        _build_lossless(image_paths, output_path)
    else:
        _build_compressed(image_paths, output_path, max_long_edge, jpeg_quality)

    logger.info("PDF: %s (%.2f MB, %d pages)", output_path.name,
                output_path.stat().st_size / 1024 / 1024, len(image_paths))
    return output_path


def _build_lossless(image_paths: list[Path], output_path: Path) -> None:
    data_list = []
    for p in image_paths:
        if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            data_list.append(p.read_bytes())
        else:
            with Image.open(p) as img:
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                data_list.append(buf.getvalue())
    with open(output_path, "wb") as f:
        f.write(img2pdf.convert(data_list))


def _build_compressed(image_paths, output_path, max_long_edge, jpeg_quality):
    data_list = []
    for p in image_paths:
        try:
            data_list.append(_compress_image(p, max_long_edge, jpeg_quality))
        except Exception as e:
            logger.warning("Compress failed, skip: %s (%s)", p.name, e)
    if not data_list:
        raise ValueError("All image compression failed")
    with open(output_path, "wb") as f:
        f.write(img2pdf.convert(data_list))


def build_searchable_pdf(
    image_paths: list[Path],
    ocr_results: list,
    output_path: Path,
    pdf_mode: str = "compressed",
    max_long_edge: int = DEFAULT_MAX_LONG_EDGE,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> Path:
    """Generate PDF with searchable text layer. Supports CJK fonts."""
    if not image_paths:
        raise ValueError("image_paths cannot be empty")
    if len(image_paths) != len(ocr_results):
        raise ValueError("image_paths and ocr_results length mismatch")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Find CJK font
    font_path = _find_cjk_font()
    font_name = "Helvetica"
    if font_path:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        try:
            pdfmetrics.registerFont(TTFont("CJK", font_path))
            font_name = "CJK"
            logger.info("Using CJK font: %s", font_path)
        except Exception as e:
            logger.warning("Failed to register CJK font (%s), falling back to Helvetica", e)
    else:
        logger.warning("No CJK font found. Chinese text search may not work. "
                       "Install fonts-noto-cjk (Linux) or use Windows with Chinese fonts.")

    c = canvas.Canvas(str(output_path))

    for img_path, ocr_result in zip(image_paths, ocr_results):
        try:
            with Image.open(img_path) as img:
                img_w, img_h = img.size
        except Exception:
            img_w, img_h = 1080, 1920

        page_w = A4[0]
        page_h = page_w * img_h / img_w
        c.setPageSize((page_w, page_h))

        c.drawImage(str(img_path), 0, 0, width=page_w, height=page_h, preserveAspectRatio=True)

        if ocr_result and ocr_result.boxes:
            _draw_text_boxes(c, ocr_result.boxes, page_w, page_h, font_name)

        c.showPage()

    c.save()
    logger.info("Searchable PDF: %s (%.2f MB, %d pages)",
                output_path.name, output_path.stat().st_size / 1024 / 1024, len(image_paths))
    return output_path


def _draw_text_boxes(c, boxes, page_w, page_h, font_name="Helvetica"):
    """Draw invisible text layer for search. Coordinates are normalized 0~1."""
    c.setFillColor(Color(0, 0, 0, alpha=0))
    for box in boxes:
        x = box.x * page_w
        y = page_h - (box.y + box.height) * page_h
        w = box.width * page_w
        h = box.height * page_h
        if w <= 0 or h <= 0:
            continue
        font_size = max(h * 0.8, 4)
        c.setFont(font_name, font_size)
        text = box.text.strip()
        if text:
            c.drawString(x, y + h * 0.1, text)


# ── Phase 1: 证据 PDF 排版系统 ─────────────────────────────────

A4_WIDTH, A4_HEIGHT = A4  # 595.27 x 841.89 pt
DEFAULT_MARGIN = 20
DEFAULT_GAP = 10

# 支持的布局配置
LAYOUTS = {
    "1x1":  (1, 1),
    "1x2":  (1, 2),
    "2x2":  (2, 2),
    "2x3":  (2, 3),
}


def _layout_cell(index: int, cols: int, rows: int, direction: str = "lr") -> tuple:
    """
    返回第 index 张图在页面中的 (x, y, w, h)。
    direction: "lr" = 左右优先（先行后列）, "tb" = 上下优先（先列后行）
    """
    per_page = cols * rows
    pos = index % per_page
    if direction == "tb":
        col = pos // rows
        row = pos % rows
    else:
        row = pos // cols
        col = pos % cols

    cell_w = (A4_WIDTH - 2 * DEFAULT_MARGIN - DEFAULT_GAP * (cols - 1)) / cols
    cell_h = (A4_HEIGHT - 2 * DEFAULT_MARGIN - DEFAULT_GAP * (rows - 1)) / rows

    x = DEFAULT_MARGIN + col * (cell_w + DEFAULT_GAP)
    y = A4_HEIGHT - DEFAULT_MARGIN - (row + 1) * cell_h - row * DEFAULT_GAP
    return (x, y, cell_w, cell_h)


def _prepare_image_for_cell(img_path: Path, cell_w: float, cell_h: float,
                            scale_mode: str) -> Path:
    """按缩放模式处理图片，返回路径。fit=保留比例，fill=裁剪填充。"""
    if scale_mode == "fit":
        return img_path
    img = Image.open(img_path)
    img_w, img_h = img.size
    img_ratio = img_w / img_h
    cell_ratio = cell_w / cell_h
    if img_ratio > cell_ratio:
        new_h = img_h
        new_w = int(new_h * cell_ratio)
    else:
        new_w = img_w
        new_h = int(new_w / cell_ratio)
    left = (img_w - new_w) // 2
    top = (img_h - new_h) // 2
    cropped = img.crop((left, top, left + new_w, top + new_h))
    tmp = img_path.parent / f"._grid_tmp_{img_path.stem}.jpg"
    cropped.convert("RGB").save(str(tmp), format="JPEG", quality=85)
    return tmp


def _draw_number(c, x: float, y: float, cell_w: float, cell_h: float,
                 number: int) -> None:
    """在单元格右上角绘制编号（白字灰底圆角标签）。"""
    label = str(number)
    font_size = min(cell_w * 0.08, 14)
    c.setFont("Helvetica-Bold", font_size)
    text_w = c.stringWidth(label, "Helvetica-Bold", font_size)
    padding = 4
    bw = text_w + padding * 2
    bh = font_size + padding * 1.5
    bx = x + cell_w - bw - 4
    by = y + cell_h - bh - 4
    c.setFillColor(Color(0.2, 0.2, 0.2, alpha=0.75))
    c.roundRect(bx, by, bw, bh, 3, fill=1, stroke=0)
    c.setFillColor(Color(1, 1, 1))
    c.drawString(bx + padding, by + padding, label)


def _draw_page_number(c, page_num: int, total_pages: int) -> None:
    """在页面底部居中绘制页码。"""
    font_size = 9
    c.setFont("Helvetica", font_size)
    text = f"第 {page_num} 页 / 共 {total_pages} 页"
    text_w = c.stringWidth(text, "Helvetica", font_size)
    x = (A4_WIDTH - text_w) / 2
    y = 12
    c.setFillColor(Color(0.5, 0.5, 0.5))
    c.drawString(x, y, text)


def build_grid_pdf(
    image_paths: list[Path],
    output_path: Path,
    scale_mode: str = "fit",
    layout: str = "2x2",
    direction: str = "lr",
    title: str = "",
    show_number: bool = True,
    show_page_number: bool = False,
) -> Path:
    """
    生成证据 PDF 排版。

    Args:
        image_paths: 图片路径列表。
        output_path: 输出 PDF 路径。
        scale_mode: "fit" 或 "fill"。
        layout: "1x1", "1x2", "2x2", "2x3"。
        direction: "lr" 左右优先, "tb" 上下优先。
        title: PDF 标题（空则用 output_path.stem）。
        show_number: 是否显示截图编号。
        show_page_number: 是否显示页码。
    """
    if not image_paths:
        raise ValueError("image_paths cannot be empty")
    if scale_mode not in ("fit", "fill"):
        raise ValueError("scale_mode must be 'fit' or 'fill'")
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {list(LAYOUTS.keys())}")
    if direction not in ("lr", "tb"):
        raise ValueError("direction must be 'lr' or 'tb'")

    cols, rows = LAYOUTS[layout]
    per_page = cols * rows
    total_pages = (len(image_paths) + per_page - 1) // per_page

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf_title = title.strip() or output_path.stem
    c = canvas.Canvas(str(output_path), pagesize=A4)
    c.setTitle(pdf_title)

    temp_files = []
    try:
        for idx, img_path in enumerate(image_paths):
            pos = idx % per_page
            if pos == 0:
                if idx > 0:
                    c.showPage()
                c.setPageSize(A4)

            cell_x, cell_y, cell_w, cell_h = _layout_cell(idx, cols, rows, direction)

            draw_path = _prepare_image_for_cell(img_path, cell_w, cell_h, scale_mode)
            if draw_path != img_path:
                temp_files.append(draw_path)

            preserve = scale_mode == "fit"
            c.drawImage(str(draw_path), cell_x, cell_y,
                        width=cell_w, height=cell_h,
                        preserveAspectRatio=preserve, anchor='c')

            if show_number:
                _draw_number(c, cell_x, cell_y, cell_w, cell_h, idx + 1)

        c.showPage()

        # 绘制页码（每页单独绘制）
        if show_page_number and total_pages > 0:
            for page_i in range(total_pages):
                c.setPageSize(A4)
                # 页码在最后一轮绘制，需要重新遍历
                pass

        c.save()

        # 如果显示页码，需要重新写入每页
        if show_page_number and total_pages > 0:
            # 用 pikepdf 重写每页添加页码
            _add_page_numbers(str(output_path), total_pages)

    finally:
        for f in temp_files:
            try:
                f.unlink()
            except OSError:
                pass

    logger.info("PDF: %s (%.2f MB, %d pages, %d images, %s %s)",
                output_path.name,
                output_path.stat().st_size / 1024 / 1024,
                total_pages, len(image_paths), layout, scale_mode)
    return output_path


def _add_page_numbers(pdf_path: str, total_pages: int) -> None:
    """用 pikepdf 在每页底部添加页码。"""
    try:
        import pikepdf
    except ImportError:
        logger.warning("pikepdf not available, page numbers not added")
        return
    try:
        from reportlab.pdfgen import canvas as rl_canvas
        import io

        pdf = pikepdf.open(pdf_path)
        # 为每页叠加页码
        for page_num in range(len(pdf.pages)):
            packet = io.BytesIO()
            c = rl_canvas.Canvas(packet, pagesize=A4)
            c.setFont("Helvetica", 9)
            text = f"第 {page_num + 1} 页 / 共 {total_pages} 页"
            text_w = c.stringWidth(text, "Helvetica", 9)
            x = (A4_WIDTH - text_w) / 2
            y = 12
            c.setFillColor(Color(0.5, 0.5, 0.5))
            c.drawString(x, y, text)
            c.save()
            packet.seek(0)
            # 合并页码水印
            overlay = pikepdf.open(packet)
            page = pdf.pages[page_num]
            page.contents_add(overlay.pages[0].contents, prepend=False)
        pdf.save(pdf_path)
        pdf.close()
    except Exception as e:
        logger.warning("Failed to add page numbers: %s", e)


# ── Phase 6: 证据增强 ───────────────────────────────────────

def _sha256(file_path: Path) -> str:
    """计算文件的 SHA256 哈希值。"""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_cover_page(
    output_path: Path,
    title: str = "聊天记录证据",
    source_files: list[Path] = None,
    params: dict = None,
) -> Path:
    """
    生成证据封面页。
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.colors import Color

    c = rl_canvas.Canvas(str(output_path), pagesize=A4)
    w, h = A4

    # 标题
    c.setFont("Helvetica-Bold", 24)
    c.setFillColor(Color(0.1, 0.1, 0.1))
    c.drawCentredString(w / 2, h - 100, title)

    # 时间
    c.setFont("Helvetica", 12)
    c.setFillColor(Color(0.3, 0.3, 0.3))
    c.drawCentredString(w / 2, h - 140, f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # 文件信息
    if source_files:
        c.drawString(60, h - 200, f"源文件数: {len(source_files)}")
        y = h - 220
        for sf in source_files[:20]:
            c.setFont("Helvetica", 9)
            c.drawString(60, y, f"  {sf.name}")
            y -= 16
        if len(source_files) > 20:
            c.drawString(60, y, f"  ... 等 {len(source_files)} 个文件")

    # 参数信息
    if params:
        y = h - 200 if not source_files else y - 30
        c.setFont("Helvetica", 9)
        c.drawString(60, y, "生成参数:")
        y -= 16
        for k, v in params.items():
            c.drawString(80, y, f"{k}: {v}")
            y -= 14

    # 哈希
    if source_files and len(source_files) <= 10:
        y = max(y - 30, 80)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(60, y, "文件哈希 (SHA256):")
        y -= 16
        c.setFont("Helvetica", 8)
        for sf in source_files:
            try:
                hsh = _sha256(sf)
                c.drawString(60, y, f"{sf.name}: {hsh[:32]}...")
                y -= 14
            except Exception:
                pass

    c.save()
    return output_path


def build_evidence_pdf(
    image_paths: list[Path],
    output_path: Path,
    scale_mode: str = "fit",
    layout: str = "2x2",
    direction: str = "lr",
    title: str = "",
    show_number: bool = True,
    show_page_number: bool = False,
    enable_cover: bool = False,
    watermark: str = "",
    source_files: list[Path] = None,
) -> Path:
    """
    生成带证据增强的 PDF。
    在 build_grid_pdf 基础上可选添加封面、水印。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 如果有封面，先生成封面
    if enable_cover:
        cover_path = output_path.parent / f"._cover_{output_path.stem}.pdf"
        params = {"layout": layout, "scale": scale_mode, "direction": direction}
        build_cover_page(cover_path, title=title or output_path.stem,
                         source_files=source_files or image_paths, params=params)

    # 生成主 PDF
    main_path = output_path.parent / f"._main_{output_path.stem}.pdf"
    build_grid_pdf(
        image_paths, main_path,
        scale_mode=scale_mode,
        layout=layout,
        direction=direction,
        title=title,
        show_number=show_number,
        show_page_number=show_page_number,
    )

    # 合并封面和主 PDF
    if enable_cover:
        try:
            import pikepdf
            cover_pdf = pikepdf.open(str(cover_path))
            main_pdf = pikepdf.open(str(main_path))
            combined = pikepdf.Pdf.new()
            combined.pages.extend(cover_pdf.pages)
            combined.pages.extend(main_pdf.pages)
            combined.save(str(output_path))
            combined.close()
            cover_pdf.close()
            main_pdf.close()
            cover_path.unlink()
            main_path.unlink()
        except Exception as e:
            logger.warning("Cover merge failed, using main PDF only: %s", e)
            main_path.rename(output_path)
    else:
        main_path.rename(output_path)

    # 可选水印（简化：在每页叠加文字）
    if watermark:
        try:
            import pikepdf
            pdf = pikepdf.open(str(output_path))
            from reportlab.pdfgen import canvas as rl_canvas
            for page_num in range(len(pdf.pages)):
                packet = io.BytesIO()
                c = rl_canvas.Canvas(packet, pagesize=A4)
                c.setFont("Helvetica", 40)
                from reportlab.lib.colors import Color
                c.setFillColor(Color(0.5, 0.5, 0.5, alpha=0.15))
                c.saveState()
                c.translate(A4_WIDTH / 2, A4_HEIGHT / 2)
                c.rotate(45)
                c.drawCentredString(0, 0, watermark)
                c.restoreState()
                c.save()
                packet.seek(0)
                overlay = pikepdf.open(packet)
                page = pdf.pages[page_num]
                page.contents_add(overlay.pages[0].contents, prepend=False)
            pdf.save(str(output_path))
            pdf.close()
        except Exception as e:
            logger.warning("Watermark failed: %s", e)

    logger.info("Evidence PDF: %s (%.2f MB)", output_path.name,
                output_path.stat().st_size / 1024 / 1024)
    return output_path

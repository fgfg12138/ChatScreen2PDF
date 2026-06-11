"""
core/ocr_service.py — OCR 服务模块。

PaddleOCR 作为可选依赖，未安装时自动降级。
所有函数在无 OCR 环境下仍可安全调用。
"""

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────

OCR_OVERLAP_HIGH = 0.85       # 高度重复阈值
OCR_OVERLAP_LOW = 0.25        # 断层警告阈值
OCR_MIN_LINES_FOR_WARNING = 2  # 至少多少行才判断为断层
OCR_MIN_NEW_LINES = 2         # 新增行数达到此值优先保留
OCR_MIN_REGION_SIZE = 20      # OCR 区域最小宽高

_ocr_engine = None


# ── 引擎管理 ────────────────────────────────────────────────

def is_ocr_available() -> bool:
    """检查 PaddleOCR 是否可用。"""
    try:
        import paddleocr  # noqa: F401
        return True
    except ImportError:
        return False


def _get_ocr_engine(lang: str = "ch"):
    """懒加载 PaddleOCR 引擎。"""
    global _ocr_engine
    if _ocr_engine is not None:
        return _ocr_engine
    if not is_ocr_available():
        return None
    try:
        from paddleocr import PaddleOCR
        _ocr_engine = PaddleOCR(lang=lang, use_angle_cls=False, show_log=False)
        logger.info("PaddleOCR 引擎已初始化 (lang=%s)", lang)
        return _ocr_engine
    except Exception as e:
        logger.warning("PaddleOCR 初始化失败: %s", e)
        return None


# ── 图片识别 ────────────────────────────────────────────────

def recognize_image(image_path: Path, region: Optional[dict] = None) -> list[str]:
    """
    对图片执行 OCR，返回文本行列表。
    region: {"x": int, "y": int, "width": int, "height": int} 或 None（全图）
    """
    engine = _get_ocr_engine()
    if engine is None:
        return []

    try:
        # 如果有 region 且图像可读，先裁剪
        from PIL import Image
        img = Image.open(image_path)
        if region:
            x = int(region.get("x", 0))
            y = int(region.get("y", 0))
            w = int(region.get("width", img.width))
            h = int(region.get("height", img.height))
            x = max(0, min(x, img.width - 1))
            y = max(0, min(y, img.height - 1))
            w = min(w, img.width - x)
            h = min(h, img.height - y)
            if w > 0 and h > 0:
                img = img.crop((x, y, x + w, y + h))

        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "ocr_tmp.jpg"
        img.convert("RGB").save(str(tmp), format="JPEG", quality=95)

        result = engine.ocr(str(tmp), cls=False)
        lines = []
        if result and result[0]:
            for line in result[0]:
                text = line[1][0] if len(line) > 1 else ""
                if text and text.strip():
                    lines.append(text.strip())
        try:
            tmp.unlink()
        except OSError:
            pass
        return lines

    except Exception as e:
        logger.debug("OCR 识别失败: %s", e)
        return []


# ── 文本清洗 ────────────────────────────────────────────────

def clean_ocr_lines(lines: list[str], exclude_words: Optional[list] = None) -> list[str]:
    """
    清洗 OCR 文本行。

    Args:
        lines: 原始文本行列表。
        exclude_words: 排除词白名单，包含任意词的文本行将被过滤。

    Returns:
        清洗后的文本行列表。
    """
    cleaned = []
    exclude_words = [w.strip() for w in (exclude_words or []) if w.strip()]

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 去除纯数字/符号行
        if re.match(r'^[\d\s\W]+$', line):
            continue
        # 排除词过滤
        if exclude_words and any(w in line for w in exclude_words):
            continue
        if line not in cleaned:
            cleaned.append(line)

    return cleaned


# ── 文本重叠度 ──────────────────────────────────────────────

def compute_text_overlap(prev_lines: list[str], curr_lines: list[str]) -> float:
    """
    计算两帧文本行之间的重叠度 (Jaccard 相似度)。

    Returns: 0.0 ~ 1.0
    """
    if not prev_lines or not curr_lines:
        return 0.0
    set_prev = set(prev_lines)
    set_curr = set(curr_lines)
    intersection = set_prev & set_curr
    union = set_prev | set_curr
    return len(intersection) / len(union)


# ── 帧分类 ──────────────────────────────────────────────────

def classify_frame_by_ocr(
    prev_lines: Optional[list[str]],
    curr_lines: list[str],
    exclude_words: Optional[list] = None,
    ocr_available: bool = True,
) -> dict:
    """
    根据 OCR 文本连续性判断当前帧是否保留。

    Returns:
        {
            "status": "kept" | "skipped_duplicate" | "kept_warning" | "ocr_failed" | "image_dedup_only",
            "reason": str,
            "warning": str | None,
            "ocr_text_count": int,
            "ocr_text_preview": list[str],
        }
    """
    result = {
        "status": "image_dedup_only",
        "reason": "",
        "warning": None,
        "ocr_text_count": 0,
        "ocr_text_preview": [],
    }

    if not ocr_available:
        result["reason"] = "OCR 未启用，使用图像去重"
        return result

    if not curr_lines:
        result["status"] = "ocr_failed"
        result["reason"] = "OCR 未识别到文本，降级为图像去重"
        return result

    # 清洗
    cleaned_curr = clean_ocr_lines(curr_lines, exclude_words)
    result["ocr_text_count"] = len(cleaned_curr)
    result["ocr_text_preview"] = cleaned_curr[:5]

    if not cleaned_curr:
        result["status"] = "ocr_failed"
        result["reason"] = "OCR 文本为空（可能被排除词过滤），降级为图像去重"
        return result

    # 新增行数
    if prev_lines is None:
        result["status"] = "kept"
        result["reason"] = f"保留：首帧，检测到 {len(cleaned_curr)} 行文本"
        return result

    cleaned_prev = clean_ocr_lines(prev_lines, exclude_words)
    if not cleaned_prev:
        result["status"] = "kept"
        result["reason"] = f"保留：上一帧无文本，当前帧有 {len(cleaned_curr)} 行"
        return result

    overlap = compute_text_overlap(cleaned_prev, cleaned_curr)
    new_lines = [l for l in cleaned_curr if l not in set(cleaned_prev)]

    if overlap >= OCR_OVERLAP_HIGH:
        result["status"] = "skipped_duplicate"
        result["reason"] = f"跳过：文本高度重复 (overlap={overlap:.2f})"
    elif len(new_lines) >= OCR_MIN_NEW_LINES:
        result["status"] = "kept"
        result["reason"] = f"保留：检测到 {len(new_lines)} 行新增聊天内容"
    elif OCR_OVERLAP_LOW <= overlap < OCR_OVERLAP_HIGH:
        result["status"] = "kept"
        result["reason"] = f"保留：正常连续 (overlap={overlap:.2f})"
    else:
        # overlap < OCR_OVERLAP_LOW
        if len(cleaned_curr) >= OCR_MIN_LINES_FOR_WARNING:
            result["status"] = "kept_warning"
            result["reason"] = f"保留：疑似内容断层 (overlap={overlap:.2f})"
            result["warning"] = f"当前帧与上一帧内容差异较大，请人工确认"
        else:
            result["status"] = "skipped_duplicate"
            result["reason"] = f"跳过：内容过少且不连续 (overlap={overlap:.2f})"

    return result


# ── OCR 区域校验 ────────────────────────────────────────────

def validate_ocr_region(region: Optional[dict], image_width: int, image_height: int) -> dict:
    """
    校验并修正 OCR 区域坐标。
    Returns: {"valid": bool, "region": dict, "warning": str | None, "error": str | None}
    """
    if not region:
        return {"valid": True, "region": None, "warning": None, "error": None}

    x = int(region.get("x", 0))
    y = int(region.get("y", 0))
    w = int(region.get("width", 0))
    h = int(region.get("height", 0))

    if w < OCR_MIN_REGION_SIZE or h < OCR_MIN_REGION_SIZE:
        return {"valid": False, "region": None, "warning": None,
                "error": f"区域太小，宽高至少 {OCR_MIN_REGION_SIZE}px"}

    warnings = []
    if x < 0:
        warnings.append(f"x({x}) 已修正为 0")
        x = 0
    if y < 0:
        warnings.append(f"y({y}) 已修正为 0")
        y = 0
    if x + w > image_width:
        w = image_width - x
        warnings.append(f"宽度已修正为 {w}")
    if y + h > image_height:
        h = image_height - y
        warnings.append(f"高度已修正为 {h}")
    if w < OCR_MIN_REGION_SIZE or h < OCR_MIN_REGION_SIZE:
        return {"valid": False, "region": None, "warning": None,
                "error": "修正后区域仍然太小"}

    return {
        "valid": True,
        "region": {"x": x, "y": y, "width": w, "height": h},
        "warning": "; ".join(warnings) if warnings else None,
        "error": None,
    }

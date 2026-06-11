"""
ocr_assist.py — OCR 辅助筛选（Phase 5）。
仅作为辅助，不作为文本导出。OCR 失败可降级为图像筛选。

注意：需要安装 PaddleOCR 和 PaddlePaddle 才能使用。
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def is_available() -> bool:
    """检查 OCR 引擎是否可用。"""
    try:
        import paddleocr  # noqa: F401
        return True
    except ImportError:
        return False


def get_ocr_text(image_path: Path, region=None) -> str:
    """
    对指定区域进行 OCR 识别。
    region: (x1, y1, x2, y2) 归一化坐标 0~1，None 表示整张图片。
    Returns: 识别文本（为空表示无文本或 OCR 不可用）。
    """
    if not is_available():
        return ""
    try:
        from core.ocr import get_ocr_engine
        engine = get_ocr_engine()
        result = engine.recognize(image_path)
        return result.text
    except Exception as e:
        logger.debug("OCR failed: %s", e)
        return ""

"""
ocr_engine.py - PaddleOCR engine implementation.
"""

from __future__ import annotations
import logging
from pathlib import Path
from PIL import Image

from core.ocr import OCREngine, OCRResult, TextBox

logger = logging.getLogger(__name__)

_LANG_MAP = {
    "zh": "ch",
    "en": "en",
    "ja": "japan",
    "auto": "ch",
}


class PaddleOCREngine(OCREngine):

    def __init__(self, lang: str = "auto"):
        from paddleocr import PaddleOCR
        paddle_lang = _LANG_MAP.get(lang, "ch")
        logger.info("Initializing PaddleOCR (lang=%s)...", paddle_lang)
        self._ocr = PaddleOCR(lang=paddle_lang)
        self._lang = lang
        logger.info("PaddleOCR ready.")

    def recognize(self, image_path: Path) -> OCRResult:
        # Try multiple API styles for compatibility
        result = None
        for method, kwargs in [
            ("ocr", {"cls": True}),
            ("ocr", {}),
            ("predict", {}),
        ]:
            try:
                fn = getattr(self._ocr, method)
                result = fn(str(image_path), **kwargs)
                break
            except TypeError:
                continue

        if result is None:
            return OCRResult(text="", boxes=[])

        # Handle different result formats
        # Format 1: [[line, line, ...]]  (nested list)
        # Format 2: [line, line, ...]    (flat list)
        if result and isinstance(result[0], list) and result[0] and isinstance(result[0][0], list):
            lines = result[0]
        elif result and isinstance(result[0], (list, tuple)):
            lines = result
        else:
            return OCRResult(text="", boxes=[])

        if not lines:
            return OCRResult(text="", boxes=[])

        with Image.open(image_path) as img:
            img_w, img_h = img.size

        texts = []
        boxes = []
        for line in lines:
            if not line or len(line) < 2:
                continue
            coords = line[0]
            text_info = line[1]
            if isinstance(text_info, (list, tuple)):
                text = str(text_info[0])
                conf = float(text_info[1])
            else:
                text = str(text_info)
                conf = 1.0

            if conf < 0.5:
                continue
            texts.append(text)
            xs = [p[0] for p in coords]
            ys = [p[1] for p in coords]
            boxes.append(TextBox(
                text=text,
                x=min(xs) / img_w,
                y=min(ys) / img_h,
                width=(max(xs) - min(xs)) / img_w,
                height=(max(ys) - min(ys)) / img_h,
            ))

        return OCRResult(text="\n".join(texts), boxes=boxes)

    def get_supported_languages(self) -> list[str]:
        return ["zh", "en", "ja"]

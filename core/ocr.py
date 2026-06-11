"""
ocr.py - OCR engine interface and data classes.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TextBox:
    """A recognized text region with normalized coordinates (0~1)."""
    text: str
    x: float
    y: float
    width: float
    height: float


@dataclass
class OCRResult:
    """Result of OCR on a single image."""
    text: str
    boxes: list[TextBox] = field(default_factory=list)


class OCREngine(ABC):
    """Abstract base class for OCR engines."""

    @abstractmethod
    def recognize(self, image_path: Path) -> OCRResult:
        ...

    @abstractmethod
    def get_supported_languages(self) -> list[str]:
        ...


class OCREngineNotAvailableError(RuntimeError):
    """Raised when --ocr is enabled but no real OCR engine is installed."""
    pass


def get_ocr_engine(lang: str = "auto") -> OCREngine:
    """
    Factory: return a real OCR engine for the given language.
    Raises OCREngineNotAvailableError if no engine is installed.
    No silent fallback - if user asks for OCR, they must get real OCR.
    """
    errors = []

    # Try PaddleOCR
    try:
        from core.ocr_engine import PaddleOCREngine
        return PaddleOCREngine(lang=lang)
    except ImportError as e:
        errors.append("PaddleOCR not installed: " + str(e))
    except Exception as e:
        errors.append("PaddleOCR init failed: " + str(e))

    # No engine available - hard error
    raise OCREngineNotAvailableError(
        "No OCR engine available. Install one of:\n"
        "  pip install paddleocr paddlepaddle\n"
        "Errors: " + "; ".join(errors)
    )

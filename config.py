from __version__ import __version__
from pathlib import Path

DEFAULT_FPS = 1.0
DEFAULT_DEDUP = True
DEFAULT_DEDUP_MODE = "consecutive"
DEFAULT_DEDUP_THRESHOLD = 10
DEFAULT_PDF_MODE = "compressed"
DEFAULT_MAX_LONG_EDGE = 1920
DEFAULT_JPEG_QUALITY = 80
DEFAULT_OCR = False
DEFAULT_OCR_LANG = "auto"
DEFAULT_OVERWRITE = "auto_rename"
DEFAULT_LOG_DIR = str(Path(__file__).resolve().parent / "logs")
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

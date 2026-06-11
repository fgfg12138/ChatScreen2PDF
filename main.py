"""
main.py - CLI entry for ChatScreen2PDF.
"""

import argparse
import logging
import sys
from pathlib import Path

from __version__ import __version__
from config import (
    DEFAULT_FPS, DEFAULT_DEDUP, DEFAULT_DEDUP_MODE, DEFAULT_DEDUP_THRESHOLD,
    DEFAULT_PDF_MODE, DEFAULT_OCR, DEFAULT_OCR_LANG, DEFAULT_OVERWRITE,
)


def _parse_crop_ratio(value: str) -> tuple:
    """Parse and validate --crop-ratio x1,y1,x2,y2."""
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "--crop-ratio requires exactly 4 values: x1,y1,x2,y2"
        )
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        raise argparse.ArgumentTypeError("--crop-ratio values must be numbers")
    x1, y1, x2, y2 = vals
    for name, v in [("x1", x1), ("y1", y1), ("x2", x2), ("y2", y2)]:
        if v < 0.0 or v > 1.0:
            raise argparse.ArgumentTypeError(
                name + " must be 0.0-1.0, got " + str(v)
            )
    if x1 >= x2:
        raise argparse.ArgumentTypeError("x1 must be < x2, got " + str(x1) + ">=" + str(x2))
    if y1 >= y2:
        raise argparse.ArgumentTypeError("y1 must be < y2, got " + str(y1) + ">=" + str(y2))
    return (x1, y1, x2, y2)


def _parse_crop_pixels(value: str) -> tuple:
    """Parse and validate --crop-pixels left:top:width:height."""
    parts = value.split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "--crop-pixels requires exactly 4 values: left:top:width:height"
        )
    try:
        vals = [int(p) for p in parts]
    except ValueError:
        raise argparse.ArgumentTypeError("--crop-pixels values must be integers")
    left, top, width, height = vals
    if left < 0:
        raise argparse.ArgumentTypeError("left must be >= 0, got " + str(left))
    if top < 0:
        raise argparse.ArgumentTypeError("top must be >= 0, got " + str(top))
    if width <= 0:
        raise argparse.ArgumentTypeError("width must be > 0, got " + str(width))
    if height <= 0:
        raise argparse.ArgumentTypeError("height must be > 0, got " + str(height))
    return (left, top, width, height)


def parse_args():
    p = argparse.ArgumentParser(
        description="ChatScreen2PDF v" + __version__,
    )
    p.add_argument("--version", action="version", version="ChatScreen2PDF " + __version__)
    p.add_argument("--input", required=True, help="Input video directory")
    p.add_argument("--output", required=True, help="Output PDF directory")
    p.add_argument("--fps", type=float, default=DEFAULT_FPS)
    p.add_argument("--ocr", type=str, default=str(DEFAULT_OCR).lower(), choices=["true", "false"],
                    help="OCR is experimental and not recommended for normal use.")
    p.add_argument("--ocr-lang", default=DEFAULT_OCR_LANG, choices=["zh", "en", "ja", "auto"])
    p.add_argument("--dedup", type=str, default=str(DEFAULT_DEDUP).lower(), choices=["true", "false"])
    p.add_argument("--dedup-mode", default=DEFAULT_DEDUP_MODE, choices=["consecutive", "global"])
    p.add_argument("--dedup-threshold", type=int, default=DEFAULT_DEDUP_THRESHOLD)
    p.add_argument("--pdf-mode", default=DEFAULT_PDF_MODE, choices=["lossless", "compressed"])
    p.add_argument("--overwrite", default=DEFAULT_OVERWRITE,
                    choices=["auto_rename", "overwrite", "skip"],
                    help="Output conflict strategy: auto_rename (default, adds _1/_2/...), overwrite, or skip")
    p.add_argument("--ffmpeg-path", default=None, help="Custom FFmpeg path")

    crop_group = p.add_mutually_exclusive_group()
    crop_group.add_argument("--crop-ratio", type=_parse_crop_ratio, default=None,
                             help="Crop as x1,y1,x2,y2 (0.0-1.0)")
    crop_group.add_argument("--crop-pixels", type=_parse_crop_pixels, default=None,
                             help="Crop as left:top:width:height (pixels)")
    return p.parse_args()


def main():
    args = parse_args()

    input_dir = Path(args.input)
    if not input_dir.exists():
        print("Error: Input directory does not exist: " + str(input_dir), file=sys.stderr)
        sys.exit(1)
    if not input_dir.is_dir():
        print("Error: Input path is not a directory: " + str(input_dir), file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    from utils.logger import setup_logger
    setup_logger(output_dir)
    logger = logging.getLogger(__name__)

    args.ocr = args.ocr.lower() == "true"
    args.dedup = args.dedup.lower() == "true"

    # Check OCR availability in portable build
    if args.ocr:
        if getattr(sys, 'frozen', False):
            logger.error(
                "OCR is Experimental and not included in Windows portable build. "
                "Please use the Python source version with PaddleOCR installed."
            )
            sys.exit(1)

    logger.info("=" * 60)
    logger.info("ChatScreen2PDF v" + __version__)
    logger.info("=" * 60)
    logger.info("Input:    %s", input_dir.resolve())
    logger.info("Output:   %s", output_dir.resolve())
    logger.info("FPS:      %s", args.fps)
    logger.info("Dedup:    %s (mode=%s, threshold=%d)", args.dedup, args.dedup_mode, args.dedup_threshold)
    logger.info("PDF mode: %s", args.pdf_mode)
    logger.info("Overwrite: %s", args.overwrite)
    if args.crop_ratio:
        logger.info("Crop:     ratio %s", args.crop_ratio)
    elif args.crop_pixels:
        logger.info("Crop:     pixels %s", args.crop_pixels)
    logger.info("OCR:      %s (lang=%s) [Experimental]", args.ocr, args.ocr_lang)
    logger.info("-" * 60)

    try:
        from pipeline import run
        result = run(args)
    except Exception as e:
        logger.error("Fatal: %s", e)
        sys.exit(1)

    logger.info("=" * 60)
    parts = []
    parts.append("RESULT: %d total, %d success" % (result.total, result.success))
    if result.skipped:
        parts.append("%d skipped" % result.skipped)
    parts.append("%d failed (%.1fs)" % (result.failed, result.elapsed))
    logger.info(", ".join(parts))
    logger.info("=" * 60)

    sys.exit(0 if result.failed == 0 else 1)


if __name__ == "__main__":
    main()

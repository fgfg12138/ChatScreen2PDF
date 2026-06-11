"""
extractor.py - FFmpeg wrapper: frame extraction with crop support.
"""

from __future__ import annotations
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class FFmpegNotInstalledError(OSError):
    pass


class FrameExtractionError(RuntimeError):
    pass


def _find_ffmpeg(custom_path: str | None = None) -> str:
    """Find FFmpeg: custom path > built-in > system PATH."""
    # 1. Custom path
    if custom_path:
        p = Path(custom_path)
        if p.exists():
            logger.info("FFmpeg (custom): %s", p)
            return str(p)
        raise FFmpegNotInstalledError("Custom FFmpeg path not found: " + str(p))

    # 2. Built-in (PyInstaller or resources/)
    candidates = []
    if getattr(sys, 'frozen', False):
        # PyInstaller onedir: exe 同级
        candidates.append(Path(sys.executable).parent / "resources" / "ffmpeg" / "ffmpeg.exe")
        # PyInstaller onedir: _internal 下 (--add-data 可能放入 _internal)
        candidates.append(Path(sys.executable).parent / "_internal" / "resources" / "ffmpeg" / "ffmpeg.exe")
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 临时解压目录
        candidates.append(Path(sys._MEIPASS) / "resources" / "ffmpeg" / "ffmpeg.exe")
    # Source tree
    candidates.append(Path(__file__).resolve().parent.parent / "resources" / "ffmpeg" / "ffmpeg.exe")
    for c in candidates:
        if c.exists():
            logger.info("FFmpeg (built-in): %s", c)
            return str(c)

    # 3. System PATH
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            logger.info("FFmpeg (system): ffmpeg")
            return "ffmpeg"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    raise FFmpegNotInstalledError(
        "FFmpeg not found. Options:\n"
        "  1. Place ffmpeg.exe in resources/ffmpeg/\n"
        "  2. Install FFmpeg and add to PATH\n"
        "  3. Use --ffmpeg-path to specify location"
    )


def check_ffmpeg(custom_path: str | None = None) -> str:
    """Check FFmpeg availability and return version string."""
    ffmpeg = _find_ffmpeg(custom_path)
    try:
        result = subprocess.run(
            [ffmpeg, "-version"], capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            raise FFmpegNotInstalledError("FFmpeg execution failed: " + ffmpeg)
        version = result.stdout.split("\n")[0].strip()
        logger.info("FFmpeg version: %s", version)
        return version
    except FileNotFoundError:
        raise FFmpegNotInstalledError("FFmpeg not found: " + ffmpeg) from None


def _build_vf_filter(fps: float, crop_ratio: tuple | None, crop_pixels: tuple | None) -> str:
    """Build FFmpeg -vf filter chain: crop first, then fps."""
    filters = []

    if crop_ratio:
        x1, y1, x2, y2 = crop_ratio
        # crop=iw*(x2-x1):ih*(y2-y1):iw*x1:ih*y1
        filters.append(
            "crop=iw*{w}:ih*{h}:iw*{x}:ih*{y}".format(
                w=x2 - x1, h=y2 - y1, x=x1, y=y1
            )
        )
    elif crop_pixels:
        left, top, width, height = crop_pixels
        filters.append("crop={w}:{h}:{x}:{y}".format(w=width, h=height, x=left, y=top))

    filters.append("fps=" + str(fps))
    return ",".join(filters)


def extract_frames(
    video_path: Path,
    fps: float,
    temp_dir: Path,
    ffmpeg_path: str | None = None,
    crop_ratio: tuple | None = None,
    crop_pixels: tuple | None = None,
) -> list[Path]:
    """
    Extract frames from video using FFmpeg.

    Args:
        video_path: Video file path.
        fps: Frames per second.
        temp_dir: Output directory for frames.
        ffmpeg_path: Optional custom FFmpeg path.
        crop_ratio: Optional (x1, y1, x2, y2) normalized 0.0-1.0.
        crop_pixels: Optional (left, top, width, height) in pixels.

    Returns:
        Sorted list of frame image paths.
    """
    if not video_path.exists():
        raise FileNotFoundError("Video not found: " + str(video_path))

    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = _find_ffmpeg(ffmpeg_path)
    vf = _build_vf_filter(fps, crop_ratio, crop_pixels)
    output_pattern = str(temp_dir / "frame_%06d.jpg")

    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-vf", vf,
        "-qscale:v", "2",
        "-y", output_pattern,
    ]
    logger.debug("FFmpeg cmd: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3600,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise FrameExtractionError("FFmpeg timeout (>1h): " + video_path.name) from None

    if result.returncode != 0:
        raise FrameExtractionError(
            "FFmpeg failed: " + video_path.name + "\n" + result.stderr.strip()
        )

    frames = sorted(temp_dir.glob("frame_*.jpg"))
    if not frames:
        raise FrameExtractionError(
            "No frames produced. Video may be corrupt: " + video_path.name
        )

    logger.info("Extracted %d frames from %s (fps=%.2f)", len(frames), video_path.name, fps)
    return frames

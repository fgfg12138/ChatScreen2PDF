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
    """Find FFmpeg: custom path > portable tools folder > legacy resources > PATH."""
    # 1. Custom path
    if custom_path:
        p = Path(custom_path)
        if p.exists():
            logger.info("FFmpeg (custom): %s", p)
            return str(p)
        raise FFmpegNotInstalledError("Custom FFmpeg path not found: " + str(p))

    # 2. Portable locations. Official release packages do not include FFmpeg,
    # but users may place ffmpeg.exe in tools/ffmpeg/ manually.
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(Path(sys.executable).parent / "tools" / "ffmpeg" / "ffmpeg.exe")
        candidates.append(Path(sys.executable).parent / "resources" / "ffmpeg" / "ffmpeg.exe")
        candidates.append(Path(sys.executable).parent / "_internal" / "tools" / "ffmpeg" / "ffmpeg.exe")
        candidates.append(Path(sys.executable).parent / "_internal" / "resources" / "ffmpeg" / "ffmpeg.exe")
    if hasattr(sys, '_MEIPASS'):
        candidates.append(Path(sys._MEIPASS) / "tools" / "ffmpeg" / "ffmpeg.exe")
        candidates.append(Path(sys._MEIPASS) / "resources" / "ffmpeg" / "ffmpeg.exe")
    candidates.append(Path(__file__).resolve().parent.parent / "tools" / "ffmpeg" / "ffmpeg.exe")
    candidates.append(Path(__file__).resolve().parent.parent / "resources" / "ffmpeg" / "ffmpeg.exe")
    for c in candidates:
        if c.exists():
            logger.info("FFmpeg (portable): %s", c)
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
        "FFmpeg not found. Video processing requires FFmpeg.\n"
        "Options:\n"
        "  1. Run the included FFmpeg helper installer package.\n"
        "  2. Install FFmpeg from https://ffmpeg.org/ and make it available in PATH.\n"
        "  3. Place ffmpeg.exe in tools/ffmpeg/ next to the application.\n"
        "  4. Use --ffmpeg-path to specify a custom location."
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


def _build_crop_filter(crop_ratio: tuple | None, crop_pixels: tuple | None) -> str:
    """Build the optional FFmpeg crop filter."""
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

    return ",".join(filters)


def _build_vf_filter(fps: float, crop_ratio: tuple | None, crop_pixels: tuple | None) -> str:
    """Build FFmpeg -vf filter chain: crop first, then fps."""
    filters = []
    crop_filter = _build_crop_filter(crop_ratio, crop_pixels)
    if crop_filter:
        filters.append(crop_filter)

    interval = 1.0 / fps
    filters.append("select='eq(n\\,0)+gte(t\\,prev_selected_t+{interval})'".format(interval=interval))
    filters.append("setpts=N/FRAME_RATE/TB")
    return ",".join(filters)


def _extract_tail_frame(
    ffmpeg: str,
    video_path: Path,
    temp_dir: Path,
    crop_ratio: tuple | None,
    crop_pixels: tuple | None,
) -> None:
    """Force an extra frame from the end of the video when FFmpeg supports it."""
    tail_path = temp_dir / "frame_999999.jpg"
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-sseof", "-0.1",
        "-i", str(video_path),
        "-frames:v", "1",
        "-qscale:v", "2",
        "-y",
    ]
    crop_filter = _build_crop_filter(crop_ratio, crop_pixels)
    if crop_filter:
        cmd += ["-vf", crop_filter]
    cmd.append(str(tail_path))

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0 or not tail_path.exists():
            logger.info("Tail frame extraction skipped: %s", result.stderr.strip())
    except Exception as exc:
        logger.info("Tail frame extraction skipped: %s", exc)


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

    _extract_tail_frame(ffmpeg, video_path, temp_dir, crop_ratio, crop_pixels)

    frames = sorted(temp_dir.glob("frame_*.jpg"))
    if not frames:
        raise FrameExtractionError(
            "No frames produced. Video may be corrupt: " + video_path.name
        )

    logger.info("Extracted %d frames from %s (fps=%.2f)", len(frames), video_path.name, fps)
    return frames

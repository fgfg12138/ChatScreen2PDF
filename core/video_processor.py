"""
video_processor.py — 视频处理：抽帧、模糊检测、去重。
复用 core/extractor.py（抽帧）和 core/dedup.py（aHash 去重）。
"""

import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 0.5  # 默认抽帧间隔（秒）
BLUR_THRESHOLD = 30.0  # Laplacian 方差阈值，低于此值视为模糊


def detect_blur(image_path: Path) -> float:
    """
    检测图片模糊程度（Laplacian 方差）。
    返回值：方差值，越大越清晰。
    """
    img = Image.open(image_path).convert("L")
    # 标准 3x3 Laplacian 核（2D 卷积，不是 1D 拉平）
    laplacian_kernel = ImageFilter.Kernel(
        (3, 3), [-1, -1, -1, -1, 8, -1, -1, -1, -1], scale=1, offset=0
    )
    lap = img.filter(laplacian_kernel)
    arr = np.array(lap, dtype=np.float64)
    return float(arr.var())

def filter_frames(
    frame_paths: list[Path],
    blur_threshold: float = BLUR_THRESHOLD,
    dedup_threshold: int = 10,
    global_dedup: bool = False,
) -> list[Path]:
    """
    综合筛选：模糊过滤 + 相似度去重。

    Args:
        frame_paths: 帧图片路径列表。
        blur_threshold: 模糊阈值（低于此值丢弃）。
        dedup_threshold: 去重汉明距离阈值。
        global_dedup: 是否全局去重（否则仅连续帧去重）。

    Returns:
        保留的帧路径列表。
    """
    if not frame_paths:
        return []

    logger.info("Filtering %d frames (blur=%s, dedup=%d, global=%s)",
                len(frame_paths), blur_threshold, dedup_threshold, global_dedup)

    # 1. 模糊过滤
    kept = []
    blur_dropped = 0
    for p in frame_paths:
        try:
            variance = detect_blur(p)
            if variance < blur_threshold:
                blur_dropped += 1
                logger.debug("Blur drop: %s (var=%.1f)", p.name, variance)
                continue
            kept.append(p)
        except Exception as e:
            logger.warning("Blur check failed for %s: %s", p.name, e)
            kept.append(p)  # 保留不确定的帧

    logger.info("Blur filter: %d → %d (dropped %d blurry)",
                len(frame_paths), len(kept), blur_dropped)

    # 2. 去重
    from core.dedup import dedup_frames
    kept = dedup_frames(kept, dedup_threshold, "global" if global_dedup else "consecutive")

    logger.info("Final: %d frames kept", len(kept))
    return kept


def extract_video_frames(
    video_path: Path,
    output_dir: Path,
    interval: float = DEFAULT_INTERVAL,
    ffmpeg_path: str | None = None,
) -> list[Path]:
    """
    从视频中提取帧。内部使用 core/extractor 的 FFmpeg 逻辑。

    Returns:
        排序后的帧路径列表。
    """
    fps = 1.0 / interval
    from core.extractor import extract_frames
    frames = extract_frames(
        video_path=video_path,
        fps=fps,
        temp_dir=output_dir,
        ffmpeg_path=ffmpeg_path,
    )
    logger.info("Extracted %d frames from %s (interval=%.1fs, fps=%.2f)",
                len(frames), video_path.name, interval, fps)
    return frames

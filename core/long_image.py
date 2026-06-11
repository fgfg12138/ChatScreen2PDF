"""
long_image.py — 长截图处理：自动切片、参数校验。
"""

import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

# 支持的图片格式（含 JFIF）
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".jfif"}

DEFAULT_SLICE_HEIGHT = 3000
DEFAULT_OVERLAP = 150
MIN_SLICE_HEIGHT = 500
MAX_SLICE_HEIGHT = 10000


def validate_params(slice_height: int, overlap: int) -> None:
    """验证切片参数。"""
    if not isinstance(slice_height, int) or slice_height < MIN_SLICE_HEIGHT:
        raise ValueError(f"切片高度必须 ≥ {MIN_SLICE_HEIGHT}px，当前: {slice_height}")
    if slice_height > MAX_SLICE_HEIGHT:
        raise ValueError(f"切片高度必须 ≤ {MAX_SLICE_HEIGHT}px，当前: {slice_height}")
    if not isinstance(overlap, int) or overlap < 0:
        raise ValueError(f"重叠高度必须 ≥ 0，当前: {overlap}")
    if overlap >= slice_height:
        raise ValueError(f"重叠高度 ({overlap}) 必须小于切片高度 ({slice_height})")


def slice_image(
    image_path: Path,
    output_dir: Path,
    slice_height: int = DEFAULT_SLICE_HEIGHT,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Path]:
    """
    将长截图切片为多张图片。

    Args:
        image_path: 长截图路径。
        output_dir: 输出目录。
        slice_height: 每片高度（像素）。
        overlap: 重叠区域高度（像素）。

    Returns:
        排序后的切片路径列表。
    """
    validate_params(slice_height, overlap)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(image_path)
    img_w, img_h = img.size

    if img_h <= slice_height:
        # 图不够长，直接返回原图
        single = output_dir / f"{image_path.stem}_001{image_path.suffix}"
        img.save(str(single))
        logger.info("Long image too short (%dpx), no slicing needed", img_h)
        return [single]

    slices = []
    top = 0
    index = 1

    while top < img_h:
        bottom = min(top + slice_height, img_h)
        crop = img.crop((0, top, img_w, bottom))
        out_path = output_dir / f"{image_path.stem}_{index:03d}{image_path.suffix}"
        crop.save(str(out_path))
        slices.append(out_path)
        logger.debug("Slice %d: y=%d..%d", index, top, bottom)

        index += 1
        if bottom == img_h:
            break
        # 下一片起点：减去重叠
        top = bottom - overlap

    logger.info("Sliced %s: %dpx → %d slices (slice=%dpx, overlap=%dpx)",
                image_path.name, img_h, len(slices), slice_height, overlap)
    return slices

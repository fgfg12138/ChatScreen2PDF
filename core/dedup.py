"""
dedup.py - Average hash (aHash) dedup, supports consecutive / global modes.
Pure numpy + Pillow, no external dependencies.
"""

from __future__ import annotations
import logging
from pathlib import Path
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

HASH_SIZE = 16  # resize to 16x16, hash = 256 bits


def _compute_ahash(image_path: Path) -> np.ndarray:
    """Average hash: resize to HASH_SIZE x HASH_SIZE, grayscale, threshold by mean."""
    with Image.open(image_path) as img:
        gray = img.convert("L").resize((HASH_SIZE, HASH_SIZE), Image.LANCZOS)
        pixels = np.array(gray, dtype=np.float64)
    mean = pixels.mean()
    return (pixels > mean).flatten().astype(np.uint8)


def _hamming(h1: np.ndarray, h2: np.ndarray) -> int:
    return int(np.sum(h1 != h2))


def dedup_frames_consecutive(frame_paths: list, threshold: int) -> list:
    if not frame_paths:
        return []
    kept = [frame_paths[0]]
    prev = _compute_ahash(frame_paths[0])
    for p in frame_paths[1:]:
        cur = _compute_ahash(p)
        d = _hamming(prev, cur)
        if d < threshold:
            logger.debug("dedup(consec): drop %s (d=%d)", p.name, d)
            continue
        kept.append(p)
        prev = cur
    logger.info("dedup(consec): %d -> %d (thr=%d)", len(frame_paths), len(kept), threshold)
    return kept


def dedup_frames_global(frame_paths: list, threshold: int) -> list:
    if not frame_paths:
        return []
    win = 50
    kept = [frame_paths[0]]
    hashes = [_compute_ahash(frame_paths[0])]
    for p in frame_paths[1:]:
        cur = _compute_ahash(p)
        if any(_hamming(cur, h) < threshold for h in hashes[-win:]):
            logger.debug("dedup(global): drop %s", p.name)
            continue
        kept.append(p)
        hashes.append(cur)
    logger.info("dedup(global): %d -> %d (thr=%d, win=%d)", len(frame_paths), len(kept), threshold, win)
    return kept


def dedup_frames(frame_paths: list, threshold: int, mode: str = "consecutive") -> list:
    if mode == "consecutive":
        return dedup_frames_consecutive(frame_paths, threshold)
    elif mode == "global":
        return dedup_frames_global(frame_paths, threshold)
    else:
        raise ValueError("dedup_mode must be consecutive or global, got: " + str(mode))

"""
scanner.py — 扫描输入文件夹，返回合法视频文件路径列表。
"""

from pathlib import Path


# 支持的视频格式（小写），运行时会做大小写匹配
VIDEO_EXTENSIONS: set[str] = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
}


def scan_videos(input_dir: Path) -> list[Path]:
    """
    递归扫描 input_dir，返回所有视频文件的绝对路径（按路径排序）。

    Args:
        input_dir: 要扫描的文件夹路径。

    Returns:
        排序后的视频文件路径列表。

    Raises:
        FileNotFoundError: input_dir 不存在。
        NotADirectoryError: input_dir 不是文件夹。
    """
    if not input_dir.exists():
        raise FileNotFoundError(f"输入路径不存在: {input_dir}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"输入路径不是文件夹: {input_dir}")

    videos: list[Path] = [
        p
        for p in input_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    ]

    return sorted(videos)

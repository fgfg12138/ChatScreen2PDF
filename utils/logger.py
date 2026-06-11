"""日志配置：控制台 + 文件。"""

from __future__ import annotations
import datetime
import logging
import sys
from pathlib import Path


def setup_logger(log_dir=None, level=logging.DEBUG):
    """
    配置根日志器。
    log_dir: 日志目录，默认项目根目录/logs/
    """
    if log_dir is None:
        log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"run_{ts}.log"

    root = logging.getLogger()
    root.setLevel(level)

    if any(isinstance(h, logging.FileHandler) for h in root.handlers):
        return root

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(ch)

    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(fh)
    return root

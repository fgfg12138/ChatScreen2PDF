"""
cleanup.py — 临时目录管理：创建、自动清理、异常兜底。
"""

from __future__ import annotations

import atexit
import logging
import shutil
import signal
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# 全局注册表，记录所有待清理的临时目录
_registered_dirs: set[str] = set()
_cleanup_done = False


def _cleanup_all() -> None:
    """清理所有已注册的临时目录。"""
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True
    for d in list(_registered_dirs):
        p = Path(d)
        if p.exists():
            try:
                shutil.rmtree(p)
                logger.debug("已清理临时目录: %s", d)
            except OSError:
                pass
    _registered_dirs.clear()


# 进程正常退出时清理
atexit.register(_cleanup_all)


def _signal_handler(signum: int, frame) -> None:
    _cleanup_all()
    raise SystemExit(128 + signum)


# 注册信号处理器（SIGTERM 在 Windows 上部分支持，SIGINT 正常）
for _sig in (signal.SIGTERM, signal.SIGINT):
    try:
        signal.signal(_sig, _signal_handler)
    except (OSError, ValueError):
        pass


class TempDir:
    """
    临时目录 Context Manager。

    用法::

        with TempDir() as tmp:
            # tmp 是一个 Path 对象，指向新创建的临时目录
            ...

    退出时自动删除，无论是否发生异常。
    同时注册到 atexit，确保进程异常退出也能清理。
    """

    def __init__(self, prefix: str = "chatScreen2pdf_") -> None:
        self._prefix = prefix
        self._path: Path | None = None

    def __enter__(self) -> Path:
        self._path = Path(tempfile.mkdtemp(prefix=self._prefix))
        _registered_dirs.add(str(self._path))
        logger.debug("创建临时目录: %s", self._path)
        return self._path

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._path is not None and self._path.exists():
            try:
                shutil.rmtree(self._path)
                logger.debug("已删除临时目录: %s", self._path)
            except OSError:
                pass
            _registered_dirs.discard(str(self._path))

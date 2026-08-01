#!/usr/bin/env python3
"""
Build an FFmpeg helper installer attachment.

The attachment contains instructions and a winget helper script only. It does
not redistribute FFmpeg binaries.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

README = """FFmpeg 视频组件安装说明
======================

用途
----
视频转 PDF/Word 需要 FFmpeg 负责读取视频并抽帧。
图片转 PDF/Word、长截图转 PDF/Word 不需要 FFmpeg。

重要说明
--------
- 本附件不包含 FFmpeg 二进制文件。
- 安装脚本会调用 Windows winget 安装第三方 FFmpeg 包。
- FFmpeg 是第三方开源项目，不由本软件作者开发或维护。

官方地址
--------
- FFmpeg 官网: https://ffmpeg.org/
- FFmpeg 下载页: https://ffmpeg.org/download.html

推荐给普通用户的安装方式
------------------------
1. 解压本附件。
2. 双击运行：安装FFmpeg视频组件.bat
3. 按提示确认安装。
4. 安装完成后重新打开主程序。

如果用户电脑不能联网
--------------------
请在一台能联网的电脑上访问 https://ffmpeg.org/download.html 按官方说明下载 Windows 版本。
离线电脑可以让技术人员将 ffmpeg.exe 所在目录加入系统 PATH，或把 ffmpeg.exe 放到主程序同级的 tools/ffmpeg/ffmpeg.exe。
"""

INSTALL_BAT = r"""@echo off
chcp 65001 >nul
setlocal

echo.
echo FFmpeg 视频组件安装助手
echo ======================
echo 视频转 PDF/Word 需要 FFmpeg。图片和长截图功能不需要 FFmpeg。
echo.
echo 本脚本不内置 FFmpeg，会通过 Windows winget 安装第三方 FFmpeg 包。
echo FFmpeg 官网：https://ffmpeg.org/
echo.
pause

where winget >nul 2>nul
if %errorlevel% neq 0 (
  echo.
  echo 未检测到 winget。
  echo 请访问 https://ffmpeg.org/download.html 按官方说明安装 FFmpeg。
  pause
  exit /b 1
)

echo.
echo 正在调用 winget 安装 FFmpeg...
winget install --id Gyan.FFmpeg -e
if %errorlevel% neq 0 (
  echo.
  echo winget 安装未完成。请访问 https://ffmpeg.org/download.html 查看官方安装方式。
  pause
  exit /b 1
)

echo.
echo FFmpeg 安装完成。请重新打开主程序。
pause
"""


def build() -> Path:
    dist = PROJECT_ROOT / "dist"
    dist.mkdir(exist_ok=True)

    work = dist / "FFmpeg-video-component-installer"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    (work / "FFmpeg安装说明.txt").write_text(README, encoding="utf-8")
    (work / "安装FFmpeg视频组件.bat").write_text(INSTALL_BAT, encoding="utf-8")

    zip_path = dist / "FFmpeg-video-component-installer.zip"
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in work.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, str(Path(work.name) / file_path.relative_to(work)))
    return zip_path


if __name__ == "__main__":
    print(build())

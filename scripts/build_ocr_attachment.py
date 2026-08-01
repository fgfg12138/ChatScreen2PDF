#!/usr/bin/env python3
"""
Build an optional PaddleOCR / PaddlePaddle installer attachment.

The attachment contains scripts and instructions only. It does not redistribute
PaddleOCR, PaddlePaddle, model files, or third-party binaries.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

README = """PaddleOCR / PaddlePaddle 可选安装器
================================

用途
----
本附件用于安装 PaddleOCR 与 PaddlePaddle，让主程序可以使用本地 OCR 辅助筛选视频帧。
不安装 OCR 也可以正常使用图片转 PDF/Word、长截图转 PDF/Word、视频抽帧、模糊过滤、手动排序、PDF/Word 导出。

重要说明
--------
- 本附件不包含 PaddleOCR、PaddlePaddle、模型文件或第三方二进制文件。
- 安装脚本会通过 pip 从 Python 包仓库下载官方依赖。
- OCR 仅作为本地辅助筛选能力，不会上传文件。
- 依赖体积较大，通常需要约 2GB 磁盘空间，并且首次安装需要联网。

官方地址
--------
- PaddleOCR GitHub: https://github.com/PaddlePaddle/PaddleOCR
- PaddlePaddle 官网: https://www.paddlepaddle.org.cn/
- PaddleOCR PyPI: https://pypi.org/project/paddleocr/
- PaddlePaddle PyPI: https://pypi.org/project/paddlepaddle/

使用方式
--------
1. 将本附件解压到主程序 EXE 同级目录。
2. 双击运行：安装PaddleOCR到程序目录.bat
3. 等待安装完成。
4. 重新打开主程序。

安装后目录结构示例
------------------
主程序.exe
ocr/
  site-packages/
    paddleocr/
    paddle/

如果用户电脑不能联网
--------------------
请在一台能联网的电脑上运行本附件，生成 ocr/site-packages 后，将整个 ocr 文件夹复制到离线电脑的主程序 EXE 同级目录。
"""

INSTALL_BAT = r"""@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo PaddleOCR / PaddlePaddle 可选安装器
echo ==================================
echo 本脚本会把 PaddleOCR 和 PaddlePaddle 安装到当前目录的 ocr\site-packages。
echo 安装包较大，通常需要约 2GB 磁盘空间，并且需要联网。
echo.
echo 官方地址：
echo   PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR
echo   PaddlePaddle: https://www.paddlepaddle.org.cn/
echo.
pause

if not exist "ocr" mkdir "ocr"
if not exist "ocr\site-packages" mkdir "ocr\site-packages"

where py >nul 2>nul
if %errorlevel%==0 (
  py -m pip install --upgrade pip
  py -m pip install --target "%~dp0ocr\site-packages" paddleocr paddlepaddle
  goto :done
)

where python >nul 2>nul
if %errorlevel%==0 (
  python -m pip install --upgrade pip
  python -m pip install --target "%~dp0ocr\site-packages" paddleocr paddlepaddle
  goto :done
)

echo.
echo 未找到 Python。请先安装 Python 3.10-3.12，然后重新运行本脚本。
pause
exit /b 1

:done
echo.
echo 安装完成。请重新打开主程序。
pause
"""


def build() -> Path:
    dist = PROJECT_ROOT / "dist"
    dist.mkdir(exist_ok=True)

    work = dist / "PaddleOCR-PaddlePaddle-optional-installer"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    (work / "PaddleOCR安装说明.txt").write_text(README, encoding="utf-8")
    (work / "安装PaddleOCR到程序目录.bat").write_text(INSTALL_BAT, encoding="utf-8")
    (work / "requirements-ocr.txt").write_text("paddleocr\npaddlepaddle\n", encoding="utf-8")

    zip_path = dist / "PaddleOCR-PaddlePaddle-optional-installer.zip"
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in work.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, str(Path(work.name) / file_path.relative_to(work)))
    return zip_path


if __name__ == "__main__":
    print(build())

#!/usr/bin/env python3
"""
Build Windows portable packages with PyInstaller.

Usage:
    python scripts/build_exe.py --edition full
    python scripts/build_exe.py --edition lite
    python scripts/build_exe.py --all
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_CONFIG = PROJECT_ROOT / "app_config.py"
APP_NAME = "Framescreen2PDF"

EXCLUDE_MODULES = [
    # Optional OCR dependency. It is distributed as a separate installer package.
    "paddleocr",
    "paddlepaddle",
    "paddle",
    "paddlex",
    # Unused GUI/testing modules.
    "tkinter",
    "tk",
    "tcl",
    "pytest",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Build Framescreen2PDF Windows packages")
    parser.add_argument("--edition", choices=["full", "lite"], default="full")
    parser.add_argument("--all", action="store_true", help="Build both Full and Lite")
    parser.add_argument(
        "--strip-metadata",
        action="store_true",
        help="Remove top-level *.dist-info folders from the frozen package",
    )
    return parser.parse_args()


def get_version() -> str:
    text = (PROJECT_ROOT / "__version__.py").read_text(encoding="utf-8")
    match = re.search(r'"([^"]+)"', text)
    return match.group(1) if match else "unknown"


def write_app_config(edition: str) -> None:
    APP_CONFIG.write_text(
        f'APP_NAME = "{APP_NAME}"\n'
        f'APP_VERSION = "{get_version()}"\n'
        f'APP_EDITION = "{edition}"\n',
        encoding="utf-8",
    )


def clean_pycache(root: Path) -> None:
    """Remove __pycache__ dirs so they are not bundled into releases."""
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def pre_build_checks() -> None:
    index_path = PROJECT_ROOT / "web" / "static" / "index.html"
    routes_path = PROJECT_ROOT / "web" / "routes.py"
    errors: list[str] = []

    if not index_path.exists():
        errors.append("web/static/index.html 不存在")
    else:
        html = index_path.read_text(encoding="utf-8")
        required = [
            APP_NAME,
            "/api/health",
            "word-only",
            "full-only",
            "watermark-control",
            "videoBtnGenerate",
            "enableOcrAssist",
            "videoBtnImagesZip",
            "videoBatchDownloadLink",
            "runBatchJobs",
            "</script>",
        ]
        for keyword in required:
            if keyword not in html:
                errors.append(f"web/static/index.html 缺少: {keyword}")
        if html.count("</script>") != 1:
            errors.append(f"web/static/index.html 应只有 1 个 </script>，实际 {html.count('</script>')} 个")
        if "var el = safeGet(id)" in html:
            errors.append("web/static/index.html 存在 safeGet 递归调用")

    if not routes_path.exists():
        errors.append("web/routes.py 不存在")
    else:
        routes = routes_path.read_text(encoding="utf-8")
        required = [
            "APP_EDITION",
            "ENABLE_WORD",
            "ENABLE_VIDEO_IMAGE_ZIP",
            "DEFAULT_WATERMARK",
            "create_video_pdf",
            "create_video_images_zip",
            "download_video_batch",
            "create_image_word",
        ]
        for keyword in required:
            if keyword not in routes:
                errors.append(f"web/routes.py 缺少: {keyword}")

    if errors:
        print("打包前检查失败：")
        for error in errors:
            print("  - " + error)
        sys.exit(1)
    print("打包前检查通过。")


def remove_if_exists(path: Path) -> None:
    if path.exists():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def run_pyinstaller(edition: str) -> None:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--console",
        "--name",
        APP_NAME,
        "--add-data",
        "web" + os.pathsep + "web",
        "--hidden-import",
        "fastapi",
        "--hidden-import",
        "uvicorn",
        "--hidden-import",
        "pydantic",
        "--hidden-import",
        "multipart",
        "--hidden-import",
        "pikepdf",
        "--hidden-import",
        "zoneinfo",
    ]
    if edition == "full":
        cmd += [
            "--hidden-import",
            "docx",
            "--hidden-import",
            "lxml",
        ]

    exclude_modules = list(EXCLUDE_MODULES)
    if edition == "lite":
        exclude_modules += ["docx", "lxml"]

    for module in exclude_modules:
        cmd += ["--exclude-module", module]
    cmd.append("web_app.py")

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    if result.returncode != 0:
        print("PyInstaller 失败：")
        print(result.stdout[-3000:])
        print(result.stderr[-3000:])
        sys.exit(result.returncode)


def verify_build(dist_dir: Path, edition: str) -> None:
    errors: list[str] = []
    exe = dist_dir / f"{APP_NAME}.exe"
    if not exe.exists():
        errors.append(f"{APP_NAME}.exe 未生成")

    for ffmpeg in dist_dir.rglob("ffmpeg.exe"):
        errors.append("正式包不应内置 FFmpeg: " + str(ffmpeg.relative_to(dist_dir)))

    for rel in ["tests", "scripts", "build", ".pytest_cache"]:
        if (dist_dir / rel).exists():
            errors.append("不应包含开发目录: " + rel)

    if edition == "lite":
        for rel in ["_internal/docx", "_internal/lxml"]:
            if (dist_dir / rel).exists():
                errors.append("Lite 版不应包含 Word 依赖: " + rel)

    index_path = dist_dir / "_internal" / "web" / "static" / "index.html"
    if not index_path.exists():
        errors.append("_internal/web/static/index.html 未打包")
    else:
        html = index_path.read_text(encoding="utf-8")
        if APP_NAME not in html:
            errors.append("打包后的首页缺少应用名")
        if edition == "lite" and "word-only" not in html:
            errors.append("Lite 包缺少 Word 隐藏控制标记")
        if edition == "lite" and "PDF/Word" in html:
            errors.append("Lite 包首页不应显示 PDF/Word")

    routes_path = dist_dir / "_internal" / "web" / "routes.py"
    if not routes_path.exists():
        errors.append("_internal/web/routes.py 未打包")

    if errors:
        print("打包产物验证失败：")
        for error in errors:
            print("  - " + error)
        sys.exit(1)
    print("打包产物验证通过。")


def build_exe(edition: str, strip_metadata: bool = False) -> Path:
    clean_pycache(PROJECT_ROOT)
    pre_build_checks()
    write_app_config(edition)

    version = get_version()
    label = "Full" if edition == "full" else "Lite"
    dist_name = f"{APP_NAME}-{label}-v{version}-windows"
    dist_dir = PROJECT_ROOT / "dist" / dist_name

    remove_if_exists(PROJECT_ROOT / "build")
    remove_if_exists(PROJECT_ROOT / "dist" / APP_NAME)
    remove_if_exists(dist_dir)

    print(f"开始构建: {dist_name}")
    run_pyinstaller(edition)

    pyinstaller_out = PROJECT_ROOT / "dist" / APP_NAME
    if pyinstaller_out.exists():
        pyinstaller_out.rename(dist_dir)

    if strip_metadata:
        removed = 0
        internal = dist_dir / "_internal"
        if internal.exists():
            for info in internal.glob("*.dist-info"):
                shutil.rmtree(info)
                removed += 1
        print(f"已清理 {removed} 个 dist-info 目录")

    for name in ["README.md", "CHANGELOG.md", "GUI_MANUAL_TEST.md"]:
        src = PROJECT_ROOT / name
        if src.exists():
            shutil.copy2(src, dist_dir / name)

    if edition == "lite":
        postprocess_lite_build(dist_dir)

    verify_build(dist_dir, edition)

    file_count = sum(1 for p in dist_dir.rglob("*") if p.is_file())
    size_mb = sum(p.stat().st_size for p in dist_dir.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"构建完成: {dist_dir}")
    print(f"文件数: {file_count}, 大小: {size_mb:.1f} MB")
    return dist_dir


def postprocess_lite_build(dist_dir: Path) -> None:
    """Remove user-facing Word references from Lite static assets."""
    index_path = dist_dir / "_internal" / "web" / "static" / "index.html"
    if not index_path.exists():
        return
    html = index_path.read_text(encoding="utf-8")
    html = html.replace("视频/截图转 PDF/Word 工具", "视频/截图转 PDF 工具")
    html = html.replace("图片转 PDF/Word", "图片转 PDF")
    html = html.replace("视频转 PDF/Word", "视频转 PDF")
    html = html.replace("长截图转 PDF/Word", "长截图转 PDF")
    html = html.replace("可导出 PDF/Word", "可导出 PDF")
    html = html.replace("视频转 PDF/Word 需要 FFmpeg", "视频转 PDF 需要 FFmpeg")
    html = html.replace("图片和长截图功能不需要 FFmpeg", "图片和长截图功能不需要 FFmpeg")
    index_path.write_text(html, encoding="utf-8")


def build_zip(dist_dir: Path, edition: str) -> Path:
    version = get_version()
    label = "Full" if edition == "full" else "Lite"
    zip_path = PROJECT_ROOT / "dist" / f"{APP_NAME}-{label}-v{version}-windows.zip"
    remove_if_exists(zip_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in dist_dir.rglob("*"):
            if file_path.is_file():
                arcname = Path(dist_dir.name) / file_path.relative_to(dist_dir)
                zf.write(file_path, str(arcname))

    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"ZIP 完成: {zip_path} ({size_mb:.1f} MB)")
    return zip_path


def main() -> None:
    os.chdir(PROJECT_ROOT)
    args = parse_args()
    editions = ["full", "lite"] if args.all else [args.edition]
    original_config = APP_CONFIG.read_text(encoding="utf-8") if APP_CONFIG.exists() else ""

    try:
        for edition in editions:
            dist_dir = build_exe(edition, args.strip_metadata)
            build_zip(dist_dir, edition)
    finally:
        if original_config:
            APP_CONFIG.write_text(original_config, encoding="utf-8")


if __name__ == "__main__":
    main()

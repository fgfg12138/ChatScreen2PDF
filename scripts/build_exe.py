#!/usr/bin/env python3
"""
build_exe.py - Build Windows Portable (onedir) via PyInstaller.
Usage:
    python scripts/build_exe.py
    python scripts/build_exe.py --strip-metadata

FFmpeg 准备逻辑：
  A. 已解压目录：../ffmpeg-8.1.1-essentials_build/bin/ffmpeg.exe
  B. 本地 ZIP：  ../ffmpeg-8.1.1-essentials_build.zip
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESOURCES_DIR = PROJECT_ROOT / "resources" / "ffmpeg"

# FFmpeg 来源路径
FFMPEG_EXTRACTED_DIR = PROJECT_ROOT.parent / "ffmpeg-8.1.1-essentials_build"
FFMPEG_EXTRACTED_EXE = FFMPEG_EXTRACTED_DIR / "bin" / "ffmpeg.exe"
FFMPEG_ZIP = PROJECT_ROOT.parent / "ffmpeg-8.1.1-essentials_build.zip"

# Modules to exclude from the Windows build
EXCLUDE_MODULES = [
    # OCR (frozen)
    "paddleocr", "paddlepaddle", "paddle", "paddlex", "paddleocr_predict",
    "ocrmypdf",
    # Unused GUI framework
    "tkinter", "tk", "tcl",
    # Indirect dependencies not needed
    "lxml", "dateutil",
    # Testing (not needed at runtime)
    "pytest",
]


def parse_args():
    p = argparse.ArgumentParser(description="Build ChatScreen2PDF Windows Portable")
    p.add_argument("--strip-metadata", action="store_true", default=False,
                    help="Remove *.dist-info from build (may break importlib.metadata)")
    return p.parse_args()


def get_version():
    vf = PROJECT_ROOT / "__version__.py"
    m = re.search(r'"([^"]+)"', vf.read_text(encoding="utf-8"))
    return m.group(1) if m else "unknown"


def prepare_ffmpeg():
    """检测并准备 FFmpeg。优先使用已解压目录，兜底使用 ZIP。"""
    RESOURCES_DIR.mkdir(parents=True, exist_ok=True)
    target = RESOURCES_DIR / "ffmpeg.exe"

    if target.exists():
        print("ffmpeg.exe 已存在: " + str(target))
        return target

    # A. 已解压目录
    if FFMPEG_EXTRACTED_EXE.exists():
        print("检测到已解压 FFmpeg: " + str(FFMPEG_EXTRACTED_EXE))
        shutil.copy2(str(FFMPEG_EXTRACTED_EXE), str(target))
        print("已复制到: " + str(target))
        return target

    # B. 本地 ZIP
    if FFMPEG_ZIP.exists():
        print("检测到 FFmpeg ZIP: " + str(FFMPEG_ZIP))
        print("正在提取 ffmpeg.exe...")
        with zipfile.ZipFile(str(FFMPEG_ZIP), "r") as zf:
            candidates = [n for n in zf.namelist()
                          if n.endswith("ffmpeg.exe") and "ffplay" not in n and "ffprobe" not in n]
            if not candidates:
                print("错误：ZIP 中未找到 ffmpeg.exe")
                sys.exit(1)
            print("  找到: " + candidates[0])
            target.write_bytes(zf.read(candidates[0]))
            print("已提取到: " + str(target))
        return target

    # 未找到
    print("错误：未找到 FFmpeg。")
    print("请确认以下任一位置存在：")
    print("  1. " + str(FFMPEG_EXTRACTED_EXE))
    print("  2. " + str(FFMPEG_ZIP))
    sys.exit(1)


def _pre_build_checks():
    """打包前检查：确保是 feature/ocr-complete 分支的新 UI。"""
    errors = []
    
    # 检查 index.html 包含新 UI 关键词
    index_path = PROJECT_ROOT / "web" / "static" / "index.html"
    keywords = [
        "第 1 步：选择视频",
        "/api/video/draft",
        "videoBtnGenerate",
    ]
    if index_path.exists():
        content = index_path.read_text(encoding="utf-8")
        for kw in keywords:
            if kw not in content:
                errors.append(f"web/static/index.html 缺少关键内容: {kw}")
    else:
        errors.append("web/static/index.html 不存在")
    
    # 检查 safeGet 不包含递归调用（曾经导致 WebUI 完全瘫痪的 bug）
    if index_path.exists():
        content = index_path.read_text(encoding="utf-8")
        # 禁止：safeGet 内部递归调用自身
        forbidden_patterns = [
            ("var el = safeGet(id)", "safeGet 递归调用自身（应使用 document.getElementById）"),
            ("safeGet('global-error-bar')", "safeGet 内部再次调用 safeGet（应使用 document.getElementById）"),
        ]
        for pattern, desc in forbidden_patterns:
            if pattern in content:
                errors.append(f"web/static/index.html 含递归 bug: {desc}")
        # 必须：safeGet 内部调用了正确的 DOM API
        required_patterns = [
            ("document.getElementById(id)", "safeGet 应使用 document.getElementById(id)"),
            ("document.getElementById('global-error-bar')", "safeGet 应使用 document.getElementById('global-error-bar')"),
        ]
        for pattern, desc in required_patterns:
            if pattern not in content:
                errors.append(f"web/static/index.html 缺少: {desc}")
    

    # 检查 index.html 有 </script> 闭合标签（缺失会导致浏览器 SyntaxError，整个 JS 报废）
    if index_path.exists():
        content = index_path.read_text(encoding="utf-8")
        if "</script>" not in content:
            errors.append("web/static/index.html 缺少 </script> 闭合标签，浏览器将无法执行 JS")

    # 检查 routes.py 包含新 API
    routes_path = PROJECT_ROOT / "web" / "routes.py"
    api_funcs = [
        "create_video_draft",
        "create_video_job",
        "create_reference_frame",
        "create_video_pdf",
    ]
    if routes_path.exists():
        content = routes_path.read_text(encoding="utf-8")
        for fn in api_funcs:
            if f"async def {fn}" not in content:
                errors.append(f"web/routes.py 缺少 API: {fn}")
    else:
        errors.append("web/routes.py 不存在")
    
    if errors:
        print("=" * 50)
        print("打包前检查失败：")
        for e in errors:
            print("  [FAIL] " + e)
        print("=" * 50)
        print("请先切换到 feature/ocr-complete 分支：")
        print("  git checkout feature/ocr-complete")
        print("  git reset --hard origin/feature/ocr-complete")
        sys.exit(1)
    else:
        print("打包前检查通过 [OK] - 确认包含新 UI 和新 API")


def build_exe(strip_metadata=False):
    # 先做检查
    _pre_build_checks()
    
    version = get_version()
    dist_name = "ChatScreen2PDF-v" + version + "-windows"
    dist_dir = PROJECT_ROOT / "dist" / dist_name

    # 清理旧构建，只清理指定目录
    for d in [PROJECT_ROOT / "build"]:
        if d.exists():
            shutil.rmtree(d)
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    # 也清理 PyInstaller 默认输出
    default_out = PROJECT_ROOT / "dist" / "ChatScreen2PDF"
    if default_out.exists():
        shutil.rmtree(default_out)

    print("Building " + dist_name + "...")
    print("Excluding: " + ", ".join(EXCLUDE_MODULES))

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--console",
        "--name", "ChatScreen2PDF",
        "--add-data", "resources" + os.pathsep + "resources",
        "--add-data", "web" + os.pathsep + "web",
        "--hidden-import", "fastapi",
        "--hidden-import", "uvicorn",
        "--hidden-import", "pydantic",
        "--hidden-import", "multipart",
        "--hidden-import", "pikepdf",
        "--hidden-import", "zoneinfo",
    ]
    for mod in EXCLUDE_MODULES:
        cmd += ["--exclude-module", mod]
    cmd.append("web_app.py")

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    if result.returncode != 0:
        print("PyInstaller 失败:")
        print(result.stderr[-3000:] if len(result.stderr) > 3000 else result.stderr)
        sys.exit(1)

    # Rename output
    pyinstaller_out = PROJECT_ROOT / "dist" / "ChatScreen2PDF"
    if pyinstaller_out.exists():
        if dist_dir.exists():
            shutil.rmtree(dist_dir)
        pyinstaller_out.rename(dist_dir)

    # Optional: strip metadata
    if strip_metadata:
        print("正在清理 dist-info 元数据...")
        removed = 0
        for d in (dist_dir / "_internal").glob("*.dist-info"):
            shutil.rmtree(d)
            removed += 1
        print("  已清理 " + str(removed) + " 个 dist-info 目录")

    # Copy docs
    for fname in ["README.md", "CHANGELOG.md", "GUI_MANUAL_TEST.md"]:
        src = PROJECT_ROOT / fname
        if src.exists():
            shutil.copy2(src, dist_dir / fname)

    # Licenses
    lic_dir = dist_dir / "licenses"
    lic_dir.mkdir(exist_ok=True)
    (lic_dir / "FFmpeg-GPL.txt").write_text(
        "FFmpeg is licensed under GPLv2.\nhttps://www.gnu.org/licenses/old-licenses/gpl-2.0.html\n",
        encoding="utf-8",
    )

    # 将 resources/ 从 _internal/ 复制到顶层（PyInstaller onedir 将 --add-data 放入 _internal/）
    internal_res = dist_dir / "_internal" / "resources"
    top_res = dist_dir / "resources"
    if internal_res.exists() and not top_res.exists():
        shutil.copytree(str(internal_res), str(top_res))
        print("已复制 resources/ 到顶层")
    elif not top_res.exists():
        print("警告：resources/ 未找到，请检查 FFmpeg 准备步骤")

    # 打包后检查：确认 dist 内包含新 UI
    _post_build_checks(dist_dir)

    # 验证核心文件
    _verify_build(dist_dir)

    # Count files
    file_count = sum(1 for _ in dist_dir.rglob("*") if _.is_file())
    total_size_mb = sum(f.stat().st_size for f in dist_dir.rglob("*") if f.is_file()) / 1024 / 1024
    print("完成: " + str(dist_dir))
    print("  文件数: " + str(file_count))
    print("  大小: " + str(round(total_size_mb, 1)) + " MB")
    return dist_dir


def _verify_build(dist_dir):
    """验证打包产物完整性。"""
    errors = []

    # 1. EXE 必须存在
    exe = dist_dir / "ChatScreen2PDF.exe"
    if not exe.exists():
        errors.append("ChatScreen2PDF.exe 未生成")

    # 2. ffmpeg 必须存在
    ffmpeg = dist_dir / "resources" / "ffmpeg" / "ffmpeg.exe"
    if not ffmpeg.exists():
        errors.append("resources/ffmpeg/ffmpeg.exe 缺失")

    # 3. 不应包含开发文件
    dev_patterns = ["tests/", "scripts/", "__pycache__", ".pyc",
                    ".pytest_cache", "build/"]
    # 源码 zip 模式 — 只检查顶层和 docs/licenses 目录不出现 .zip
    source_zips = [".zip"]
    for f in dist_dir.rglob("*"):
        if f.is_file():
            rel = str(f.relative_to(dist_dir))
            # 跳过 _internal/ 下的文件（PyInstaller 运行时）
            if rel.startswith("_internal" + os.sep):
                continue
            for pat in dev_patterns:
                if pat in rel:
                    errors.append("包含不应出现的文件: " + rel)
                    break
            for pat in source_zips:
                if rel.endswith(".zip"):
                    errors.append("包含不应出现的 zip: " + rel)
                    break

    if errors:
        print("验证失败:")
        for e in errors:
            print("  - " + e)
        sys.exit(1)
    print("打包验证通过。")


def _post_build_checks(dist_dir):
    """打包后检查：确认 dist 内包含新 UI 和新 API。"""
    errors = []

    # 检查 dist 内的 index.html
    dist_index = dist_dir / "_internal" / "web" / "static" / "index.html"
    if dist_index.exists():
        content = dist_index.read_text(encoding="utf-8")
        checks = [
            ("第 1 步：选择视频", "新 UI 步骤引导"),
            ("/api/video/draft", "草稿上传 API"),
            ("videoBtnGenerate", "开始转换按钮"),
        ]
        for keyword, desc in checks:
            if keyword not in content:
                errors.append(f"_internal/web/static/index.html 缺少 {desc}: {keyword}")
    else:
        errors.append("_internal/web/static/index.html 不存在")

    # 检查 dist 内的 routes.py
    dist_routes = dist_dir / "_internal" / "web" / "routes.py"
    if dist_routes.exists():
        content = dist_routes.read_text(encoding="utf-8")
        for fn in ["create_video_draft", "create_reference_frame", "create_video_pdf"]:
            if f"async def {fn}" not in content:
                errors.append(f"_internal/web/routes.py 缺少函数: {fn}")
    else:
        errors.append("_internal/web/routes.py 不存在")

    if errors:
        print("=" * 50)
        print("打包后检查失败：")
        for e in errors:
            print("  [FAIL] " + e)
        print("=" * 50)
        sys.exit(1)
    else:
        print("打包后检查通过 [OK] - dist 内确认包含新 UI 和新 API")


def build_zip(dist_dir):
    """将构建产物打包为 zip。"""
    version = get_version()
    zip_name = "ChatScreen2PDF-v" + version + "-windows.zip"
    zip_path = PROJECT_ROOT / "dist" / zip_name

    # 删除旧 zip
    if zip_path.exists():
        zip_path.unlink()

    print("打包 ZIP: " + zip_name + "...")
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in dist_dir.rglob("*"):
            if file_path.is_file():
                arcname = str(dist_dir.name / file_path.relative_to(dist_dir))
                zf.write(str(file_path), arcname)

    count = sum(1 for _ in zipfile.ZipFile(str(zip_path)).namelist())
    size_kb = zip_path.stat().st_size / 1024
    print("ZIP 完成: " + zip_name)
    print("  文件数: " + str(count))
    print("  大小: " + str(round(size_kb, 1)) + " KB (" + str(round(size_kb / 1024, 1)) + " MB)")
    return zip_path


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    args = parse_args()
    prepare_ffmpeg()
    dist = build_exe(strip_metadata=args.strip_metadata)
    build_zip(dist)

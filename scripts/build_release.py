#!/usr/bin/env python3
"""
Build the source release zip.

Usage:
    python scripts/build_release.py
"""

from __future__ import annotations

import os
import re
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "Framescreen2PDF"

EXCLUDE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    "output",
    "temp",
    "logs",
    ".mypy_cache",
    "build",
    "dist",
    "dist_new",
    "resources",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".zip", ".spec"}
EXCLUDE_FILES = {"dedup_hash.py"}


def get_version() -> str:
    text = (PROJECT_ROOT / "__version__.py").read_text(encoding="utf-8")
    match = re.search(r'"([^"]+)"', text)
    if match:
        return match.group(1)
    raise RuntimeError("Cannot parse version")


def should_exclude(rel: str) -> bool:
    path = Path(rel)
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    if path.name in EXCLUDE_FILES:
        return True
    return False


def compile_sources() -> None:
    import py_compile

    errors: list[str] = []
    for py_file in PROJECT_ROOT.rglob("*.py"):
        rel = py_file.relative_to(PROJECT_ROOT)
        if should_exclude(str(rel)):
            continue
        try:
            py_compile.compile(str(py_file), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(str(exc))

    if errors:
        for error in errors:
            print("Compile error:", error)
        sys.exit(1)
    print("compileall OK")


def build() -> Path:
    os.chdir(PROJECT_ROOT)
    compile_sources()

    version = get_version()
    zip_name = f"{APP_NAME}-v{version}-source.zip"
    zip_path = PROJECT_ROOT / zip_name
    if zip_path.exists():
        zip_path.unlink()

    print("Building " + zip_name + "...")
    count = 0
    archive_root = APP_NAME
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirs, files in os.walk(PROJECT_ROOT):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for filename in files:
                file_path = Path(dirpath) / filename
                rel = str(file_path.relative_to(PROJECT_ROOT))
                if should_exclude(rel):
                    continue
                zf.write(file_path, str(Path(archive_root) / rel))
                count += 1

    kb = zip_path.stat().st_size / 1024
    print(f"Done: {zip_name} ({count} files, {kb:.0f} KB)")
    return zip_path


if __name__ == "__main__":
    build()

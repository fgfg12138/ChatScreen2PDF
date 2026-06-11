#!/usr/bin/env python3
"""
build_release.py - Build source release zip.
Usage: python scripts/build_release.py
"""

import os
import re
import sys
import zipfile
from pathlib import Path

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".git", "output", "temp", "logs", ".mypy_cache", "build", "dist", "resources"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".zip"}
EXCLUDE_FILES = {"dedup_hash.py"}


def get_version():
    vf = Path(__file__).resolve().parent.parent / "__version__.py"
    m = re.search(r'"([^"]+)"', vf.read_text(encoding="utf-8"))
    if m:
        return m.group(1)
    raise RuntimeError("Cannot parse version")


def should_exclude(rel: str) -> bool:
    parts = Path(rel).parts
    for p in parts:
        if p in EXCLUDE_DIRS:
            return True
    if Path(rel).suffix in EXCLUDE_SUFFIXES:
        return True
    if Path(rel).name in EXCLUDE_FILES:
        return True
    return False


def build():
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)

    import py_compile
    errors = []
    for py in root.rglob("*.py"):
        rel = py.relative_to(root)
        if should_exclude(str(rel)):
            continue
        try:
            py_compile.compile(str(py), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(str(e))
    if errors:
        for e in errors:
            print("Compile error:", e)
        sys.exit(1)
    print("compileall OK")

    ver = get_version()
    zip_name = "ChatScreen2PDF-v" + ver + "-source.zip"
    zip_path = root / zip_name

    print("Building " + zip_name + "...")
    n = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                fp = Path(dirpath) / f
                rel = str(fp.relative_to(root))
                if should_exclude(rel):
                    continue
                zf.write(fp, "chatScreen2pdf/" + rel)
                n += 1

    kb = zip_path.stat().st_size / 1024
    print("Done: " + zip_name + " (" + str(n) + " files, " + str(round(kb)) + " KB)")
    return zip_path

if __name__ == "__main__":
    build()

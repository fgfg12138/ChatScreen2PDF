"""
web_app.py - Framescreen2PDF local Web entry.

Start the local service and open the browser automatically.
Usage:
    python web_app.py
"""

import sys
import threading
import webbrowser
import os
from pathlib import Path

# Ensure the project root is importable when frozen by PyInstaller.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_config import APP_NAME, APP_VERSION  # noqa: E402
from web.routes import app  # noqa: E402,F401

HOST = "127.0.0.1"
PORT = 18766

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _open_browser():
    """Open the browser after uvicorn has had a moment to start."""
    import time

    time.sleep(1.5)
    url = f"http://{HOST}:{PORT}/"
    try:
        webbrowser.open(url)
        print(f"已自动打开浏览器: {url}")
    except Exception:
        print(f"请手动访问: {url}")


def main():
    print("=" * 50)
    print(f"{APP_NAME} v{APP_VERSION} - 本地 Web 服务")
    print("所有处理仅在本地完成，不上传任何数据。")
    print("=" * 50)
    print()

    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex((HOST, PORT))
    sock.close()
    if result == 0:
        print(f"错误：端口 {PORT} 已被占用。")
        print("请关闭占用该端口的程序后重试。")
        print(f"如果服务已经在运行，请访问 http://{HOST}:{PORT}/")
        sys.exit(1)

    # 恢复历史任务：浏览器关闭或程序重启后仍可下载已生成的文件
    from web.routes import init_job_persistence
    init_job_persistence()

    url = f"http://{HOST}:{PORT}/"
    print(f"启动服务: {url}")
    print("按 Ctrl+C 停止服务")
    print()

    t = threading.Thread(target=_open_browser, daemon=True)
    t.start()

    import uvicorn

    uvicorn.run(
        "web.routes:app",
        host=HOST,
        port=PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()

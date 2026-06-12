"""
web_app.py — ChatScreen2PDF Web 服务入口。

启动本地服务并自动打开浏览器。
Usage:
    python web_app.py
"""

import logging
import sys
import threading
import webbrowser
from pathlib import Path

# 显式导入确保 PyInstaller 打包所有依赖
from web.routes import app  # noqa: F401

# 确保项目在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

HOST = "127.0.0.1"
PORT = 18766


def _open_browser():
    """延迟打开浏览器，等待服务就绪。"""
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
    print("ChatScreen2PDF v1.0.0-ocr-ready — 本地 Web 服务")
    print("所有处理仅在本地完成，不上传任何数据")
    print("=" * 50)
    print()

    # 检测端口是否被占用
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex((HOST, PORT))
    sock.close()
    if result == 0:
        print(f"错误：端口 {PORT} 已被占用。")
        print(f"请关闭占用该端口的程序后重试。")
        print(f"如果服务已在运行，请访问 http://{HOST}:{PORT}/")
        sys.exit(1)

    url = f"http://{HOST}:{PORT}/"
    print(f"启动服务: {url}")
    print("按 Ctrl+C 停止服务")
    print()

    # 启动浏览器线程
    t = threading.Thread(target=_open_browser, daemon=True)
    t.start()

    # 启动 uvicorn 服务
    import uvicorn
    uvicorn.run(
        "web.routes:app",
        host=HOST,
        port=PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()

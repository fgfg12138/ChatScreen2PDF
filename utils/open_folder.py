"""跨平台打开文件夹。"""

import os
import platform
import subprocess
from pathlib import Path


def open_folder(path: Path) -> tuple:
    """
    在文件管理器中打开指定目录。
    返回 (True, "") 成功，(False, "错误原因") 失败。
    """
    if not path.exists():
        return False, "目录不存在: " + str(path)
    if not path.is_dir():
        return False, "路径不是目录: " + str(path)

    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(str(path))
        elif system == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True, ""
    except Exception as e:
        return False, "打开失败: " + str(e)

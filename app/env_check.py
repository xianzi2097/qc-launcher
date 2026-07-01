"""
QC Launcher — 环境检测
检测系统是否安装了 Python / 便携 Python。
"""

import subprocess
import os


def _run_cmd(cmd, timeout=3):
    """运行命令并返回 stdout 第一行，失败返回 None"""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.stdout.strip()
    except Exception:
        return None


def check_python():
    """检测系统 Python（--version 很快，秒出）"""
    import sys
    # 直接用当前运行的 Python，避免 where 搜全盘
    if hasattr(sys, "executable"):
        py_path = sys.executable
        output = _run_cmd([py_path, "--version"], timeout=3)
        if output and output.startswith("Python"):
            return {"ok": True, "version": output, "path": py_path}
    # fallback: 尝试 python 命令
    output = _run_cmd(["python", "--version"], timeout=3)
    if output and output.startswith("Python"):
        return {"ok": True, "version": output, "path": "python"}
    return {"ok": False, "version": "", "path": ""}


def check_portable_python(launcher_dir):
    """检测便携 Python（runtime/python/python.exe）"""
    portable_py = os.path.join(launcher_dir, "python", "python.exe")
    if not os.path.exists(portable_py):
        return {"ok": False, "version": "", "message": "便携 Python 未安装"}
    output = _run_cmd([portable_py, "--version"], timeout=3)
    version = output if output else "Python"
    # 检查能否导入 fastapi
    out = _run_cmd([portable_py, "-c", "import fastapi; print(fastapi.__version__)"], timeout=3)
    if out:
        return {"ok": True, "version": f"{version} (fastapi {out})", "message": "已就绪 🍊"}
    return {"ok": True, "version": version, "message": "fastapi 未安装"}

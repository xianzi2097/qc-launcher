"""
QC Launcher v0.9.6
CodeNova — 全功能桌面启动器
"""

import sys
import os
import subprocess

# ── 使用 DirectWrite 渲染字体（ClearType，贴近 Word 观感）必须在 import PySide6 之前 ──
os.environ["QT_FONT_ENGINE_DIRECTWRITE"] = "1"

_LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
_VENV_PYTHON = os.path.join(_LAUNCHER_DIR, ".venv", "Scripts", "python.exe")

# ── 强制使用虚拟环境 ──
if sys.executable.lower() != os.path.abspath(_VENV_PYTHON).lower():
    if os.path.exists(_VENV_PYTHON):
        subprocess.run([_VENV_PYTHON] + sys.argv)
    else:
        input("未找到虚拟环境，请先运行 python -m venv .venv")
    sys.exit()

sys.path.insert(0, _LAUNCHER_DIR)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt, QTimer
import qtawesome

from app.gui import MainWindow


def _make_orange_icon():
    """品牌图标（lucide rocket，蓝）"""
    return qtawesome.icon("fa6s.rocket", color="#2563eb")


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 9))
    app.setWindowIcon(_make_orange_icon())

    window = MainWindow()
    # Keep the logical window inside the current work area on high-DPI displays.
    available = app.primaryScreen().availableGeometry()
    target_width = min(window.width(), max(window.minimumWidth(), available.width() - 32))
    target_height = min(window.height(), max(window.minimumHeight(), available.height() - 72))
    window.resize(target_width, target_height)
    window.move(
        available.left() + (available.width() - window.width()) // 2,
        available.top() + (available.height() - window.height()) // 2,
    )
    window.show()
    if "--auto-start" in sys.argv:
        # 一键启动：开窗即拉服务（等价点击 🟢），供脚本/远程协助/开机任务使用
        QTimer.singleShot(800, window._toggle_services)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

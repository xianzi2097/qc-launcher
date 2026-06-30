"""
QC Launcher v1.0
青橙 Studio — 全功能桌面启动器
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QPixmap, QPainter, QIcon
from PySide6.QtCore import Qt, QRect

from app.gui import MainWindow


def _make_orange_icon():
    """用 emoji 画图标"""
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    font = QFont("Segoe UI Emoji", 42)
    p.setFont(font)
    p.drawText(QRect(0, 0, 64, 64), Qt.AlignCenter, "🍊")
    p.end()
    return QIcon(pix)


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 9))
    app.setWindowIcon(_make_orange_icon())

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

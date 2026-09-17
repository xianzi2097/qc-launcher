"""
CodeNova Launcher — 主窗口
"""
import os
import re
import sys
import socket
import subprocess
import threading
import time
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QProgressBar, QSizePolicy,
    QRadioButton, QLineEdit, QPushButton, QTextEdit,
    QStatusBar, QCheckBox, QMessageBox, QApplication,
    QGraphicsOpacityEffect, QToolButton,
)
from PySide6.QtCore import (
    Qt, QTimer, Signal, QUrl, QPropertyAnimation, QEasingCurve, QRectF, QSize,
)
from PySide6.QtGui import QFont, QDesktopServices, QPainter, QColor

from .config import get_paths, load_config, save_config
from .system_info import get_cpu_info, get_memory_info, get_disk_info
from .styles import (
    C_GRAY,
    LAUNCHER_BG, LAUNCHER_SURFACE, LAUNCHER_SURFACE_SOFT,
    LAUNCHER_TEXT, LAUNCHER_TEXT_SECONDARY, LAUNCHER_MUTED,
    LAUNCHER_BORDER, LAUNCHER_BLUE, LAUNCHER_GREEN,
    LAUNCHER_ORANGE, LAUNCHER_RED, LAUNCHER_CARD,
    LAUNCHER_INPUT, LAUNCHER_SEGMENT,
    LAUNCHER_PRIMARY_GREEN, LAUNCHER_PRIMARY_RED,
    LAUNCHER_SECONDARY_BUTTON, LAUNCHER_LOG_STYLE,
)
import psutil
import qtawesome as qta

# FastAPI 内部端口（Caddy 反向代理指向此端口，占用时可改）
FASTAPI_PORT = "8000"


class ElidedLabel(QLabel):
    """Single-line label that preserves its full text in a tooltip."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setText(text)

    def setText(self, text):
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._update_elision()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elision()

    def _update_elision(self):
        width = max(0, self.width() - 2)
        shown = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, width
        )
        QLabel.setText(self, shown)


class ResourceMeter(QWidget):
    """Compact flat resource indicator used for CPU, memory and disk."""

    def __init__(self, title, icon=None, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(118)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(6)
        if icon:
            icon_label = QLabel()
            icon_label.setPixmap(qta.icon(icon, color=LAUNCHER_TEXT).pixmap(14, 14))
            head.addWidget(icon_label)
        title_label = QLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Normal))
        title_label.setStyleSheet(f"color: {LAUNCHER_TEXT};")
        self.percent_label = QLabel("0%")
        self.percent_label.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        self.percent_label.setStyleSheet(f"color: {LAUNCHER_GREEN};")
        head.addWidget(title_label)
        head.addStretch()
        head.addWidget(self.percent_label)
        layout.addLayout(head)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        layout.addWidget(self.bar)

        self.detail_label = ElidedLabel()
        self.detail_label.setFont(QFont("Consolas", 8))
        self.detail_label.setStyleSheet(f"color: {LAUNCHER_TEXT_SECONDARY};")
        layout.addWidget(self.detail_label)

        self.sub_label = ElidedLabel()
        self.sub_label.setFont(QFont("Microsoft YaHei", 8))
        self.sub_label.setStyleSheet(f"color: {LAUNCHER_MUTED};")
        layout.addWidget(self.sub_label)
        self.set_value(0)

    def set_value(self, pct, text="", sub_text="", percent_text=None):
        value = int(max(0, min(100, pct)))
        color = LAUNCHER_GREEN if value < 50 else LAUNCHER_ORANGE if value < 80 else LAUNCHER_RED
        self.percent_label.setText(percent_text if percent_text is not None else f"{value}%")
        self.percent_label.setStyleSheet(f"color: {color};")
        self.bar.setValue(value)
        self.bar.setStyleSheet(f"""
            QProgressBar {{ border: none; border-radius: 3px; background: #e8edf2; }}
            QProgressBar::chunk {{ border-radius: 3px; background: {color}; }}
        """)
        self.detail_label.setText(text)
        self.sub_label.setText(sub_text)


class ToggleSwitch(QCheckBox):
    """Compact painted switch with a text label."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(176)
        self.setFixedHeight(24)

    def sizeHint(self):
        return QSize(190, 24)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track = QRectF(0, 3, 34, 18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(LAUNCHER_GREEN if self.isChecked() else "#d7dfe6"))
        painter.drawRoundedRect(track, 9, 9)

        knob_x = 18 if self.isChecked() else 2
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(knob_x, 5, 14, 14))

        painter.setPen(QColor(LAUNCHER_TEXT_SECONDARY))
        painter.setFont(QFont("Microsoft YaHei", 8))
        painter.drawText(
            QRectF(44, 0, self.width() - 44, self.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )
        painter.end()


class MainWindow(QMainWindow):
    """QC Launcher 主窗口"""

    log_signal = Signal(str)
    status_signal = Signal(dict)
    msgbox_signal = Signal(str, str, str)  # type, title, message
    services_started_signal = Signal()  # 服务启动完成 → 主线程更新 UI

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CodeNova Launcher  v0.9.7")
        self.setMinimumSize(960, 680)
        self.resize(1353, 1046)

        self.paths = get_paths()
        self.config = load_config(self.paths)
        self.fastapi_process = None
        self.caddy_process = None
        self.fastapi_pid = None
        self.caddy_pid = None
        self._fastapi_port = int(FASTAPI_PORT)
        self._caddy_ports = []        # Caddyfile 里解析的实际端口，启动成功才记录
        self._caddy_ok = False
        self.running = False
        self._user_stopped = False  # 用户主动停止时为 True，抑制「异常退出」误报
        self._animations = []
        # 网速监测状态
        self._prev_net = None
        self._prev_net_ts = None
        self._link_speed_mbps = 0

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_services)
        self.poll_timer.setInterval(2000)

        # 硬件定时刷新（每 3 秒）
        self.hw_timer = QTimer(self)
        self.hw_timer.timeout.connect(self._refresh_hardware)
        self.hw_timer.setInterval(3000)

        # 信号连接
        self.log_signal.connect(self._append_log)
        self.status_signal.connect(self._update_hardware)
        self.msgbox_signal.connect(self._show_msgbox)
        self.services_started_signal.connect(self._on_services_started)

        self._build_ui()
        self._update_component_status(False, False, idle=True)
        self._update_ui_state()
        # 延迟检测硬件
        QTimer.singleShot(200, self._run_hardware_check)
        # 1.5 秒后启动定时刷新（等首次检测完成）
        QTimer.singleShot(1500, self.hw_timer.start)

    # ============================================================
    #  UI
    # ============================================================

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("launcherRoot")
        central.setStyleSheet(f"QWidget#launcherRoot {{ background: {LAUNCHER_BG}; }}")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(22, 14, 22, 8)
        main_layout.setSpacing(10)

        main_layout.addLayout(self._build_header())

        body_row = QHBoxLayout()
        body_row.setSpacing(10)

        # 左列：服务状态 + （系统资源 2×2 ｜ 数据工具 并排）
        left_col = QVBoxLayout()
        left_col.setSpacing(10)
        left_col.addWidget(self._build_service_panel())
        resources_row = QHBoxLayout()
        resources_row.setSpacing(10)
        resources_row.addWidget(self._build_hardware_panel(), 1)
        resources_row.addWidget(self._build_tools_panel())
        left_col.addLayout(resources_row)
        left_col.addStretch()
        body_row.addLayout(left_col, 58)

        # 右列：启动模式
        body_row.addWidget(self._build_control_panel(), 42)
        main_layout.addLayout(body_row)

        main_layout.addWidget(self._build_log_panel(), 1)
        self._build_status_bar()

    def _build_header(self):
        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 2, 2)

        logo = QLabel()
        logo.setPixmap(qta.icon("fa6s.rocket", color=LAUNCHER_BLUE).pixmap(30, 30))
        row.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title = QLabel("CodeNova 控制面板")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {LAUNCHER_TEXT};")
        title_col.addWidget(title)
        row.addLayout(title_col)
        row.addStretch()
        return row

    def _make_card(self, min_height=0, max_height=16777215):
        card = QFrame()
        card.setObjectName("flatCard")
        card.setStyleSheet(LAUNCHER_CARD)
        if min_height:
            card.setMinimumHeight(min_height)
        card.setMaximumHeight(max_height)
        return card

    def _title_label(self, text):
        label = QLabel(text)
        label.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        label.setStyleSheet(f"color: {LAUNCHER_TEXT};")
        return label

    def _muted_label(self, text):
        label = QLabel(text)
        label.setFont(QFont("Microsoft YaHei", 8))
        label.setStyleSheet(f"color: {LAUNCHER_MUTED};")
        return label

    def _build_service_panel(self):
        card = self._make_card(180, 240)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        left_col = QVBoxLayout()
        left_col.setSpacing(6)
        left_col.addWidget(self._title_label("服务状态"))

        component_row = QHBoxLayout()
        component_row.setSpacing(6)
        self.fastapi_chip = QToolButton()
        self.caddy_chip = QToolButton()
        for chip, ico in (
            (self.fastapi_chip, "fa6s.server"),
            (self.caddy_chip, "fa6s.globe"),
        ):
            chip.setFont(QFont("Microsoft YaHei", 8))
            chip.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            chip.setCursor(Qt.CursorShape.ArrowCursor)
            chip.setAutoRaise(True)
            chip.setIcon(qta.icon(ico, color=LAUNCHER_TEXT_SECONDARY, scale_factor=0.8))
            chip.setIconSize(QSize(13, 13))
            chip.setStyleSheet(
                f"QToolButton {{ color: {LAUNCHER_TEXT_SECONDARY}; background: {LAUNCHER_SURFACE_SOFT}; "
                f"border: 1px solid #e8edf2; border-radius: 6px; padding: 5px 10px; }}"
                "QToolButton:hover { background: #edf3f8; }"
            )
            component_row.addWidget(chip)
        component_row.addStretch()
        left_col.addLayout(component_row)

        self.service_hint = self._muted_label("服务器尚未启动，请点击右侧按钮启动")
        left_col.addWidget(self.service_hint)

        top_row.addLayout(left_col)
        top_row.addStretch()
        # 电源按钮（大，垂直对齐「标题 + FastAPI/Caddy」两行）
        self.btn_toggle = QPushButton()
        self.btn_toggle.setFixedSize(70, 70)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setToolTip("启动服务")
        self.btn_toggle.setIcon(qta.icon("fa6s.power-off", color="#ffffff"))
        self.btn_toggle.setIconSize(QSize(34, 34))
        self.btn_toggle.setStyleSheet(LAUNCHER_PRIMARY_GREEN)
        self.btn_toggle.clicked.connect(self._toggle_services)
        top_row.addWidget(self.btn_toggle)
        layout.addLayout(top_row)

        address_surface = QFrame()
        address_surface.setObjectName("addressSurface")
        address_surface.setStyleSheet(f"""
            QFrame#addressSurface {{
                background: {LAUNCHER_SURFACE_SOFT};
                border: 1px solid #e7ecf1;
                border-radius: 7px;
            }}
        """)
        address_layout = QVBoxLayout(address_surface)
        address_layout.setContentsMargins(12, 6, 8, 7)
        address_layout.setSpacing(3)
        address_layout.addWidget(self._muted_label("访问地址"))

        address_row = QHBoxLayout()
        address_row.setSpacing(6)
        self.addr_value = ElidedLabel("服务未启动")
        self.addr_value.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        self.addr_value.setStyleSheet(f"color: {LAUNCHER_MUTED};")
        self.addr_value.setTextInteractionFlags(
            self.addr_value.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        address_row.addWidget(self.addr_value, 1)

        self.btn_copy_addr = QPushButton("复制")
        self.btn_open_addr = QPushButton("打开")
        for button, ico in (
            (self.btn_copy_addr, "fa6s.copy"),
            (self.btn_open_addr, "fa6s.up-right-from-square"),
        ):
            button.setFixedWidth(62)
            button.setIcon(qta.icon(ico, color=LAUNCHER_TEXT, scale_factor=0.75))
            button.setIconSize(QSize(12, 12))
            button.setStyleSheet(LAUNCHER_SECONDARY_BUTTON)
            button.setEnabled(False)
        self.btn_copy_addr.clicked.connect(self._copy_address)
        self.btn_open_addr.clicked.connect(self._open_address)
        address_row.addWidget(self.btn_copy_addr)
        address_row.addWidget(self.btn_open_addr)
        address_layout.addLayout(address_row)
        layout.addWidget(address_surface)
        return card

    def _build_hardware_panel(self):
        card = self._make_card(196, 216)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 10, 18, 12)
        layout.setSpacing(6)
        layout.addWidget(self._title_label("系统资源"))

        grid = QGridLayout()
        grid.setSpacing(12)
        self.cpu_meter = ResourceMeter("CPU", icon="fa6s.microchip")
        self.mem_meter = ResourceMeter("内存", icon="fa6s.memory")
        self.disk_meter = ResourceMeter("磁盘", icon="fa6s.hard-drive")
        self.net_meter = ResourceMeter("网速", icon="fa6s.wifi")
        grid.addWidget(self.cpu_meter, 0, 0)
        grid.addWidget(self.mem_meter, 0, 1)
        grid.addWidget(self.disk_meter, 1, 0)
        grid.addWidget(self.net_meter, 1, 1)
        # 两行均分，内容填满整卡高度，与右侧数据工具卡平齐
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        layout.addLayout(grid, 1)
        return card

    def _build_control_panel(self):
        card = self._make_card(300)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(7)

        title_row = QHBoxLayout()
        title_row.addWidget(self._title_label("启动模式"))
        title_row.addStretch()
        title_row.addWidget(self._muted_label("单进程"))
        layout.addLayout(title_row)

        segment = QFrame()
        segment_layout = QHBoxLayout(segment)
        segment_layout.setContentsMargins(0, 0, 0, 0)
        segment_layout.setSpacing(6)
        self.radio_local = QRadioButton("局域网")
        self.radio_domain = QRadioButton("域名")
        radio_style = """
            QRadioButton { spacing: 6px; }
            QRadioButton::indicator {
                width: 12px;
                height: 12px;
            }
        """
        for radio in (self.radio_local, self.radio_domain):
            radio.setFont(QFont("Microsoft YaHei", 10))
            radio.setStyleSheet(radio_style)
            segment_layout.addWidget(radio)
        segment_layout.addStretch()
        self.radio_local.setChecked(True)
        self.radio_local.toggled.connect(self._on_mode_changed)
        layout.addWidget(segment)

        self.local_address_label = self._muted_label("局域网地址")
        layout.addWidget(self.local_address_label)
        local_row = QHBoxLayout()
        local_row.setSpacing(6)
        self.local_addr = QLineEdit("http://localhost")
        self.local_addr.setReadOnly(True)
        self.local_addr.setFont(QFont("Consolas", 11))
        self.local_addr.setStyleSheet(LAUNCHER_INPUT)
        self.local_port_sep = QLabel(":")
        self.local_port_sep.setStyleSheet(f"color: {LAUNCHER_TEXT_SECONDARY};")
        self.port_input = QLineEdit("80")
        self.port_input.setFont(QFont("Consolas", 11))
        self.port_input.setFixedWidth(66)
        self.port_input.setStyleSheet(LAUNCHER_INPUT)
        local_row.addWidget(self.local_addr, 1)
        local_row.addWidget(self.local_port_sep)
        local_row.addWidget(self.port_input)
        layout.addLayout(local_row)

        self.domain_address_label = self._muted_label("域名地址")
        layout.addWidget(self.domain_address_label)
        domain_row = QHBoxLayout()
        domain_row.setSpacing(6)
        self.domain_input = QLineEdit()
        raw = self.config.get("domain", "")
        while raw.startswith("https://"):
            raw = raw[8:]
        self.domain_input.setText(raw)
        self.domain_input.setPlaceholderText("codenova.cn")
        self.domain_input.setFont(QFont("Consolas", 11))
        self.domain_input.setStyleSheet(LAUNCHER_INPUT)
        self.domain_port_sep = QLabel(":")
        self.domain_port_sep.setStyleSheet(f"color: {LAUNCHER_MUTED};")
        self.domain_port_input = QLineEdit("443")
        self.domain_port_input.setFont(QFont("Consolas", 11))
        self.domain_port_input.setFixedWidth(66)
        self.domain_port_input.setStyleSheet(LAUNCHER_INPUT)
        domain_row.addWidget(self.domain_input, 1)
        domain_row.addWidget(self.domain_port_sep)
        domain_row.addWidget(self.domain_port_input)
        layout.addLayout(domain_row)

        # ── Judge0 地址（可选） ──
        # Judge0 就是一个地址 + 端口，不分本地/公网模式，统一默认远程公网隧道
        judge0_label = self._muted_label("Judge0 地址（可选，留空不启用）")
        layout.addWidget(judge0_label)
        judge0_row = QHBoxLayout()
        judge0_row.setSpacing(6)
        # 优先用用户保存过的地址；没保存过用远程公网隧道默认值
        raw_j0 = self.config.get("judge0_address", "")
        j0_parts = raw_j0.split(":", 1) if raw_j0 else ["", ""]
        self.judge0_input = QLineEdit(j0_parts[0])
        self.judge0_input.setPlaceholderText("例：38.76.216.46 或 192.168.2.158")
        self.judge0_input.setFont(QFont("Consolas", 11))
        self.judge0_input.setStyleSheet(LAUNCHER_INPUT)
        self.judge0_port_sep = QLabel(":")
        self.judge0_port_sep.setStyleSheet(f"color: {LAUNCHER_MUTED};")
        self.judge0_port_input = QLineEdit(j0_parts[1] if len(j0_parts) > 1 else "")
        self.judge0_port_input.setPlaceholderText("端口")
        self.judge0_port_input.setFont(QFont("Consolas", 11))
        self.judge0_port_input.setFixedWidth(66)
        self.judge0_port_input.setStyleSheet(LAUNCHER_INPUT)
        judge0_row.addWidget(self.judge0_input, 1)
        judge0_row.addWidget(self.judge0_port_sep)
        judge0_row.addWidget(self.judge0_port_input)
        layout.addLayout(judge0_row)

        # 分割线
        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"background: {LAUNCHER_BORDER};")
        layout.addWidget(separator)

        footer = QHBoxLayout()
        self.auto_backup_check = ToggleSwitch("启动前创建数据快照")
        self.auto_backup_check.setChecked(True)
        footer.addWidget(self.auto_backup_check)
        footer.addStretch()
        layout.addLayout(footer)

        layout.addStretch()

        self._on_mode_changed()
        return card

    def _build_tools_panel(self):
        card = self._make_card(196, 216)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(6)
        tools_title = self._title_label("数据工具")
        tools_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(tools_title)
        layout.addSpacing(8)  

        self.btn_register = QPushButton("账号注册")
        self.btn_manage = QPushButton("账号管理")
        self.btn_backup = QPushButton("备份数据")
        self.btn_restore = QPushButton("恢复数据")
        buttons = (self.btn_register, self.btn_manage, self.btn_backup, self.btn_restore)
        icons = ("fa6s.user-plus", "fa6s.users", "fa6s.database", "fa6s.rotate-left")
        for button, ico in zip(buttons, icons):
            button.setFont(QFont("Microsoft YaHei", 10))
            button.setMinimumWidth(76)
            button.setMinimumHeight(40)
            button.setIcon(qta.icon(ico, color=LAUNCHER_TEXT, scale_factor=1.0))
            button.setIconSize(QSize(14, 14))
            button.setStyleSheet(LAUNCHER_SECONDARY_BUTTON.replace("font-weight: 600;", "font-weight: 400;"))
            # 一列竖排（上往下），整体靠上，底部留白
            layout.addWidget(button)
        layout.addStretch()

        self.btn_register.clicked.connect(lambda: self._open_register("register"))
        self.btn_manage.clicked.connect(lambda: self._open_register("manage"))
        self.btn_backup.clicked.connect(self._open_backup)
        self.btn_restore.clicked.connect(self._open_restore)
        return card

    def _build_log_panel(self):
        card = self._make_card(150)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 10, 16, 14)
        layout.setSpacing(7)

        head = QHBoxLayout()
        head.addWidget(self._title_label("运行日志"))
        head.addStretch()
        self.btn_clear_log = QPushButton("清空")
        self.btn_clear_log.setFixedWidth(62)
        self.btn_clear_log.setIcon(qta.icon("fa6s.eraser", color=LAUNCHER_TEXT, scale_factor=0.75))
        self.btn_clear_log.setIconSize(QSize(12, 12))
        self.btn_clear_log.setStyleSheet(LAUNCHER_SECONDARY_BUTTON)
        self.btn_clear_log.clicked.connect(lambda: self.log_text.clear())
        head.addWidget(self.btn_clear_log)
        layout.addLayout(head)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.log_text.setStyleSheet(LAUNCHER_LOG_STYLE)
        layout.addWidget(self.log_text)
        return card

    def _build_status_bar(self):
        status = QStatusBar()
        status.setFont(QFont("Microsoft YaHei", 9))
        status.setStyleSheet(f"""
            QStatusBar {{ background: {LAUNCHER_BG}; color: {LAUNCHER_TEXT_SECONDARY}; }}
            QStatusBar::item {{ border: none; }}
        """)

        # 服务器整体状态（未启动 / 运行中 / 部分运行），替代原 FastAPI/Caddy 指示灯
        self.status_light = QLabel("●")
        self.status_light.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.status_light.setStyleSheet(f"color: {C_GRAY};")
        status.addPermanentWidget(self.status_light)

        self.status_text = QLabel("未启动")
        self.status_text.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        self.status_text.setStyleSheet(f"color: {LAUNCHER_TEXT_SECONDARY};")
        status.addPermanentWidget(self.status_text)
        status.addPermanentWidget(self.status_text)

        self.setStatusBar(status)

    def _on_mode_changed(self):
        local = self.radio_local.isChecked()
        self.local_addr.setEnabled(local)
        self.port_input.setEnabled(local)
        self.domain_input.setEnabled(not local)
        self.domain_port_input.setEnabled(not local)
        active = LAUNCHER_TEXT_SECONDARY
        inactive = LAUNCHER_MUTED
        self.local_address_label.setStyleSheet(f"color: {active if local else inactive};")
        self.domain_address_label.setStyleSheet(f"color: {inactive if local else active};")
        self.local_port_sep.setStyleSheet(f"color: {active if local else inactive};")
        self.domain_port_sep.setStyleSheet(f"color: {inactive if local else active};")
        # Judge0 地址不分模式，切模式不联动 Judge0 输入框

    def _copy_address(self):
        address = self.addr_value._full_text.strip()
        if not self.btn_copy_addr.isEnabled() or not address.startswith(("http://", "https://")):
            return
        QApplication.clipboard().setText(address)
        self.btn_copy_addr.setText("已复制")
        QTimer.singleShot(1200, lambda: self.btn_copy_addr.setText("复制"))

    def _open_address(self):
        address = self.addr_value._full_text.strip()
        if self.btn_open_addr.isEnabled() and address.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(address))

    def _set_address(self, text, enabled=False):
        self.addr_value.setText(text)
        self.addr_value.setStyleSheet(
            f"color: {LAUNCHER_GREEN if enabled else LAUNCHER_MUTED};"
        )
        self.btn_copy_addr.setEnabled(enabled)
        self.btn_open_addr.setEnabled(enabled)
        self._fade_widget(self.addr_value)

    def _fade_widget(self, widget):
        effect = widget.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(160)
        animation.setStartValue(0.35)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animations.append(animation)
        animation.finished.connect(lambda: self._animations.remove(animation) if animation in self._animations else None)
        animation.start()

    # ============================================================
    #  日志
    # ============================================================

    def log(self, msg):
        self.log_signal.emit(msg)

    def _append_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {msg}")
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def _show_msgbox(self, type_: str, title: str, message: str):
        """在主线程显示消息框（通过信号调用）"""
        if type_ == "info":
            QMessageBox.information(self, title, message)
        elif type_ == "error":
            QMessageBox.critical(self, title, message)

    # ============================================================
    #  环境检测
    # ============================================================

    def _run_hardware_check(self):
        threading.Thread(target=self._do_hardware_check, daemon=True).start()

    def _refresh_hardware(self):
        """轻量刷新硬件数据（每 3 秒）"""
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        try:
            cpu_pct = psutil.cpu_percent(interval=0.5)
        except Exception:
            cpu_pct = 0
        try:
            mem = get_memory_info()
        except Exception:
            mem = {"total_gb": 0, "available_gb": 0, "percent": 0}
        try:
            disk = get_disk_info(self.paths["data_disk"])
        except Exception:
            disk = {"total_gb": 0, "free_gb": 0, "percent": 0}
        net_down, net_up, net_pct = self._sample_net_speed()
        self.status_signal.emit({
            "cpu_pct": cpu_pct,
            "mem_total": f"{mem['total_gb']} GB",
            "mem_detail": f"可用 {mem['available_gb']} GB",
            "mem_pct": mem["percent"],
            "disk_total": f"{disk['total_gb']} GB",
            "disk_detail": f"可用 {disk['free_gb']} GB",
            "disk_pct": disk["percent"],
            "net_down": net_down,
            "net_up": net_up,
            "net_pct": net_pct,
        })

    def _sample_net_speed(self):
        """采样实时网速（两次计数差值）。返回 (下载, 上传, 占网卡带宽百分比)"""
        try:
            now = time.time()
            io = psutil.net_io_counters()
            if self._prev_net is None or not self._prev_net_ts:
                self._prev_net = io
                self._prev_net_ts = now
                return "0 KB/s", "0 KB/s", 0.0
            dt = now - self._prev_net_ts
            down_kbs = (io.bytes_recv - self._prev_net.bytes_recv) / dt / 1024 if dt > 0 else 0.0
            up_kbs = (io.bytes_sent - self._prev_net.bytes_sent) / dt / 1024 if dt > 0 else 0.0
            self._prev_net = io
            self._prev_net_ts = now
        except Exception:
            return "0 KB/s", "0 KB/s", 0.0
        down = f"{down_kbs:.1f} KB/s" if down_kbs < 1024 else f"{down_kbs / 1024:.2f} MB/s"
        up = f"{up_kbs:.1f} KB/s" if up_kbs < 1024 else f"{up_kbs / 1024:.2f} MB/s"
        pct = down_kbs / 1024 / self._link_speed_mbps * 100 if self._link_speed_mbps else 0.0
        return down, up, pct

    def _do_hardware_check(self):
        try:
            cpu = get_cpu_info()
            cpu["percent"] = psutil.cpu_percent(interval=0.5)
            mem = get_memory_info()
            disk = get_disk_info(self.paths["data_disk"])
            # 主网卡协商速率（当“总带宽”参考）
            speeds = [v.speed for v in psutil.net_if_stats().values() if v.isup and v.speed]
            self._link_speed_mbps = max(speeds) if speeds else 0
        except Exception as e:
            self.log(f"[警告] 硬件检测出错: {e}")
            cpu = {"model": "获取失败", "physical_cores": 0, "logical_cores": 0, "percent": 0}
            mem = {"total_gb": 0, "available_gb": 0, "percent": 0}
            disk = {"total_gb": 0, "free_gb": 0, "percent": 0}

        self.status_signal.emit({
            "cpu_model": cpu["model"],
            "cpu_cores": f"核心: {cpu['physical_cores']}  /  线程: {cpu['logical_cores']}",
            "cpu_pct": cpu["percent"],
            "mem_total": f"{mem['total_gb']} GB",
            "mem_detail": f"可用 {mem['available_gb']} GB",
            "mem_pct": mem["percent"],
            "disk_total": f"{disk['total_gb']} GB",
            "disk_detail": f"可用 {disk['free_gb']} GB",
            "disk_pct": disk["percent"],
            "net_down": "0 KB/s",
            "net_up": "0 KB/s",
            "net_pct": 0.0,
            "net_link": f"{self._link_speed_mbps} Mbps",
        })

        self.log(
            f"硬件检测完成  |  "
            f"CPU: {cpu['logical_cores']}线程  "
            f"内存: {mem['total_gb']}GB  "
            f"磁盘: {disk['total_gb']}GB  "
            f"网卡: {self._link_speed_mbps}Mbps"
        )

    def _update_hardware(self, data):
        # CPU
        if "cpu_model" in data:
            self._cpu_model_text = data["cpu_model"]
            self._cpu_cores_text = data.get("cpu_cores", "")
        if "cpu_pct" in data:
            self.cpu_meter.set_value(
                data["cpu_pct"],
                text=getattr(self, '_cpu_model_text', ''),
                sub_text=getattr(self, '_cpu_cores_text', '')
            )
        # 内存
        if "mem_pct" in data:
            self.mem_meter.set_value(
                data["mem_pct"],
                text=data.get("mem_total", ""),
                sub_text=data.get("mem_detail", "")
            )
        # 磁盘
        if "disk_pct" in data:
            self.disk_meter.set_value(
                data["disk_pct"],
                text=data.get("disk_total", ""),
                sub_text=data.get("disk_detail", "")
            )
        # 网速
        if "net_pct" in data:
            self.net_meter.set_value(
                data["net_pct"],
                text=data.get("net_link", ""),
                sub_text=f"↑ {data.get('net_up', '')}",
                percent_text=data.get("net_down", "0")
            )

    # ============================================================
    #  服务控制
    # ============================================================

    def _update_ui_state(self):
        """根据运行状态更新指示灯和按钮"""
        if self.running:
            caddy_ok = self._caddy_ok and self.caddy_process and self.caddy_process.poll() is None
            if caddy_ok:
                self.status_light.setText("●")
                self.status_light.setStyleSheet(f"color: {LAUNCHER_GREEN};")
                self.status_text.setText("运行中")
                self.status_text.setStyleSheet("color: #24764d;")
                self.service_hint.setText("服务运行正常，可复制地址或直接在浏览器中打开")
            else:
                self.status_light.setText("●")
                self.status_light.setStyleSheet(f"color: {LAUNCHER_ORANGE};")
                self.status_text.setText("部分运行")
                self.status_text.setStyleSheet("color: #9a6414;")
                self.service_hint.setText("后端已运行，反向代理尚未就绪，请查看运行日志")
            self.btn_toggle.setToolTip("停止服务")
            self.btn_toggle.setIcon(qta.icon("fa6s.power-off", color="#ffffff"))
            self.btn_toggle.setStyleSheet(LAUNCHER_PRIMARY_RED)
        else:
            self.status_light.setText("●")
            self.status_light.setStyleSheet(f"color: {LAUNCHER_RED};")
            self.status_text.setText("未启动")
            self.status_text.setStyleSheet("color: #6f7f8e;")
            self.service_hint.setText("服务器尚未启动，请点击右侧按钮启动")
            self.btn_toggle.setToolTip("启动服务")
            self.btn_toggle.setIcon(qta.icon("fa6s.power-off", color="#ffffff"))
            self.btn_toggle.setStyleSheet(LAUNCHER_PRIMARY_GREEN)
        self.btn_toggle.setEnabled(True)
        QApplication.processEvents()

    def _toggle_services(self):
        # 瞬间锁定 UI，防止频繁点击
        self.btn_toggle.setEnabled(False)
        self.status_light.setText("●")
        self.status_light.setStyleSheet(f"color: {LAUNCHER_ORANGE};")
        self.status_text.setText("处理中")
        self.status_text.setStyleSheet("color: #9a6414;")
        self.service_hint.setText("正在切换服务状态，请稍候")
        self.btn_toggle.setToolTip("处理中...")
        self.btn_copy_addr.setEnabled(False)
        self.btn_open_addr.setEnabled(False)
        QApplication.processEvents()

        try:
            if self.running:
                self._stop_services()
            else:
                self.log("[启动] 正在启动服务...")
                self.btn_toggle.setEnabled(False)
                self.btn_toggle.setToolTip("启动中...")
                threading.Thread(target=self._start_services, daemon=True).start()
                return  # 不立即更新 UI，等启动完成后通过 _update_ui_state 刷新
        except Exception as e:
            self.log(f"[失败] 操作异常: {e}")
            import traceback
            self.log(traceback.format_exc())

        # 操作完成，恢复按钮并根据结果更新状态
        self._update_ui_state()

    def _start_services(self):
        if self.running:
            QTimer.singleShot(0, self._update_ui_state)
            return
        mode = "domain" if self.radio_domain.isChecked() else "local"
        domain = self.domain_input.text().strip() if mode == "domain" else "localhost"
        # 去掉可能残留的协议前缀
        while "://" in domain:
            domain = domain.split("://", 1)[-1]
        if mode == "domain" and not domain:
            self.log("[警告] 请输入域名")
            QTimer.singleShot(0, self._update_ui_state)
            return

        self.log(f"[启动] 正在启动服务（{'域名' if mode == 'domain' else '本地'}模式）")

        # ── 启动前自动备份（可选，默认开启） ──
        if self.auto_backup_check.isChecked():
            self.log("[备份] 启动前自动备份 data ...")
            from .backup import auto_backup_now
            backup_root = os.path.join(os.path.dirname(self.paths["data_dir"]), "backups")
            auto_backup_now(self.paths["data_dir"], backup_root, keep=14, log=self.log)

        # 只清理自己上一轮残留的进程（按 PID，不杀别人的）
        if self.caddy_pid:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(self.caddy_pid), "/T", "/F"],
                    capture_output=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass
            self.caddy_pid = None
            self.caddy_process = None
            self._caddy_ports = []
        if self.fastapi_pid:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(self.fastapi_pid), "/T", "/F"],
                    capture_output=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass
            self.fastapi_pid = None
            self.fastapi_process = None

        # 打印运行时版本
        py_exe = self.paths["runtime_python"]
        caddy_exe = self.paths["caddy_exe"]
        try:
            py_ver = subprocess.run([py_exe, "--version"], capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
            self.log(f"Python: {py_ver}")
        except Exception:
            self.log("Python: 版本获取失败")
        try:
            cv = subprocess.run([caddy_exe, "version"], capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip().split("\n")[0]
            self.log(f"Caddy: {cv}")
        except Exception:
            self.log("Caddy: 版本获取失败")

        caddy_port = self.domain_port_input.text().strip() if mode == "domain" else self.port_input.text().strip()
        if not caddy_port.isdigit():
            self.log("[警告] 端口格式不正确")
            QTimer.singleShot(0, self._update_ui_state)
            return

        # [1] 先启动后端，自动找空闲端口（8000→9000）
        self._start_fastapi()
        if self.fastapi_process is None:
            self.log("[失败] FastAPI 未就绪，取消启动 Caddy")
            QTimer.singleShot(0, self._update_ui_state)
            return
        self.log(f"FastAPI 已就绪，使用端口: {self._fastapi_port}")
        self.running = True
        self._user_stopped = False

        # [2] 再用后端真正跑起来的端口生成 Caddyfile
        self._generate_caddyfile(mode, domain, caddy_port)
        # 记住 Judge0 地址：两种模式都保存（用户手动填过就存用户的）
        j0_addr = self.judge0_input.text().strip()
        j0_port = self.judge0_port_input.text().strip()
        j0_full = f"{j0_addr}:{j0_port}" if j0_addr and j0_port else j0_addr
        save_config(self.paths, domain, j0_full)

        # [3] 启动 Caddy（失败不阻止 FastAPI 运行）
        self._caddy_ok = self._start_caddy()

        # 通过信号在主线程更新 UI
        self.services_started_signal.emit()

    def _generate_caddyfile(self, mode, domain, caddy_port):
        script = os.path.join(self.paths["caddy_dir"], "generate_caddyfile.py")
        if not os.path.exists(script):
            self.log("[警告] generate_caddyfile.py 未找到")
            return
        judge0_addr = self.judge0_input.text().strip()
        judge0_port = self.judge0_port_input.text().strip()
        judge0_full = f"{judge0_addr}:{judge0_port}" if judge0_addr and judge0_port else judge0_addr
        try:
            cmd = [sys.executable, script,
                   "server" if mode == "domain" else "local",
                   domain, str(self._fastapi_port), caddy_port]
            if judge0_full:
                cmd.append(judge0_full)
            r = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=10,
                cwd=self.paths["caddy_dir"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if r.returncode == 0:
                self.log(f"[完成] Caddyfile 已生成（{mode}模式, Caddy端口: {caddy_port}）")
            else:
                self.log(f"[警告] Caddyfile 生成出错: {r.stderr.strip()}")
        except Exception as e:
            self.log(f"[警告] Caddyfile 生成出错: {e}")
            return

    def _wait_for_port(self, host: str, port: int, timeout: int = 5) -> bool:
        """等待端口就绪，超时返回 False"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                s.connect((host, port))
                s.close()
                return True
            except (ConnectionRefusedError, OSError):
                time.sleep(0.3)
        return False

    def _start_fastapi(self):
        portable_py = self.paths.get("runtime_python", "")
        if portable_py and os.path.exists(portable_py):
            venv_py = portable_py
        else:
            venv_py = sys.executable

        # 从 _fastapi_port 开始尝试，不行就往后扫
        max_port = 9000
        for port in range(self._fastapi_port, max_port + 1):
            # 先确认端口空闲
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("127.0.0.1", port))
                s.close()
            except OSError:
                self.log(f"端口 {port} 已被占用，尝试下一个...")
                continue

            cmd = [venv_py, "-m", "uvicorn", "main:app", "--port", str(port)]
            try:
                self.fastapi_process = subprocess.Popen(
                    cmd,
                    cwd=self.paths["backend_dir"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    encoding='utf-8', errors='replace',
                )
                proc = self.fastapi_process
                self.fastapi_pid = proc.pid
                # 后台线程：读取输出到日志面板（用局部变量 proc，不怕 self.fastapi_process 被置空）
                def _watch_fastapi(p=proc):
                    for line in p.stdout:
                        self.log(f"[FastAPI] {line.strip()}")
                    rc = p.wait()
                    if rc != 0 and not self._user_stopped:
                        self.log(f"[失败] FastAPI 异常退出 (code {rc})")
                threading.Thread(target=_watch_fastapi, daemon=True).start()
                # 等待端口就绪（进程死了立即放弃，不等 10s）
                port_ok = False
                deadline = time.time() + 10
                while time.time() < deadline:
                    if proc.poll() is not None:
                        self.log(f"FastAPI 进程已退出，跳过端口 {port}")
                        break
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(0.5)
                        s.connect(("127.0.0.1", port))
                        s.close()
                        port_ok = True
                        break
                    except (ConnectionRefusedError, OSError):
                        time.sleep(0.3)
                if port_ok:
                    self._fastapi_port = port
                    self.log(f"[完成] FastAPI 已启动 (端口 {port}, 单进程, PID {self.fastapi_pid})")
                    return
                else:
                    self.log(f"[警告] 端口 {port} 未就绪，尝试下一个...")
                    if self.fastapi_process:
                        self.fastapi_process.kill()
                        self.fastapi_process.wait(timeout=3)
                        self.fastapi_process = None
                        self.fastapi_pid = None
            except Exception as e:
                self.log(f"[警告] 端口 {port} 启动异常: {e}")
                if self.fastapi_process:
                    self.fastapi_process.kill()
                    self.fastapi_process = None
                    self.fastapi_pid = None

        # 所有端口都试完了
        self.log("[失败] FastAPI 启动失败：8000~9000 全部尝试无果")
        self.msgbox_signal.emit("error", "启动失败",
            "FastAPI 启动失败，请查看日志，或联系管理员")
        self.fastapi_process = None

    @staticmethod
    def _port_busy(host: str, port: int) -> bool:
        """检测端口是否已被占用（True = 占用）"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect((host, port))
            s.close()
            return True
        except (ConnectionRefusedError, OSError):
            return False

    def _start_caddy(self) -> bool:
        """启动 Caddy，成功返回 True，失败返回 False"""
        exe = self.paths["caddy_exe"]
        cf = os.path.join(self.paths["caddy_dir"], "Caddyfile")
        if not os.path.exists(exe):
            self.log("[失败] Caddy 可执行文件未找到")
            return False
        if not os.path.exists(cf):
            self.log("[失败] Caddyfile 未找到")
            return False

        # 从 Caddyfile 里提取监听端口
        caddy_ports = []
        try:
            with open(cf, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    m = re.search(r':(\d+)\s*\{', line)
                    if m:
                        caddy_ports.append(int(m.group(1)))
        except Exception:
            pass
        if not caddy_ports:
            caddy_ports = [80]

        # 预检查：端口是否已被占用
        for cp in caddy_ports:
            if self._port_busy("127.0.0.1", cp):
                self._caddy_ports = []
                self.log(f"[失败] Caddy 端口 {cp} 已被占用，请先关闭占用该端口的程序")
                return False

        # 关键：清除代理环境变量后启动 Caddy
        # Caddy 的 reverse_proxy 遵循 Go 的 ProxyFromEnvironment，
        # 若本机开着 Clash 等代理（HTTP_PROXY/HTTPS_PROXY），
        # 出站请求会被劫持回环，导致 Judge0 等公网反向代理全部"离线"。
        caddy_env = dict(os.environ)
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            caddy_env.pop(key, None)
        caddy_env["NO_PROXY"] = "*"

        try:
            self.caddy_process = subprocess.Popen(
                [exe, "run", "--config", cf],
                cwd=self.paths["caddy_dir"],
                env=caddy_env,
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding='utf-8', errors='replace',
            )
            self.caddy_pid = self.caddy_process.pid
            # 后台线程：读取输出到日志面板
            caddy_proc = self.caddy_process  # 捕获局部引用，避免 _stop_services 置空后访问异常
            def _watch_caddy(p=caddy_proc):
                for line in p.stdout:
                    self.log(f"[Caddy] {line.strip()}")
                rc = p.wait()
                if rc != 0 and not self._user_stopped:
                    self.log(f"[失败] Caddy 异常退出 (code {rc})")
            threading.Thread(target=_watch_caddy, daemon=True).start()
            # 等待端口就绪（任何一个端口通就算成功）
            ok = False
            for cp in caddy_ports:
                if self._wait_for_port("127.0.0.1", cp, timeout=3):
                    ok = True
                    break
            if ok:
                self._caddy_ports = caddy_ports
                self.log(f"[完成] Caddy 已启动 (端口 {', '.join(str(p) for p in caddy_ports)}, PID {self.caddy_pid})")
                return True
            else:
                self._caddy_ports = []
                self.log(f"[失败] Caddy 启动失败：端口 {', '.join(str(p) for p in caddy_ports)} 未就绪")
                if self.caddy_process:
                    self.caddy_process.kill()
                    self.caddy_process.wait(timeout=3)
                self.caddy_process = None
                self.caddy_pid = None
                return False
        except Exception as e:
            self._caddy_ports = []
            self.log(f"[失败] Caddy 启动失败: {e}")
            if self.caddy_process:
                self.caddy_process.kill()
                self.caddy_process = None
            return False

    def _on_services_started(self):
        """服务启动完成后的 UI 更新（在主线程执行）"""
        # 立即更新状态指示灯，不等 poll 定时器
        fa = bool(self.fastapi_process and self.fastapi_process.poll() is None)
        ca = bool(self.caddy_process and self.caddy_process.poll() is None)
        self._update_component_status(fa, ca)

        self.poll_timer.start()
        self._set_status("running")
        self._update_ui_state()

        # ── 构造提示信息 ──
        caddy_hint = ""
        if not ca:
            caddy_hint = (
                "[警告] Caddy 反向代理未启动（80 端口可能被占用）\n"
                "学生将无法通过浏览器访问，但后端 API 已在运行。\n"
                "可尝试手动运行 Caddy 或检查端口占用。"
            )

        # 提示访问地址
        if self.radio_local.isChecked():
            port = self.port_input.text().strip() or "80"
            addr = "（未能自动检测到本机IP，请检查网络连接）"
            try:
                import socket, urllib.request, psutil
                found = []
                for name, if_addrs in psutil.net_if_addrs().items():
                    for a in if_addrs:
                        if a.family != socket.AF_INET or a.address.startswith("127."):
                            continue
                        ip = a.address
                        try:
                            req = urllib.request.urlopen(f"http://{ip}:{port}/", timeout=5)
                            if req.status == 200:
                                is_wifi = any(k in name.lower() for k in ("wi-fi","wifi","wlan","无线","802.11"))
                                found.append((0 if is_wifi else 1, ip))
                        except Exception:
                            continue
                found.sort(key=lambda x: x[0])
                if found:
                    ip = found[0][1]
                    addr = f"http://{ip}:{port}" if port != "80" else f"http://{ip}"
            except Exception:
                pass

            self._set_address(addr, enabled=addr.startswith(("http://", "https://")))
            self.log(f"[地址] 访问地址: {addr}")
            from .system_info import get_wifi_ssid
            wifi = get_wifi_ssid()
            wifi_hint = f"Wi-Fi：{wifi}\n" if wifi else ""
            if ca:
                self.msgbox_signal.emit("info", "服务已启动",
                    f"服务已成功启动！\n\n"
                    f"请同学们打开浏览器，访问：\n"
                    f"访问地址：{addr}\n"
                    f"{wifi_hint}"
                    f"（确保手机/电脑连接同一个 Wi-Fi 或交换机）")
            else:
                self.msgbox_signal.emit("info", "部分启动",
                    f"服务已启动，但 Caddy 未就绪\n\n"
                    f"后端 API 地址：{addr}\n"
                    f"{wifi_hint}"
                    f"{caddy_hint}")
        else:
            domain = self.domain_input.text().strip()
            url = f"https://{domain}"
            self._set_address(url, enabled=True)
            self.log(f"[地址] 访问地址: {url}")
            if ca:
                self.msgbox_signal.emit("info", "服务已启动",
                    f"服务已成功启动！\n\n"
                    f"请同学们打开浏览器，访问：\n"
                    f"访问地址：{url}\n")
            else:
                self.msgbox_signal.emit("info", "部分启动",
                    f"服务已启动，但 Caddy 未就绪\n\n"
                    f"后端 API 地址：{url}\n"
                    f"{caddy_hint}")

    def _stop_services(self):
        self._user_stopped = True  # 标记为主动停止，抑制 watcher 线程误报
        self.log("[停止] 正在停止服务...")
        # 只杀自己启动的进程（按 PID，精确打击）
        pids = [("Caddy", self.caddy_pid), ("FastAPI", self.fastapi_pid)]
        for name, pid in pids:
            if pid:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        capture_output=True, timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    self.log(f"{name} 已停止 (PID {pid})")
                except Exception as e:
                    self.log(f"{name} 停止失败: {e}")

        # 清理
        self.fastapi_process = None
        self.caddy_process = None
        self.fastapi_pid = None
        self.caddy_pid = None
        self._caddy_ports = []
        self._caddy_ok = False
        self.running = False
        self.poll_timer.stop()
        # 手动更新指示灯（定时器停了不会再触发 _poll_services）
        self._update_component_status(False, False, idle=True)
        self._update_ui_state()
        self._set_status("stopped")
        self.log("[完成] 服务已全部停止")

    def _poll_services(self):
        fa = bool(self.fastapi_process and self.fastapi_process.poll() is None)
        ca = bool(self.caddy_process and self.caddy_process.poll() is None)
        self._update_component_status(fa, ca, idle=not self.running)
        if not fa and not ca and self.running:
            self._stop_services()

    def _update_component_status(self, fastapi_ok, caddy_ok, idle=False):
        states = (
            (self.fastapi_chip, "FastAPI", fastapi_ok, "fa6s.server"),
            (self.caddy_chip, "Caddy", caddy_ok, "fa6s.globe"),
        )
        for chip, name, ok, ico in states:
            if ok:
                color, chip_bg, chip_border = LAUNCHER_GREEN, "#f0fdf4", "#bbf7d0"
            elif idle:
                color, chip_bg, chip_border = LAUNCHER_TEXT_SECONDARY, LAUNCHER_SURFACE_SOFT, "#e4eaf0"
            else:
                color, chip_bg, chip_border = LAUNCHER_RED, "#f9ecec", "#efd0d0"
            label = "运行中" if ok else "未运行"
            chip.setText(f"{name}  ·  {label}")
            chip.setIcon(qta.icon(ico, color=color, scale_factor=0.8))
            chip.setStyleSheet(
                f"QToolButton {{ color: {color}; background: {chip_bg}; border: 1px solid {chip_border}; "
                "border-radius: 6px; padding: 6px 10px; }"
                "QToolButton:hover { background: #edf3f8; }"
            )

    def _set_status(self, state):
        if state == "stopped":
            self._set_address("服务未启动", enabled=False)
        elif state == "running":
            # 地址会在 _on_services_started 里设置
            pass



    # ============================================================
    #  工具：批量注册 / 备份
    # ============================================================

    def _open_register(self, mode: str = "register"):
        # 后端没启动，直接拦住
        if not self.running or not self.fastapi_process or self.fastapi_process.poll() is not None:
            QMessageBox.warning(self, "服务未启动",
                "请先点击「启动服务」启动后端，再进行账号注册/管理。")
            return
        from .register import BatchRegisterDialog
        dlg = BatchRegisterDialog(parent=self, mode=mode)
        dlg.exec()

    def _open_backup(self):
        from .backup import BackupDialog
        dlg = BackupDialog(
            data_dir=self.paths["data_dir"],
            parent=self,
        )
        dlg.exec()

    def _open_restore(self):
        if self.running:
            QMessageBox.warning(self, "服运行中",
                "请先点击「停止服务」再恢复数据（否则文件被占用）。")
            return
        from .backup import RestoreDialog
        backup_root = os.path.join(os.path.dirname(self.paths["data_dir"]), "backups")
        dlg = RestoreDialog(
            data_dir=self.paths["data_dir"],
            backup_root=backup_root,
            parent=self,
        )
        dlg.exec()

    def closeEvent(self, event):
        if self.running:
            QMessageBox.warning(
                self, "服务正在运行",
                "请先点击「停止服务」再关闭启动器。",
                QMessageBox.StandardButton.Ok,
            )
            event.ignore()
        else:
            super().closeEvent(event)

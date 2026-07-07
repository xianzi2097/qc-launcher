"""
QC Launcher — 主窗口
左三圆环硬件 | 右控制中心 | 中服务器地址 |底日志
"""

import os
import re
import sys
import socket
import subprocess
import threading
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel,
    QRadioButton, QLineEdit, QPushButton, QTextEdit,
    QStatusBar, QSplitter, QCheckBox, QComboBox, QMessageBox,
)
from PySide6.QtCore import Qt, QTimer, Signal, QRect
from PySide6.QtGui import QFont, QPainter, QColor, QPen

from .config import get_paths, load_config, save_config
from .system_info import get_cpu_info, get_memory_info, get_disk_info
import psutil


# ---------- 颜色 ----------
C_GREEN = "#22c55e"
C_RED = "#ef4444"
C_GRAY = "#6b7280"
C_BORDER = "#e2e8f0"
C_BG = "#f8fafc"

# FastAPI 内部端口（Caddy 反向代理指向此端口，占用时可改）
FASTAPI_PORT = "8000"


# ============================================================
#  环形进度条控件
# ============================================================
class CircularProgress(QWidget):
    """环形进度条，中间显示百分比和标题"""

    def __init__(self, title, unit="%", parent=None):
        super().__init__(parent)
        self._title = title
        self._unit = unit
        self._value = 0
        self._text = ""
        self._sub_text = ""
        self.setFixedSize(175, 235)

    def set_value(self, pct, text="", sub_text=""):
        self._value = max(0, min(100, pct))
        self._text = text
        self._sub_text = sub_text
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w // 2, 90
        radius = 58
        pen_w = 12

        # 背景圆环
        painter.setPen(QPen(QColor("#e2e8f0"), pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(cx - radius, cy - radius, radius * 2, radius * 2, 0, 360 * 16)

        # 前景弧
        if self._value > 0:
            color = C_GREEN if self._value < 50 else "#eab308" if self._value < 80 else C_RED
            painter.setPen(QPen(QColor(color), pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            span = int(360 * self._value / 100 * 16)
            painter.drawArc(cx - radius, cy - radius, radius * 2, radius * 2, 90 * 16, -span)

        # 中间百分比 — 严格居中于圆环圆心
        painter.setPen(QColor("#1e293b"))
        font_big = QFont("Consolas", 22, QFont.Weight.Bold)
        painter.setFont(font_big)
        pct_text = f"{int(self._value)}{self._unit}"
        pr = QRect(cx - 38, cy - 18, 76, 36)
        painter.drawText(pr, Qt.AlignmentFlag.AlignCenter, pct_text)

        # 标题（圆环下方）
        painter.setPen(QColor("#64748b"))
        font_title = QFont("Microsoft YaHei", 10, QFont.Weight.Bold)
        painter.setFont(font_title)
        title_rect = self.rect().adjusted(0, cy + radius + 8, 0, 0)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._title)

        # 副文本
        if self._text or self._sub_text:
            painter.setPen(QColor("#475569"))
            font_sm = QFont("Consolas", 8)
            painter.setFont(font_sm)
            y_base = cy + radius + 32
            if self._text:
                tr = self.rect().adjusted(4, y_base, -4, 0)
                painter.drawText(tr, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._text)
            if self._sub_text:
                tr = self.rect().adjusted(4, y_base + 16, -4, 0)
                painter.drawText(tr, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._sub_text)

        painter.end()


class MainWindow(QMainWindow):
    """QC Launcher 主窗口"""

    log_signal = Signal(str)
    status_signal = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("QC Launcher  v0.9.5")
        self.setMinimumSize(960, 680)
        self.resize(1000, 720)

        self.paths = get_paths()
        self.config = load_config(self.paths)
        self.fastapi_process = None
        self.caddy_process = None
        self.fastapi_pid = None
        self.caddy_pid = None
        self.running = False

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

        self._build_ui()
        # 延迟检测硬件
        QTimer.singleShot(200, self._run_hardware_check)
        # 1.5 秒后启动定时刷新（等首次检测完成）
        QTimer.singleShot(1500, self.hw_timer.start)

    # ============================================================
    #  UI
    # ============================================================

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 10, 12, 2)
        main_layout.setSpacing(6)

        # 上: 左硬件 + 右控制 (比例 6:4)
        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.addWidget(self._build_hardware_panel())
        top_splitter.addWidget(self._build_control_panel())
        top_splitter.setSizes([520, 340])
        top_splitter.setChildrenCollapsible(False)
        main_layout.addWidget(top_splitter, 3)

        # 下: 地址栏 + 日志
        self._build_addr_bar()
        main_layout.addWidget(self.addr_bar, 0)
        main_layout.addWidget(self._build_log_panel(), 4)
        self._build_status_bar()

    def _card_style(self):
        return f"""
            QGroupBox {{
                border: 1px solid {C_BORDER};
                border-radius: 8px;
                margin-top: 12px;
                padding: 16px 12px 12px 12px;
                background: {C_BG};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #1e293b;
            }}
        """

    def _build_hardware_panel(self):
        g = QGroupBox("💻  硬件参数")
        g.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        g.setStyleSheet(self._card_style())

        layout = QHBoxLayout(g)
        layout.setContentsMargins(6, 16, 6, 6)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.cpu_circle = CircularProgress("CPU")
        self.mem_circle = CircularProgress("内存")
        self.disk_circle = CircularProgress("磁盘")

        layout.addStretch()
        layout.addWidget(self.cpu_circle)
        layout.addSpacing(8)
        layout.addWidget(self.mem_circle)
        layout.addSpacing(8)
        layout.addWidget(self.disk_circle)
        layout.addStretch()

        return g

    def _build_control_panel(self):
        g = QGroupBox("⚙️  设置")
        g.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        g.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {C_BORDER}; border-radius: 8px;
                margin-top: 12px; padding: 16px 12px 8px 12px; background: {C_BG}; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px;
                padding: 0 6px; color: #1e293b; }}
        """)

        layout = QVBoxLayout(g)
        layout.setSpacing(8)

        # ── 启动选项 ──
        layout.addWidget(QLabel("启动选项",
            font=QFont("Microsoft YaHei", 9, QFont.Weight.Bold),
            styleSheet=f"color: #64748b;"))

        # 线程（下拉框，动态 1~N）
        row = QHBoxLayout()
        row.addWidget(QLabel("⚙️  进程", font=QFont("Microsoft YaHei", 9),
                             styleSheet=f"color: #475569;"))
        self.workers_combo = QComboBox()
        max_workers = min(os.cpu_count() or 4, 16)
        for i in range(1, max_workers + 1):
            self.workers_combo.addItem(f"{i} 个进程")
        self.workers_combo.setFont(QFont("Consolas", 9))
        self.workers_combo.setFixedWidth(100)
        self.workers_combo.setStyleSheet(f"""
            QComboBox {{ border: 1px solid {C_BORDER}; border-radius: 4px;
                padding: 4px 6px; background: white; color: #1e293b; }}
        """)
        self.workers_combo.currentIndexChanged.connect(self._on_workers_changed)
        row.addWidget(self.workers_combo)
        row.addStretch()
        layout.addLayout(row)

        # Reload 模式
        self.reload_check = QCheckBox("Reload 模式")
        self.reload_check.setFont(QFont("Microsoft YaHei", 9))
        self.reload_check.setStyleSheet(f"color: #475569;")
        self.reload_check.setChecked(False)
        layout.addWidget(self.reload_check)

        # ── 启动模式 ──
        layout.addSpacing(4)
        layout.addWidget(QLabel("启动模式",
            font=QFont("Microsoft YaHei", 9, QFont.Weight.Bold),
            styleSheet=f"color: #64748b;"))

        # 本地模式行
        local_row = QHBoxLayout()
        self.radio_local = QRadioButton("本地模式")
        self.radio_local.setFont(QFont("Microsoft YaHei", 9))
        self.radio_local.setChecked(True)
        self.radio_local.toggled.connect(self._on_mode_changed)
        local_row.addWidget(self.radio_local)

        self.local_addr = QLineEdit("http://localhost")
        self.local_addr.setFont(QFont("Consolas", 9))
        self.local_addr.setReadOnly(True)
        self.local_addr.setStyleSheet(f"""
            QLineEdit {{ border: 1px solid {C_BORDER}; border-radius: 4px;
                padding: 3px 6px; background: #f1f5f9; color: #64748b; }}
        """)
        local_row.addWidget(self.local_addr, 1)

        local_row.addWidget(QLabel(":", font=QFont("Consolas", 9),
                                   styleSheet=f"color: {C_GRAY};"))
        self.port_input = QLineEdit("80")
        self.port_input.setFont(QFont("Consolas", 9))
        self.port_input.setFixedWidth(self.port_input.fontMetrics().averageCharWidth() * 5 + 14)
        self.port_input.setStyleSheet(f"""
            QLineEdit {{ border: 1px solid {C_BORDER}; border-radius: 4px;
                padding: 3px 6px; background: white; color: #1e293b; }}
        """)
        local_row.addWidget(self.port_input)
        layout.addLayout(local_row)

        # 域名模式行
        domain_row = QHBoxLayout()
        self.radio_domain = QRadioButton("域名模式")
        self.radio_domain.setFont(QFont("Microsoft YaHei", 9))
        self.radio_domain.toggled.connect(self._on_mode_changed)
        domain_row.addWidget(self.radio_domain)

        self.domain_input = QLineEdit()
        self.domain_input.setPlaceholderText("https://域名...")
        raw = self.config.get("domain", "codenova.cn")
        # 去掉可能积累的 https:// 前缀
        while raw.startswith("https://"):
            raw = raw[8:]
        self.domain_input.setText(raw)
        self.domain_input.setFont(QFont("Consolas", 9))
        self.domain_input.setStyleSheet(f"""
            QLineEdit {{ border: 1px solid {C_BORDER}; border-radius: 4px;
                padding: 3px 6px; background: white; color: #1e293b; }}
        """)
        self.domain_input.setEnabled(False)
        domain_row.addWidget(self.domain_input, 1)

        domain_row.addWidget(QLabel(":", font=QFont("Consolas", 9),
                                    styleSheet=f"color: {C_GRAY};"))
        self.domain_port_input = QLineEdit("443")
        self.domain_port_input.setFont(QFont("Consolas", 9))
        self.domain_port_input.setFixedWidth(self.domain_port_input.fontMetrics().averageCharWidth() * 5 + 14)
        self.domain_port_input.setStyleSheet(f"""
            QLineEdit {{ border: 1px solid {C_BORDER}; border-radius: 4px;
                padding: 3px 6px; background: white; color: #1e293b; }}
        """)
        self.domain_port_input.setEnabled(False)
        domain_row.addWidget(self.domain_port_input)
        layout.addLayout(domain_row)

        # ── 弹性空间将按钮推到最底 ──
        layout.addStretch()

        # ── 状态 + 控制按钮（同行） ──
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(4)

        self.status_light = QLabel("🔴")
        self.status_light.setFont(QFont("Segoe UI Emoji", 12))
        ctrl_row.addWidget(self.status_light)

        self.status_text = QLabel("已停止")
        self.status_text.setFont(QFont("Microsoft YaHei", 9))
        self.status_text.setStyleSheet("color: #94a3b8;")
        ctrl_row.addWidget(self.status_text)

        ctrl_row.addStretch()

        self.btn_toggle = QPushButton("启动服务")
        self.btn_toggle.setFont(QFont("Microsoft YaHei", 10))
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{ border: none; border-radius: 5px; padding: 6px 24px;
                background: {C_GREEN}; color: white; font-weight: bold; }}
            QPushButton:hover {{ background: #16a34a; }}
            QPushButton:disabled {{ background: #94a3b8; }}
        """)
        self.btn_toggle.clicked.connect(self._toggle_services)
        ctrl_row.addWidget(self.btn_toggle)

        layout.addLayout(ctrl_row)

        return g

    def _build_addr_bar(self):
        """地址显示栏：服务启动后显示访问地址"""
        g = QGroupBox("🌐  访问地址")
        g.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        g.setStyleSheet(self._card_style())

        layout = QHBoxLayout(g)
        layout.setContentsMargins(12, 6, 12, 6)

        self.addr_value = QLabel("服务未启动")
        self.addr_value.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        self.addr_value.setStyleSheet("color: #94a3b8; border: none; background: transparent;")
        self.addr_value.setTextInteractionFlags(
            self.addr_value.textInteractionFlags() | Qt.TextSelectableByMouse)
        layout.addWidget(self.addr_value, 1)

        self.addr_bar = g

    def _build_log_panel(self):
        g = QGroupBox("📋  日志")
        g.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        g.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {C_BORDER}; border-radius: 8px;
                margin-top: 8px; padding: 14px 8px 8px 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px;
                padding: 0 6px; color: #1e293b; }}
        """)

        layout = QVBoxLayout(g)
        layout.setContentsMargins(4, 6, 4, 4)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.log_text.setStyleSheet("""
            QTextEdit { border: 1px solid #e2e8f0; border-radius: 4px;
                background: #0f172a; color: #e2e8f0; padding: 8px; }
        """)
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.log_text)
        return g

    def _build_status_bar(self):
        status = QStatusBar()
        status.setFont(QFont("Microsoft YaHei", 9))

        self.fastapi_status = QLabel("FastAPI: ⚪")
        self.fastapi_status.setStyleSheet(f"color: {C_GRAY};")
        status.addPermanentWidget(self.fastapi_status)

        status.addPermanentWidget(QLabel("│"))
        self.caddy_status = QLabel("Caddy: ⚪")
        self.caddy_status.setStyleSheet(f"color: {C_GRAY};")
        status.addPermanentWidget(self.caddy_status)

        self.setStatusBar(status)

    def _on_mode_changed(self):
        self.domain_input.setEnabled(self.radio_domain.isChecked())
        self.domain_port_input.setEnabled(self.radio_domain.isChecked())
        self.port_input.setEnabled(self.radio_local.isChecked())

    def _on_workers_changed(self, idx):
        if idx > 0:  # 不是 "1 个进程"
            QMessageBox.information(
                None, "提示",
                "暂不支持多进程",
                QMessageBox.StandardButton.Ok
            )
            # 切回 1 个进程，但代码已预留多进程支持
            self.workers_combo.setCurrentIndex(0)

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
        self.status_signal.emit({
            "cpu_pct": cpu_pct,
            "mem_total": f"{mem['total_gb']} GB",
            "mem_detail": f"可用 {mem['available_gb']} GB",
            "mem_pct": mem["percent"],
            "disk_total": f"{disk['total_gb']} GB",
            "disk_detail": f"可用 {disk['free_gb']} GB",
            "disk_pct": disk["percent"],
        })

    def _do_hardware_check(self):
        try:
            cpu = get_cpu_info()
            cpu["percent"] = psutil.cpu_percent(interval=0.5)
            mem = get_memory_info()
            disk = get_disk_info(self.paths["data_disk"])
        except Exception as e:
            self.log(f"⚠️  硬件检测出错: {e}")
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
        })

        self.log(
            f"硬件检测完成  |  "
            f"CPU: {cpu['logical_cores']}线程  "
            f"内存: {mem['total_gb']}GB  "
            f"磁盘: {disk['total_gb']}GB"
        )

    def _update_hardware(self, data):
        # CPU
        if "cpu_model" in data:
            model = data["cpu_model"]
            if len(model) > 30:
                model = model[:28] + "…"
            self._cpu_model_text = model
            self._cpu_cores_text = data.get("cpu_cores", "")
        if "cpu_pct" in data:
            self.cpu_circle.set_value(
                data["cpu_pct"],
                text=getattr(self, '_cpu_model_text', ''),
                sub_text=getattr(self, '_cpu_cores_text', '')
            )
        # 内存
        if "mem_pct" in data:
            self.mem_circle.set_value(
                data["mem_pct"],
                text=data.get("mem_total", ""),
                sub_text=data.get("mem_detail", "")
            )
        # 磁盘
        if "disk_pct" in data:
            self.disk_circle.set_value(
                data["disk_pct"],
                text=data.get("disk_total", ""),
                sub_text=data.get("disk_detail", "")
            )

    # ============================================================
    #  服务控制
    # ============================================================

    def _update_ui_state(self):
        """根据运行状态更新指示灯和按钮"""
        from PySide6.QtWidgets import QApplication
        if self.running:
            self.status_light.setText("🟢")
            self.status_light.setStyleSheet("color: #22c55e;")
            self.status_text.setText("运行中")
            self.status_text.setStyleSheet("color: #22c55e;")
            self.btn_toggle.setText("停止服务")
            self.btn_toggle.setStyleSheet(f"""
                QPushButton {{ border: none; border-radius: 5px; padding: 6px 24px;
                    background: {C_RED}; color: white; font-weight: bold; }}
                QPushButton:hover {{ background: #dc2626; }}
                QPushButton:disabled {{ background: #94a3b8; }}
            """)
        else:
            self.status_light.setText("🔴")
            self.status_light.setStyleSheet("color: #ef4444;")
            self.status_text.setText("已停止")
            self.status_text.setStyleSheet("color: #94a3b8;")
            self.btn_toggle.setText("启动服务")
            self.btn_toggle.setStyleSheet(f"""
                QPushButton {{ border: none; border-radius: 5px; padding: 6px 24px;
                    background: {C_GREEN}; color: white; font-weight: bold; }}
                QPushButton:hover {{ background: #16a34a; }}
                QPushButton:disabled {{ background: #94a3b8; }}
            """)
        self.btn_toggle.setEnabled(True)
        QApplication.processEvents()

    def _toggle_services(self):
        # 瞬间锁定 UI，防止频繁点击
        self.btn_toggle.setEnabled(False)
        self.status_light.setText("🟡")
        self.status_light.setStyleSheet("color: #facc15;")
        self.status_text.setText("正在切换...")
        self.status_text.setStyleSheet("color: #facc15;")
        self.btn_toggle.setText("处理中...")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        try:
            if self.running:
                self._stop_services()
            else:
                self.log("⏳  正在启动服务...")
                self._start_services()
        except Exception as e:
            self.log(f"❌ 操作异常: {e}")
            import traceback
            self.log(traceback.format_exc())

        # 操作完成，恢复按钮并根据结果更新状态
        self._update_ui_state()

    def _start_services(self):
        if self.running:
            return
        mode = "domain" if self.radio_domain.isChecked() else "local"
        domain = self.domain_input.text().strip() if mode == "domain" else "localhost"
        # 去掉可能残留的协议前缀
        while "://" in domain:
            domain = domain.split("://", 1)[-1]
        if mode == "domain" and not domain:
            self.log("⚠️  请输入域名")
            return

        self.log(f"🚀  正在启动服务（{'域名' if mode == 'domain' else '本地'}模式）")

        # 先找空闲端口
        self._fastapi_port = self._find_free_port(int(FASTAPI_PORT), 9000)
        self.log(f"   FastAPI 端口: {self._fastapi_port}")

        # 打印运行时版本
        py_exe = self.paths["runtime_python"]
        caddy_exe = self.paths["caddy_exe"]
        try:
            py_ver = subprocess.run([py_exe, "--version"], capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
            self.log(f"   Python: {py_ver}")
        except Exception:
            self.log("   Python: 版本获取失败")
        try:
            cv = subprocess.run([caddy_exe, "version"], capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip().split("\n")[0]
            self.log(f"   Caddy: {cv}")
        except Exception:
            self.log("   Caddy: 版本获取失败")

        caddy_port = self.domain_port_input.text().strip() if mode == "domain" else self.port_input.text().strip()
        if not caddy_port.isdigit():
            self.log("⚠️  端口格式不正确")
            return

        self._generate_caddyfile(mode, domain, caddy_port)
        if mode == "domain":
            save_config(self.paths, domain)
        self._start_fastapi()
        if self.fastapi_process is None:
            self.log("❌  FastAPI 未就绪，取消启动 Caddy")
            self.btn_toggle.setText("🟢  启动服务")
            self.btn_toggle.setEnabled(True)
            return
        self._start_caddy()

    def _generate_caddyfile(self, mode, domain, caddy_port):
        script = os.path.join(self.paths["caddy_dir"], "generate_caddyfile.py")
        if not os.path.exists(script):
            self.log("⚠️  generate_caddyfile.py 未找到")
            return
        try:
            r = subprocess.run(
                [sys.executable, script, "server" if mode == "domain" else "local", domain, str(self._fastapi_port), caddy_port],
                capture_output=True, text=True, timeout=10,
                cwd=self.paths["caddy_dir"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if r.returncode == 0:
                self.log(f"✅  Caddyfile 已生成（{mode}模式, Caddy端口: {caddy_port}）")
            else:
                self.log(f"⚠️  Caddyfile 生成出错: {r.stderr.strip()}")
        except Exception as e:
            self.log(f"⚠️  Caddyfile 生成出错: {e}")
            return

    def _find_free_port(self, start, end):
        """从 start 到 end 扫描空闲端口"""
        for port in range(start, end + 1):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("127.0.0.1", port))
                s.close()
                return port
            except OSError:
                continue
        raise RuntimeError(f"端口 {start}-{end} 全部被占用")

    def _wait_for_port(self, host: str, port: int, timeout: int = 5) -> bool:
        """等待端口就绪，超时返回 False"""
        import time
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
        # 从下拉框读取线程数
        workers = int(self.workers_combo.currentText().split()[0])
        port = self._fastapi_port
        cmd = [venv_py, "-m", "uvicorn", "main:app", "--port", str(port)]
        if self.reload_check.isChecked():
            cmd.append("--reload")
        if workers > 1:
            cmd.extend(["--workers", str(workers)])
        try:
            self.fastapi_process = subprocess.Popen(
                cmd,
                cwd=self.paths["backend_dir"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding='utf-8', errors='replace',
            )
            self.fastapi_pid = self.fastapi_process.pid
            # 后台线程：读取输出到日志面板
            def _watch_fastapi():
                for line in self.fastapi_process.stdout:
                    self.log(f"[FastAPI] {line.strip()}")
                rc = self.fastapi_process.wait()
                if self.fastapi_process is not None and rc != 0:
                    self.log(f"❌ FastAPI 异常退出 (code {rc})")
                    self.fastapi_process = None
            threading.Thread(target=_watch_fastapi, daemon=True).start()
            # 等待端口就绪
            if self._wait_for_port("127.0.0.1", int(port), timeout=10):
                self.log(f"✅  FastAPI 已启动 (端口 {port}, {workers}个进程, PID {self.fastapi_pid})")
            else:
                self.log(f"❌ FastAPI 启动失败：端口 {port} 未就绪")
                QMessageBox.critical(self, "启动失败",
                    f"FastAPI 启动失败，请查看日志，或联系管理员")
                self.fastapi_process = None
                self.btn_toggle.setText("🟢  启动服务")
                self.btn_toggle.setEnabled(True)
                return
        except Exception as e:
            self.log(f"❌  FastAPI 启动失败: {e}")
            self.btn_toggle.setText("🟢  启动服务")
            self.btn_toggle.setEnabled(True)

    def _start_caddy(self):
        exe = self.paths["caddy_exe"]
        cf = os.path.join(self.paths["caddy_dir"], "Caddyfile")
        if not os.path.exists(exe):
            self.log("⚠️  Caddy 可执行文件未找到")
            self.btn_toggle.setText("🟢  启动服务")
            self.btn_toggle.setEnabled(True)
            return
        if not os.path.exists(cf):
            self.log("⚠️  Caddyfile 未找到")
            self.btn_toggle.setText("🟢  启动服务")
            self.btn_toggle.setEnabled(True)
            return
        # 从 Caddyfile 里提取监听端口
        caddy_ports = []
        try:
            with open(cf, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # 匹配 "codenova.cn:443 {" 或 ":80 {" 或 "localhost:2019"
                    m = re.search(r':(\d+)\s*\{', line)
                    if m:
                        caddy_ports.append(int(m.group(1)))
        except Exception:
            pass
        if not caddy_ports:
            caddy_ports = [80]  # 猜不到就默认 80
        try:
            self.caddy_process = subprocess.Popen(
                [exe, "run", "--config", cf],
                cwd=self.paths["caddy_dir"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding='utf-8', errors='replace',
            )
            self.caddy_pid = self.caddy_process.pid
            # 后台线程：读取输出到日志面板
            def _watch_caddy():
                for line in self.caddy_process.stdout:
                    self.log(f"[Caddy] {line.strip()}")
                rc = self.caddy_process.wait()
                if self.caddy_process is not None and rc != 0:
                    self.log(f"❌ Caddy 异常退出 (code {rc})")
                    self.caddy_process = None
            threading.Thread(target=_watch_caddy, daemon=True).start()
            # 等待端口就绪（任何一个端口通就算成功）
            ok = False
            for cp in caddy_ports:
                if self._wait_for_port("127.0.0.1", cp, timeout=3):
                    ok = True
                    break
            if ok:
                self.log(f"✅  Caddy 已启动 (端口 {', '.join(str(p) for p in caddy_ports)}, PID {self.caddy_pid})")
            else:
                self.log(f"❌ Caddy 启动失败：端口 {', '.join(str(p) for p in caddy_ports)} 未就绪")
                QMessageBox.critical(self, "启动失败",
                    f"Caddy 启动失败，请查看日志，或联系管理员")
                self.caddy_process = None
                self.btn_toggle.setText("🟢  启动服务")
                self.btn_toggle.setEnabled(True)
                return
        except Exception as e:
            self.log(f"❌  Caddy 启动失败: {e}")
            self.btn_toggle.setText("🟢  启动服务")
            self.btn_toggle.setEnabled(True)
            return

        self.running = True
        self.poll_timer.start()
        self._set_status("running")

        # 启动成功后弹窗提示访问地址
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
                            req = urllib.request.urlopen(
                                f"http://{ip}:{port}/", timeout=5)
                            if req.status == 200:
                                # 检测是否是 Wi-Fi 接口
                                is_wifi = any(k in name.lower() for k in ("wi-fi","wifi","wlan","无线","802.11"))
                                found.append((0 if is_wifi else 1, ip))
                        except Exception:
                            continue
                # 按优先级排序，Wi-Fi 优先
                found.sort(key=lambda x: x[0])
                if found:
                    ip = found[0][1]
                    addr = f"http://{ip}:{port}" if port != "80" else f"http://{ip}"
            except Exception:
                pass

            self.addr_value.setText(f"{addr}")
            self.addr_value.setStyleSheet("color: #22c55e;")
            self.log(f"🌐  访问地址: {addr}")
            from .system_info import get_wifi_ssid
            wifi = get_wifi_ssid()
            wifi_hint = f"\n📶  Wi-Fi：{wifi}\n" if wifi else "\n"
            QMessageBox.information(self, "服务已启动",
                f"✅ 服务已成功启动！\n\n"
                f"请同学们打开浏览器，访问：\n"
                f"\n"
                f"🔗  {addr}\n"
                f"{wifi_hint}"
                f"（确保手机/电脑连接同一个 Wi-Fi 或交换机）")
        else:
            domain = self.domain_input.text().strip()
            url = f"https://{domain}"
            self.addr_value.setText(f"{url}")
            self.addr_value.setStyleSheet("color: #22c55e;")
            self.log(f"🌐  访问地址: {url}")
            QMessageBox.information(self, "服务已启动",
                f"✅ 服务已成功启动！\n\n"
                f"请同学们打开浏览器，访问：\n"
                f"\n"
                f"🔗  {url}\n")

    def _stop_services(self):
        self.log("🔴  正在停止服务...")
        from PySide6.QtWidgets import QApplication

        # 先记录 PID，避免清理时丢失
        pids = [("Caddy", self.caddy_pid), ("FastAPI", self.fastapi_pid)]

        # 用 taskkill /T /F 杀进程树，比 terminate() 更可靠
        for name, pid in pids:
            if pid:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        capture_output=True, timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    self.log(f"    {name} 已停止 (PID {pid})")
                except Exception as e:
                    self.log(f"    {name} 停止失败: {e}")

        # 清理
        self.fastapi_process = None
        self.caddy_process = None
        self.fastapi_pid = None
        self.caddy_pid = None
        self.running = False
        self.poll_timer.stop()
        self._update_ui_state()
        self._set_status("stopped")
        self.log("✅  服务已全部停止")

    def _poll_services(self):
        fa = self.fastapi_process and self.fastapi_process.poll() is None
        ca = self.caddy_process and self.caddy_process.poll() is None
        green = f"color: {C_GREEN};"
        red = f"color: {C_RED};"
        self.fastapi_status.setText(f"FastAPI: {'🟢' if fa else '🔴'}")
        self.fastapi_status.setStyleSheet(green if fa else red)
        self.caddy_status.setText(f"Caddy: {'🟢' if ca else '🔴'}")
        self.caddy_status.setStyleSheet(green if ca else red)
        if not fa and not ca and self.running:
            self._stop_services()

    def _set_status(self, state):
        if state == "stopped":
            self.addr_value.setText("服务未启动")
            self.addr_value.setStyleSheet("color: #94a3b8;")



    def closeEvent(self, event):
        if self.running:
            self._stop_services()
        super().closeEvent(event)

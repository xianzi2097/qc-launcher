"""
QC Launcher — 主窗口
左右分栏布局：左硬件参数 | 右启动选项（线程数）
"""

import os
import sys
import subprocess
import threading
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QProgressBar,
    QRadioButton, QLineEdit, QPushButton, QTextEdit,
    QStatusBar, QFrame, QSplitter, QSpinBox,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont

from .config import get_paths, load_config, save_config
from .system_info import get_cpu_info, get_memory_info, get_disk_info


# ---------- 颜色 ----------
C_GREEN = "#22c55e"
C_RED = "#ef4444"
C_GRAY = "#6b7280"
C_BORDER = "#e2e8f0"


class MainWindow(QMainWindow):
    """QC Launcher 主窗口"""

    log_signal = Signal(str)
    status_signal = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("QC Launcher  v0.9")
        self.setMinimumSize(720, 580)
        self.resize(760, 620)

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

        # 信号连接
        self.log_signal.connect(self._append_log)
        self.status_signal.connect(self._update_hardware)

        self._build_ui()
        # 延迟检测硬件
        QTimer.singleShot(200, self._run_hardware_check)

    # ============================================================
    #  UI
    # ============================================================

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_hardware_panel())
        splitter.addWidget(self._build_options_panel())
        splitter.setSizes([340, 380])
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter, 1)

        main_layout.addWidget(self._build_mode_panel())
        main_layout.addLayout(self._build_button_row())
        main_layout.addWidget(self._build_log_panel(), 2)
        self._build_status_bar()

    def _card_style(self):
        return f"""
            QGroupBox {{
                border: 1px solid {C_BORDER};
                border-radius: 8px;
                margin-top: 12px;
                padding: 16px 12px 12px 12px;
                background: #f8fafc;
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

        layout = QVBoxLayout(g)
        layout.setSpacing(8)

        # CPU
        layout.addWidget(QLabel("🧠  CPU", font=QFont("Microsoft YaHei", 9, QFont.Weight.Bold),
                                styleSheet=f"color: #64748b;"))
        self.cpu_model = QLabel("检测中...", font=QFont("Consolas", 9), wordWrap=True)
        layout.addWidget(self.cpu_model)
        self.cpu_cores = QLabel("", font=QFont("Consolas", 9),
                                styleSheet=f"color: #64748b;")
        layout.addWidget(self.cpu_cores)

        layout.addSpacing(4)

        # 内存
        layout.addWidget(QLabel("🧮  内存", font=QFont("Microsoft YaHei", 9, QFont.Weight.Bold),
                                styleSheet=f"color: #64748b;"))
        self.mem_total = QLabel("总量: -- GB", font=QFont("Consolas", 9))
        layout.addWidget(self.mem_total)

        self.mem_bar = QProgressBar()
        self.mem_bar.setRange(0, 100)
        self.mem_bar.setFixedHeight(14)
        self.mem_bar.setTextVisible(True)
        self.mem_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #cbd5e1; border-radius: 4px;
                background: #f1f5f9; text-align: center; font-size: 9px; color: #1e293b; }
            QProgressBar::chunk { border-radius: 3px; background: #22c55e; }
        """)
        layout.addWidget(self.mem_bar)

        self.mem_detail = QLabel("可用: -- GB", font=QFont("Consolas", 9),
                                 styleSheet=f"color: #64748b;")
        layout.addWidget(self.mem_detail)

        layout.addSpacing(4)

        # 磁盘
        disk_letter = os.path.splitdrive(self.paths["data_dir"])[0] or "?"
        layout.addWidget(QLabel(f"💾  磁盘 ({disk_letter})",
                                font=QFont("Microsoft YaHei", 9, QFont.Weight.Bold),
                                styleSheet=f"color: #64748b;"))
        self.disk_total = QLabel("总量: -- GB", font=QFont("Consolas", 9))
        layout.addWidget(self.disk_total)

        self.disk_bar = QProgressBar()
        self.disk_bar.setRange(0, 100)
        self.disk_bar.setFixedHeight(14)
        self.disk_bar.setTextVisible(True)
        self.disk_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #cbd5e1; border-radius: 4px;
                background: #f1f5f9; text-align: center; font-size: 9px; color: #1e293b; }
            QProgressBar::chunk { border-radius: 3px; background: #22c55e; }
        """)
        layout.addWidget(self.disk_bar)

        self.disk_detail = QLabel("可用: -- GB", font=QFont("Consolas", 9),
                                  styleSheet=f"color: #64748b;")
        layout.addWidget(self.disk_detail)

        layout.addStretch()
        return g

    def _build_options_panel(self):
        g = QGroupBox("⚙️  启动选项")
        g.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        g.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {C_BORDER}; border-radius: 8px;
                margin-top: 12px; padding: 16px 12px 12px 12px; background: #f8fafc; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px;
                padding: 0 6px; color: #1e293b; }}
        """)

        layout = QVBoxLayout(g)
        layout.setSpacing(12)

        # 线程数
        layout.addWidget(QLabel("🧵  工作线程数",
                                font=QFont("Microsoft YaHei", 9, QFont.Weight.Bold),
                                styleSheet=f"color: #64748b;"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setFont(QFont("Consolas", 14))
        self.workers_spin.setMinimum(1)
        self.workers_spin.setMaximum(os.cpu_count() or 2)
        self.workers_spin.setValue(min(os.cpu_count() or 2, 4))
        self.workers_spin.setFixedWidth(100)
        self.workers_spin.setStyleSheet(f"""
            QSpinBox {{ border: 1px solid {C_BORDER}; border-radius: 4px;
                padding: 4px 8px; background: white; color: #1e293b; }}
        """)
        row = QHBoxLayout()
        row.addWidget(self.workers_spin)
        row.addWidget(QLabel(f"/ {os.cpu_count() or '?'} 逻辑核心",
                             font=QFont("Microsoft YaHei", 9),
                             styleSheet=f"color: {C_GRAY};"))
        row.addStretch()
        layout.addLayout(row)

        layout.addSpacing(4)
        tip = QLabel("💡 线程数建议 ≤ 逻辑核心数。\n    小机构 1~2 即可，大点设 4~8。")
        tip.setFont(QFont("Microsoft YaHei", 9))
        tip.setStyleSheet(f"color: {C_GRAY};")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        layout.addStretch()
        return g

    def _build_mode_panel(self):
        g = QGroupBox("🚀  启动模式")
        g.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        g.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {C_BORDER}; border-radius: 8px;
                margin-top: 12px; padding: 12px 12px 8px 12px; background: #f8fafc; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px;
                padding: 0 6px; color: #1e293b; }}
        """)

        layout = QHBoxLayout(g)
        layout.setSpacing(16)

        self.radio_local = QRadioButton("本地模式  →  http://localhost")
        self.radio_local.setFont(QFont("Microsoft YaHei", 10))
        self.radio_local.setChecked(True)
        self.radio_local.toggled.connect(self._on_mode_changed)

        self.radio_domain = QRadioButton("域名模式  →")
        self.radio_domain.setFont(QFont("Microsoft YaHei", 10))

        self.domain_input = QLineEdit()
        self.domain_input.setPlaceholderText("输入域名...")
        self.domain_input.setText(self.config.get("domain", "codenova.cn"))
        self.domain_input.setFont(QFont("Consolas", 10))
        self.domain_input.setStyleSheet(f"""
            QLineEdit {{ border: 1px solid {C_BORDER}; border-radius: 4px;
                padding: 4px 8px; background: white; color: #1e293b; }}
        """)
        self.domain_input.setEnabled(False)

        layout.addWidget(self.radio_local)
        layout.addWidget(self.radio_domain)
        layout.addWidget(self.domain_input, 1)
        return g

    def _on_mode_changed(self):
        self.domain_input.setEnabled(self.radio_domain.isChecked())

    def _build_button_row(self):
        layout = QHBoxLayout()
        layout.setSpacing(12)

        self.btn_start = QPushButton("🟢  启动服务")
        self.btn_start.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self.btn_start.setStyleSheet(f"""
            QPushButton {{ border: none; border-radius: 6px; padding: 8px 28px;
                background: {C_GREEN}; color: white; }}
            QPushButton:hover {{ background: #16a34a; }}
            QPushButton:disabled {{ background: #94a3b8; }}
        """)
        self.btn_start.clicked.connect(self._start_services)

        self.btn_stop = QPushButton("🔴  停止服务")
        self.btn_stop.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self.btn_stop.setStyleSheet(f"""
            QPushButton {{ border: none; border-radius: 6px; padding: 8px 28px;
                background: {C_RED}; color: white; }}
            QPushButton:hover {{ background: #dc2626; }}
            QPushButton:disabled {{ background: #94a3b8; }}
        """)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_services)

        layout.addStretch()
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_stop)
        layout.addStretch()
        return layout

    def _build_log_panel(self):
        g = QGroupBox("📋  日志")
        g.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        g.setStyleSheet(f"""
            QGroupBox {{ border: 1px solid {C_BORDER}; border-radius: 8px;
                margin-top: 8px; padding: 12px 8px 8px 8px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px;
                padding: 0 6px; color: #1e293b; }}
        """)

        layout = QVBoxLayout(g)
        layout.setContentsMargins(4, 4, 4, 4)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("""
            QTextEdit { border: 1px solid #e2e8f0; border-radius: 4px;
                background: #0f172a; color: #e2e8f0; padding: 6px; }
        """)
        layout.addWidget(self.log_text)
        return g

    def _build_status_bar(self):
        status = QStatusBar()
        status.setFont(QFont("Microsoft YaHei", 9))

        self.status_label = QLabel("⚪  就绪")
        self.status_label.setStyleSheet(f"color: {C_GRAY};")
        status.addWidget(self.status_label)

        status.addPermanentWidget(QLabel("│"))
        self.fastapi_status = QLabel("FastAPI: ⚪")
        self.fastapi_status.setStyleSheet(f"color: {C_GRAY};")
        status.addPermanentWidget(self.fastapi_status)

        status.addPermanentWidget(QLabel("│"))
        self.caddy_status = QLabel("Caddy: ⚪")
        self.caddy_status.setStyleSheet(f"color: {C_GRAY};")
        status.addPermanentWidget(self.caddy_status)

        self.setStatusBar(status)

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

    def _do_hardware_check(self):
        try:
            cpu = get_cpu_info()
            mem = get_memory_info()
            disk = get_disk_info(self.paths["data_disk"])
        except Exception as e:
            self.log(f"⚠️  硬件检测出错: {e}")
            cpu = {"model": "获取失败", "physical_cores": 0, "logical_cores": 0}
            mem = {"total_gb": 0, "available_gb": 0, "percent": 0}
            disk = {"total_gb": 0, "free_gb": 0, "percent": 0}

        self.status_signal.emit({
            "cpu_model": cpu["model"],
            "cpu_cores": f"物理核心: {cpu['physical_cores']}  /  逻辑线程: {cpu['logical_cores']}",
            "mem_total": f"总量: {mem['total_gb']} GB",
            "mem_detail": f"可用: {mem['available_gb']} GB",
            "mem_pct": mem["percent"],
            "disk_total": f"总量: {disk['total_gb']} GB",
            "disk_detail": f"可用: {disk['free_gb']} GB",
            "disk_pct": disk["percent"],
        })

        self.log(
            f"硬件检测完成  |  "
            f"CPU: {cpu['logical_cores']}线程  "
            f"内存: {mem['total_gb']}GB  "
            f"磁盘: {disk['total_gb']}GB"
        )

    def _update_hardware(self, data):
        if "cpu_model" in data:
            self.cpu_model.setText(data["cpu_model"])
        if "cpu_cores" in data:
            self.cpu_cores.setText(data["cpu_cores"])
        if "mem_total" in data:
            self.mem_total.setText(data["mem_total"])
        if "mem_detail" in data:
            self.mem_detail.setText(data["mem_detail"])
        if "mem_pct" in data:
            self.mem_bar.setValue(int(data["mem_pct"]))
            color = "#22c55e" if data["mem_pct"] < 50 else "#eab308" if data["mem_pct"] < 80 else "#ef4444"
            self.mem_bar.setStyleSheet(
                self.mem_bar.styleSheet().rsplit("QProgressBar::chunk", 1)[0]
                + f"QProgressBar::chunk {{ border-radius: 3px; background: {color}; }}"
            )
        if "disk_total" in data:
            self.disk_total.setText(data["disk_total"])
        if "disk_detail" in data:
            self.disk_detail.setText(data["disk_detail"])
        if "disk_pct" in data:
            self.disk_bar.setValue(int(data["disk_pct"]))
            color = "#22c55e" if data["disk_pct"] < 50 else "#eab308" if data["disk_pct"] < 80 else "#ef4444"
            self.disk_bar.setStyleSheet(
                self.disk_bar.styleSheet().rsplit("QProgressBar::chunk", 1)[0]
                + f"QProgressBar::chunk {{ border-radius: 3px; background: {color}; }}"
            )

    # ============================================================
    #  服务控制
    # ============================================================

    def _start_services(self):
        if self.running:
            return
        mode = "domain" if self.radio_domain.isChecked() else "local"
        domain = self.domain_input.text().strip() if mode == "domain" else "localhost"
        if mode == "domain" and not domain:
            self.log("⚠️  请输入域名")
            return

        self.log(f"🚀  正在启动服务（{'域名' if mode == 'domain' else '本地'}模式）")
        self._generate_caddyfile(mode, domain)
        if mode == "domain":
            save_config(self.paths, domain)
        self._start_fastapi()
        self._start_caddy()

    def _generate_caddyfile(self, mode, domain):
        script = os.path.join(self.paths["caddy_dir"], "generate_caddyfile.py")
        if not os.path.exists(script):
            self.log("⚠️  generate_caddyfile.py 未找到")
            return
        try:
            r = subprocess.run(
                [sys.executable, script, "server" if mode == "domain" else "local"],
                capture_output=True, text=True, timeout=10,
                cwd=self.paths["caddy_dir"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self.log(f"{'✅' if r.returncode == 0 else '⚠️'}  Caddyfile 已生成（{mode}模式）")
        except Exception as e:
            self.log(f"⚠️  Caddyfile 生成出错: {e}")

    def _start_fastapi(self):
        # 优先级: 便携 Python → 系统 Python
        portable_py = self.paths.get("runtime_python", "")
        if portable_py and os.path.exists(portable_py):
            venv_py = portable_py
        else:
            venv_py = sys.executable
        workers = self.workers_spin.value()
        cmd = [venv_py, "-m", "uvicorn", "main:app", "--port", "8000"]
        if workers > 1:
            cmd.extend(["--workers", str(workers)])
        else:
            cmd.append("--reload")
        try:
            self.fastapi_process = subprocess.Popen(
                cmd,
                cwd=self.paths["backend_dir"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.fastapi_pid = self.fastapi_process.pid
            self.log(f"✅  FastAPI 已启动 (端口 8000, {workers}线程, PID {self.fastapi_pid})")
        except Exception as e:
            self.log(f"❌  FastAPI 启动失败: {e}")

    def _start_caddy(self):
        exe = self.paths["caddy_exe"]
        cf = os.path.join(self.paths["caddy_dir"], "Caddyfile")
        if not os.path.exists(exe):
            self.log("⚠️  Caddy 可执行文件未找到")
            return
        if not os.path.exists(cf):
            self.log("⚠️  Caddyfile 未找到")
            return
        try:
            self.caddy_process = subprocess.Popen(
                [exe, "run", "--config", cf],
                cwd=self.paths["caddy_dir"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.caddy_pid = self.caddy_process.pid
            self.log(f"✅  Caddy 已启动 (PID {self.caddy_pid})")
        except Exception as e:
            self.log(f"❌  Caddy 启动失败: {e}")

        self.running = True
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.poll_timer.start()
        self._set_status("running")

    def _stop_services(self):
        self.log("🔴  正在停止服务...")

        # 用 taskkill /T /F 杀进程树，比 terminate() 更可靠
        for name, pid in [("Caddy", getattr(self, "caddy_pid", None)),
                           ("FastAPI", getattr(self, "fastapi_pid", None))]:
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
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.poll_timer.stop()
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
        if not fa and not ca:
            self._stop_services()

    def _set_status(self, state):
        if state == "running":
            self.status_label.setText("🟢  运行中")
            self.status_label.setStyleSheet(f"color: {C_GREEN};")
        else:
            self.status_label.setText("⚪  已停止")
            self.status_label.setStyleSheet(f"color: {C_GRAY};")



    def closeEvent(self, event):
        if self.running:
            self._stop_services()
        super().closeEvent(event)

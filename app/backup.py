"""
QC Launcher — 数据备份模块
支持将 data 目录备份到用户指定位置。
"""

import os
import shutil
import zipfile
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QProgressBar, QTextEdit, QMessageBox,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont

from .styles import BTN_SECONDARY, BTN_ORANGE, PROGRESS_BAR_TALL, LOG_AREA


# ============================================================
#  备份工作线程
# ============================================================

class BackupWorker(QThread):
    """后台执行备份，避免阻塞 UI"""
    progress = Signal(str)
    progress_pct = Signal(int)
    done_signal = Signal(bool, str)  # (success, message)

    def __init__(self, src_dir: str, dst_path: str, use_zip: bool):
        super().__init__()
        self.src_dir = src_dir
        self.dst_path = dst_path
        self.use_zip = use_zip

    def run(self):
        try:
            if not os.path.exists(self.src_dir):
                self.done_signal.emit(False, f"源目录不存在: {self.src_dir}")
                return

            # 统计文件总数（用于进度条）
            total_files = 0
            for _, _, filenames in os.walk(self.src_dir):
                total_files += len(filenames)
            if total_files == 0:
                self.done_signal.emit(False, "data 目录为空，无需备份")
                return

            processed = 0

            if self.use_zip:
                self._backup_zip(total_files, lambda: None)
            else:
                self._backup_copy(total_files, lambda: None)

            size_mb = 0
            if os.path.isfile(self.dst_path):
                size_mb = os.path.getsize(self.dst_path) / (1024 * 1024)
            elif os.path.isdir(self.dst_path):
                size_mb = self._dir_size_mb(self.dst_path)

            self.done_signal.emit(True, f"备份完成！\n\n📁 {self.dst_path}\n📦 大小：{size_mb:.1f} MB")
        except Exception as e:
            self.done_signal.emit(False, f"备份失败：{e}")

    def _backup_zip(self, total_files, _cb):
        """压缩备份"""
        self.progress.emit(f"📦 正在压缩到 {self.dst_path} ...")
        processed = 0
        with zipfile.ZipFile(self.dst_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(self.src_dir):
                for fname in files:
                    fp = os.path.join(root, fname)
                    arcname = os.path.relpath(fp, os.path.dirname(self.src_dir))
                    zf.write(fp, arcname)
                    processed += 1
                    if processed % 10 == 0 or processed == total_files:
                        self.progress_pct.emit(int(processed / total_files * 100))

    def _backup_copy(self, total_files, _cb):
        """直接复制文件夹"""
        self.progress.emit(f"📁 正在复制到 {self.dst_path} ...")
        if os.path.exists(self.dst_path):
            shutil.rmtree(self.dst_path)

        # 先创建目标目录
        os.makedirs(self.dst_path, exist_ok=True)

        processed = 0
        for root, dirs, files in os.walk(self.src_dir):
            rel = os.path.relpath(root, self.src_dir)
            target_dir = os.path.join(self.dst_path, rel) if rel != '.' else self.dst_path
            os.makedirs(target_dir, exist_ok=True)
            for fname in files:
                shutil.copy2(os.path.join(root, fname), os.path.join(target_dir, fname))
                processed += 1
                if processed % 20 == 0 or processed == total_files:
                    self.progress_pct.emit(int(processed / total_files * 100))

    @staticmethod
    def _dir_size_mb(path: str) -> float:
        total = 0
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total / (1024 * 1024)


# ============================================================
#  备份对话框
# ============================================================

class BackupDialog(QDialog):
    """数据备份对话框"""

    def __init__(self, data_dir: str, parent=None):
        super().__init__(parent)
        self.data_dir = data_dir
        self._worker = None
        self._dst_path = ""

        self.setWindowTitle("备份数据")
        self.setMinimumSize(500, 350)
        self.resize(550, 380)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint | Qt.WindowCloseButtonHint
        )

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── 说明 ──
        hint = QLabel(
            "将 data 目录（用户数据、课程、数据库）备份到指定位置。\n"
            "建议定期备份，以防数据丢失。"
        )
        hint.setFont(QFont("Microsoft YaHei", 9))
        hint.setStyleSheet("color: #64748b;")
        layout.addWidget(hint)

        # ── 源目录 ──
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("源目录：", font=QFont("Microsoft YaHei", 9)))
        src_label = QLabel(self.data_dir)
        src_label.setFont(QFont("Consolas", 9))
        src_label.setStyleSheet("color: #475569;")
        src_label.setWordWrap(True)
        src_row.addWidget(src_label, 1)
        layout.addLayout(src_row)

        # ── 目标选择 ──
        dst_row = QHBoxLayout()
        dst_row.addWidget(QLabel("备份到：", font=QFont("Microsoft YaHei", 9)))
        self.dst_label = QLabel("（请选择目标位置）")
        self.dst_label.setFont(QFont("Consolas", 9))
        self.dst_label.setStyleSheet("color: #94a3b8;")
        self.dst_label.setWordWrap(True)
        dst_row.addWidget(self.dst_label, 1)

        browse_btn = QPushButton("选择...")
        browse_btn.setFont(QFont("Microsoft YaHei", 9))
        browse_btn.setStyleSheet(BTN_SECONDARY)
        browse_btn.clicked.connect(self._browse_dst)
        dst_row.addWidget(browse_btn)
        layout.addLayout(dst_row)

        # ── 格式选择 ──
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("备份格式：", font=QFont("Microsoft YaHei", 9)))

        from PySide6.QtWidgets import QRadioButton
        self.radio_zip = QRadioButton("ZIP 压缩包（推荐）")
        self.radio_zip.setFont(QFont("Microsoft YaHei", 9))
        self.radio_zip.setChecked(True)
        fmt_row.addWidget(self.radio_zip)

        self.radio_copy = QRadioButton("直接复制文件夹")
        self.radio_copy.setFont(QFont("Microsoft YaHei", 9))
        fmt_row.addWidget(self.radio_copy)

        fmt_row.addStretch()
        layout.addLayout(fmt_row)

        # ── 进度条 ──
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(PROGRESS_BAR_TALL)
        layout.addWidget(self.progress_bar)

        # ── 日志 ──
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setMaximumHeight(120)
        self.log_area.setStyleSheet(LOG_AREA)
        layout.addWidget(self.log_area)

        # ── 按钮 ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("关闭")
        cancel_btn.setFont(QFont("Microsoft YaHei", 9))
        cancel_btn.setStyleSheet(BTN_SECONDARY)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        self.backup_btn = QPushButton("开始备份")
        self.backup_btn.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.backup_btn.setStyleSheet(BTN_ORANGE)
        self.backup_btn.clicked.connect(self._do_backup)
        btn_row.addWidget(self.backup_btn)

        layout.addLayout(btn_row)

    def _browse_dst(self):
        if self.radio_zip.isChecked():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_name = f"QC_data_backup_{ts}.zip"
            path, _ = QFileDialog.getSaveFileName(
                self, "选择备份保存位置", default_name,
                "ZIP 文件 (*.zip);;所有文件 (*)"
            )
        else:
            path = QFileDialog.getExistingDirectory(
                self, "选择备份目标文件夹"
            )
            if path:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = os.path.join(path, f"QC_data_backup_{ts}")

        if path:
            self._dst_path = path
            self.dst_label.setText(path)
            self.dst_label.setStyleSheet("color: #1e293b;")

    def _do_backup(self):
        if not self._dst_path:
            QMessageBox.warning(self, "提示", "请先选择备份目标位置")
            return

        self.backup_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log_area.clear()

        use_zip = self.radio_zip.isChecked()
        self._worker = BackupWorker(self.data_dir, self._dst_path, use_zip)
        self._worker.progress.connect(self._on_progress)
        self._worker.progress_pct.connect(self.progress_bar.setValue)
        self._worker.done_signal.connect(self._on_done)
        self._worker.start()

    def _on_progress(self, msg: str):
        self.log_area.append(msg)

    def _on_done(self, success: bool, message: str):
        self.progress_bar.setVisible(False)
        self.backup_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "备份完成", message)
        else:
            QMessageBox.critical(self, "备份失败", message)

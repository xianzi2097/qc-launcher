"""
QC Launcher — 数据备份模块
支持将 data 目录备份到用户指定位置。
"""

import os
import shutil
import tempfile
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


# ============================================================
#  自动备份（供"启动服务前自动备份"调用，纯同步函数）
# ============================================================

def auto_backup_now(data_dir: str, backup_root: str, keep: int = 7, log=None) -> str:
    """
    将 data 目录打包为 zip 到 backup_root，保留最近 keep 份，返回备份文件名。
    同步执行；data 较大时应由调用方放在后台线程。成功返回文件名，跳过返回空串。
    """
    def _log(msg):
        if log:
            log(msg)
    if not os.path.isdir(data_dir):
        _log(f"⚠️  自动备份跳过：data 目录不存在 {data_dir}")
        return ""
    try:
        _checkpoint_db(data_dir)
    except Exception:
        pass
    os.makedirs(backup_root, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst_name = f"auto_{ts}.zip"
    dst_path = os.path.join(backup_root, dst_name)
    try:
        with zipfile.ZipFile(dst_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(data_dir):
                for fn in files:
                    fp = os.path.join(root, fn)
                    arc = os.path.relpath(fp, os.path.dirname(data_dir))
                    zf.write(fp, arc)
        _cleanup_old(backup_root, keep)
        _log(f"✅  自动备份完成：{dst_path}（保留最近 {keep} 份）")
        return dst_name
    except Exception as e:
        _log(f"❌  自动备份失败：{e}")
        try:
            if os.path.exists(dst_path):
                os.remove(dst_path)
        except OSError:
            pass
        return ""


def _checkpoint_db(data_dir: str):
    """尽力把 WAL 合并回主库，保证 zip 里的数据库完整"""
    import sqlite3
    db_path = os.path.join(data_dir, "qingcheng.db")
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path, timeout=5)
    try:
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        conn.commit()
    finally:
        conn.close()


def _cleanup_old(backup_root: str, keep: int):
    """删除超过 keep 份的最旧自动备份"""
    if not os.path.isdir(backup_root):
        return
    files = sorted(
        f for f in os.listdir(backup_root)
        if f.startswith("auto_") and f.endswith(".zip")
    )
    for old in files[:-keep]:
        try:
            os.remove(os.path.join(backup_root, old))
        except OSError:
            pass


# ============================================================
#  恢复（从备份 ZIP 还原 data 目录）
# ============================================================

def restore_from_zip(zip_path: str, data_dir: str, backup_root: str, log=None):
    """
    从备份 zip 恢复 data 目录。恢复前自动把当前 data 备份 + 改名保护（不直接删）。
    返回 (success, message)。
    """
    def _log(m):
        if log:
            log(m)
    if not os.path.isfile(zip_path):
        return False, "请选择有效的 ZIP 备份文件"

    # 1️⃣ 保护当前 data：先自动备份一份，再把旧 data 改名（绝不直接删除）
    if os.path.isdir(data_dir) and os.listdir(data_dir):
        _log("💾  恢复前先备份当前 data（保护）...")
        auto_backup_now(data_dir, backup_root, keep=7, log=_log)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = f"{data_dir}.bak_{ts}"
        _log(f"📦  当前 data 改名保护 → {bak}")
        os.rename(data_dir, bak)

    # 2️⃣ 安全解压到临时目录（防路径穿越）
    tmp = tempfile.mkdtemp(prefix="qc_restore_")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if not any(n.startswith("data/") for n in names):
                return False, "备份文件里没有 data/ 结构，不是有效备份"
            tmp_norm = os.path.normpath(tmp)
            for m in zf.infolist():
                tgt = os.path.normpath(os.path.join(tmp, m.filename))
                if not (tgt == tmp_norm or tgt.startswith(tmp_norm + os.sep)):
                    return False, f"备份包含不安全路径，已中止：{m.filename}"
            _log("📂  解压备份文件 ...")
            zf.extractall(tmp)

        src = os.path.join(tmp, "data")
        if not os.path.isdir(src):
            return False, "备份里没有 data 目录"

        # 3️⃣ 移动为新的 data（此时旧 data 已被改名保护，目标位空）
        os.makedirs(os.path.dirname(data_dir), exist_ok=True)
        shutil.move(src, data_dir)
        _log(f"✅  恢复完成：{data_dir}")
        return True, (
            "恢复完成！请点击「启动服务」重新启动。\n\n"
            f"原 data 已备份并改名保护：\n{data_dir}.bak_*\n\n"
            "确认一切正常后，可手动删除 .bak_* 旧数据。"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class RestoreWorker(QThread):
    """后台执行恢复，避免阻塞 UI"""
    log = Signal(str)
    done_signal = Signal(bool, str)  # (success, message)

    def __init__(self, zip_path: str, data_dir: str, backup_root: str):
        super().__init__()
        self.zip_path = zip_path
        self.data_dir = data_dir
        self.backup_root = backup_root

    def run(self):
        try:
            ok, msg = restore_from_zip(
                self.zip_path, self.data_dir, self.backup_root, log=self.log.emit
            )
            self.done_signal.emit(ok, msg)
        except Exception as e:
            self.done_signal.emit(False, f"恢复失败：{e}")


class RestoreDialog(QDialog):
    """数据恢复对话框"""

    def __init__(self, data_dir: str, backup_root: str, parent=None):
        super().__init__(parent)
        self.data_dir = data_dir
        self.backup_root = backup_root
        self._worker = None
        self._zip_path = ""

        self.setWindowTitle("恢复数据")
        self.setMinimumSize(520, 340)
        self.resize(560, 360)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint | Qt.WindowCloseButtonHint
        )
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        hint = QLabel(
            "从备份 ZIP 恢复 data 目录（用户数据、课程、数据库）。\n\n"
            "⚠️ 服务必须已停止才能恢复。\n"
            "恢复前会自动备份当前 data 并改名保护，不会直接删除。"
        )
        hint.setFont(QFont("Microsoft YaHei", 9))
        hint.setStyleSheet("color: #64748b;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        zip_row = QHBoxLayout()
        zip_row.addWidget(QLabel("备份文件：", font=QFont("Microsoft YaHei", 9)))
        self.zip_label = QLabel("（请选择备份 ZIP）")
        self.zip_label.setFont(QFont("Consolas", 9))
        self.zip_label.setStyleSheet("color: #94a3b8;")
        self.zip_label.setWordWrap(True)
        zip_row.addWidget(self.zip_label, 1)

        browse_btn = QPushButton("选择...")
        browse_btn.setFont(QFont("Microsoft YaHei", 9))
        browse_btn.setStyleSheet(BTN_SECONDARY)
        browse_btn.clicked.connect(self._browse_zip)
        zip_row.addWidget(browse_btn)
        layout.addLayout(zip_row)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setMaximumHeight(140)
        self.log_area.setStyleSheet(LOG_AREA)
        layout.addWidget(self.log_area)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("关闭")
        cancel_btn.setFont(QFont("Microsoft YaHei", 9))
        cancel_btn.setStyleSheet(BTN_SECONDARY)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        self.restore_btn = QPushButton("开始恢复")
        self.restore_btn.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.restore_btn.setStyleSheet(BTN_ORANGE)
        self.restore_btn.clicked.connect(self._do_restore)
        btn_row.addWidget(self.restore_btn)
        layout.addLayout(btn_row)

    def _browse_zip(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择备份文件", "", "ZIP 文件 (*.zip);;所有文件 (*)"
        )
        if path:
            self._zip_path = path
            self.zip_label.setText(path)
            self.zip_label.setStyleSheet("color: #1e293b;")

    def _do_restore(self):
        if not self._zip_path:
            QMessageBox.warning(self, "提示", "请先选择备份 ZIP 文件")
            return
        ret = QMessageBox.question(
            self, "确认恢复",
            "⚠️ 将用备份替换当前 data 数据。\n\n"
            "恢复前会自动备份并保护当前 data（不会直接删除）。\n\n"
            "确定继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        self.restore_btn.setEnabled(False)
        self.log_area.clear()
        self._worker = RestoreWorker(self._zip_path, self.data_dir, self.backup_root)
        self._worker.log.connect(self.log_area.append)
        self._worker.done_signal.connect(self._on_done)
        self._worker.start()

    def _on_done(self, ok: bool, message: str):
        self.restore_btn.setEnabled(True)
        if ok:
            QMessageBox.information(self, "恢复完成", message)
            self.accept()
        else:
            QMessageBox.critical(self, "恢复失败", message)

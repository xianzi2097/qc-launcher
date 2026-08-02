"""
QC Launcher — 备份/恢复核心逻辑（纯标准库，不依赖 PySide6）
================================================================
存放"数据备份与恢复"的业务逻辑，供两处使用：
  · GUI 层（app/backup.py）：手动备份对话框、恢复对话框、启动前自动备份
  · 自动化测试：直接 `from app.backup_core import ...`，无需 PySide6 环境

与后端每日自动备份（qc-pocket-space/backend/backup.py）行为对齐：
同一备份目录 backups/、同一命名 auto_*.zip、保留最近 7 份。
"""

import os
import shutil
import tempfile
import zipfile
from datetime import datetime


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


def auto_backup_now(data_dir: str, backup_root: str, keep: int = 14, log=None) -> str:
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
        auto_backup_now(data_dir, backup_root, keep=14, log=_log)
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

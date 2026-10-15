"""
QC Launcher — 备份/恢复核心逻辑（纯标准库，不依赖 PySide6）
================================================================
存放"数据备份与恢复"的业务逻辑，供两处使用：
  · GUI 层（app/backup.py）：手动备份对话框、恢复对话框、启动前自动备份
  · 自动化测试：直接 `from app.backup_core import ...`，无需 PySide6 环境

与后端每日自动备份（qc-pocket-space/backend_v2/app/backup.py）行为对齐：
同一备份目录 backups/；命名前缀隔离（启动器 auto_*.zip / 后端 v2_auto_*.zip，
互不清理），各保留最近 14 份。
"""

import os
import shutil
import tempfile
import time
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
    db_path = os.path.join(data_dir, "codenova_v2.db")
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path, timeout=5)
    try:
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        conn.commit()
    finally:
        conn.close()


def _last_backup_ts(backup_root: str) -> float:
    """backups/ 里最近一份 auto_*.zip 的时间戳，没有则 0"""
    if not os.path.isdir(backup_root):
        return 0
    files = [f for f in os.listdir(backup_root)
             if f.startswith("auto_") and f.endswith(".zip")]
    if not files:
        return 0
    return max(os.path.getmtime(os.path.join(backup_root, f)) for f in files)


def auto_backup_now(data_dir: str, backup_root: str, keep: int = 14, log=None,
                    min_interval_hours: int = 12) -> str:
    """
    将 data 目录打包为 zip 到 backup_root，保留最近 keep 份，返回备份文件名。
    距上次备份不足 min_interval_hours 小时则跳过（防止反复启动刷屏），传 0 强制备份。
    同步执行；data 较大时应由调用方放在后台线程。成功返回文件名，跳过返回空串。
    """
    def _log(msg):
        if log:
            log(msg)
    if not os.path.isdir(data_dir):
        _log(f"[警告] 自动备份跳过：data 目录不存在 {data_dir}")
        return ""
    if min_interval_hours and min_interval_hours > 0:
        last = _last_backup_ts(backup_root)
        if last and time.time() - last < min_interval_hours * 3600:
            _log(f"[跳过] 距上次备份不足 {min_interval_hours} 小时，本次跳过")
            return ""
    try:
        _checkpoint_db(data_dir)
    except Exception:
        pass
    os.makedirs(backup_root, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst_name = f"auto_{ts}.zip"
    dst_path = os.path.join(backup_root, dst_name)
    # 同一秒内多次备份可能重名，自动加后缀防止互相覆盖
    n = 1
    while os.path.exists(dst_path):
        dst_name = f"auto_{ts}_{n}.zip"
        dst_path = os.path.join(backup_root, dst_name)
        n += 1
    try:
        with zipfile.ZipFile(dst_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(data_dir):
                for fn in files:
                    fp = os.path.join(root, fn)
                    arc = os.path.relpath(fp, os.path.dirname(data_dir))
                    zf.write(fp, arc)
        _cleanup_old(backup_root, keep)
        _log(f"[完成] 自动备份完成：{dst_path}（保留最近 {keep} 份）")
        return dst_name
    except Exception as e:
        _log(f"[失败] 自动备份失败：{e}")
        try:
            if os.path.exists(dst_path):
                os.remove(dst_path)
        except OSError:
            pass
        return ""


def restore_from_zip(zip_path: str, data_dir: str, backup_root: str, log=None):
    """
    从备份 zip 恢复数据目录（备份顶层 = data_dir 同名，如 data_v2/）。
    先校验并解压，全部通过后才改名保护当前 data（校验失败绝不动现有数据）。
    返回 (success, message)。
    """
    def _log(m):
        if log:
            log(m)
    if not os.path.isfile(zip_path):
        return False, "请选择有效的 ZIP 备份文件"

    top = os.path.basename(os.path.normpath(data_dir))   # 备份里的顶层目录名（data_v2）

    # [1] 校验 + 解压到临时目录（此阶段绝不动当前 data）
    tmp = tempfile.mkdtemp(prefix="qc_restore_")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if not any(n.startswith(top + "/") for n in names):
                return False, (
                    f"备份文件里没有 {top}/ 结构，不是有效备份"
                    "（V1 旧版 data/ 备份不适用于当前版本）"
                )
            tmp_norm = os.path.normpath(tmp)
            for m in zf.infolist():
                tgt = os.path.normpath(os.path.join(tmp, m.filename))
                if not (tgt == tmp_norm or tgt.startswith(tmp_norm + os.sep)):
                    return False, f"备份包含不安全路径，已中止：{m.filename}"
            _log("[解压] 备份文件解压中 ...")
            zf.extractall(tmp)

        src = os.path.join(tmp, top)
        if not os.path.isdir(src):
            return False, f"备份里没有 {top} 目录"

        # [2] 保护当前 data：先自动备份一份，再把旧 data 改名（绝不直接删除）
        if os.path.isdir(data_dir) and os.listdir(data_dir):
            _log("[备份] 恢复前先备份当前 data（保护）...")
            # 恢复前保护备份必须强制（min_interval_hours=0），不能被跳过
            auto_backup_now(data_dir, backup_root, keep=14, log=_log, min_interval_hours=0)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            bak = f"{data_dir}.bak_{ts}"
            _log(f"[备份] 当前 data 改名保护 → {bak}")
            os.rename(data_dir, bak)

        # [3] 移动为新的 data（此时旧 data 已被改名保护，目标位空）
        os.makedirs(os.path.dirname(data_dir), exist_ok=True)
        shutil.move(src, data_dir)
        _log(f"[完成] 恢复完成：{data_dir}")
        return True, (
            "恢复完成！请点击「启动服务」重新启动。\n\n"
            f"原 data 已备份并改名保护：\n{data_dir}.bak_*\n\n"
            "确认一切正常后，可手动删除 .bak_* 旧数据。"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

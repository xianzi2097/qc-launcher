"""
QC Launcher — 路径配置模块
自动推导项目所有路径，零配置。

支持两种目录布局：
    开发机:  QC-PocketSpace/labs_dev/qx-launcher/
    服务器:  QC-Packet/qc-launcher/
两种情况下 qc-pocket-space/ 和 data/ 都是 launcher 的兄弟目录（同一 project_root 下）。
"""

import os
import json

_CONFIG_FILE = "launcher_config.json"

# 部署站点文件夹名，用于自动探测 project_root
_SITE_DIR = "qc-pocket-space"


def _find_project_root(start_dir):
    """向上查找包含 qc-pocket-space/ 的目录作为 project_root"""
    d = os.path.abspath(start_dir)
    while True:
        if os.path.isdir(os.path.join(d, _SITE_DIR)):
            return d
        parent = os.path.dirname(d)
        if parent == d:  # 到达根目录
            # fallback: 假设 launcher 在 project_root 下 1~2 层
            return os.path.dirname(os.path.dirname(start_dir))
        d = parent


def get_paths():
    """
    根据自身位置推导所有项目路径。
    config.py 在 .../qx-launcher/app/config.py
    """
    # .../qx-launcher/app/config.py → .../qx-launcher/
    launcher_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 自动探测 project_root（包含 qc-pocket-space/ 的目录）
    project_root = _find_project_root(launcher_dir)

    website_root = os.path.join(project_root, "qc-pocket-space")
    data_dir = os.path.join(project_root, "data")

    portable_dir = os.path.join(website_root, "runtime")

    return {
        "launcher_dir": launcher_dir,
        "project_root": project_root,
        "website_root": website_root,
        "portable_dir": portable_dir,
        "backend_dir": os.path.join(website_root, "backend"),
        "caddy_dir": os.path.join(portable_dir, "caddy"),
        "frontend_dir": os.path.join(website_root, "frontend"),
        "data_dir": data_dir,
        "data_disk": os.path.splitdrive(data_dir)[0],
        "runtime_python": os.path.join(portable_dir, "python", "python.exe"),
    }


def load_config(paths):
    """加载持久化配置（目前只需记上次域名）"""
    config_path = os.path.join(paths["launcher_dir"], _CONFIG_FILE)
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"domain": "codenova.cn"}


def save_config(paths, domain):
    """保存域名到配置文件"""
    config_path = os.path.join(paths["launcher_dir"], _CONFIG_FILE)
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"domain": domain}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

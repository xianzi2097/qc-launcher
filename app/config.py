"""
QC Launcher — 路径配置模块
自动推导项目所有路径，零配置。

目录结构（开发机）：
    QC-PocketSpace/
    ├── website/          ← Git 仓库
    ├── data/             ← 用户数据
    └── labs_dev/
        └── qx-launcher/  ← 本程序所在目录
"""

import os
import json

_CONFIG_FILE = "launcher_config.json"


def get_paths():
    """
    根据自身位置推导所有项目路径。
    config.py 在 .../labs_dev/qx-launcher/app/config.py
    """
    # .../labs_dev/qx-launcher/app/config.py → .../labs_dev/qx-launcher/
    launcher_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # .../labs_dev/qx-launcher/ → .../QC-PocketSpace/
    project_root = os.path.dirname(os.path.dirname(launcher_dir))

    # 兼容本地（website/）和服务器（qc-pocket-space/）两种目录名
    website_root = os.path.join(project_root, "website")
    if not os.path.exists(website_root):
        website_root = os.path.join(project_root, "qc-pocket-space")
    data_dir = os.path.join(project_root, "data")

    portable_dir = os.path.join(website_root, "launcher")

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
        "launcher_python": os.path.join(portable_dir, "python", "python.exe"),
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

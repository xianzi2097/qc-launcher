"""
QC Launcher — 路径配置模块
自动推导项目所有路径，零配置。

支持两种目录布局：
    开发机:  CodeNova-Workspace/labs_dev/qx-launcher/
    服务器:  QC-Packet/qc-launcher/
两种情况下 qc-pocket-space/ 和 data_v2/ 都是 launcher 的兄弟目录（同一 project_root 下）。
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
    data_dir = os.path.join(project_root, "data_v2")

    portable_dir = os.path.join(website_root, "runtime")

    return {
        "launcher_dir": launcher_dir,
        "project_root": project_root,
        "website_root": website_root,
        "portable_dir": portable_dir,
        "backend_dir": os.path.join(website_root, "backend_v2"),
        "caddy_dir": os.path.join(portable_dir, "caddy"),
        "caddy_exe": os.path.join(portable_dir, "caddy", "caddy.exe"),
        "frontend_dir": os.path.join(website_root, "frontend"),
        "data_dir": data_dir,
        "data_disk": os.path.splitdrive(data_dir)[0],
        "runtime_python": os.path.join(portable_dir, "python", "python.exe"),
    }


# JSON 里的默认值：首次运行或文件缺失时使用
_DEFAULTS = {
    "domain": "codenova.cn",
    "judge0_address": "38.76.216.46:10654",
    "agent_address": "",
}


def load_config(paths):
    """加载持久化配置，缺失字段自动补全默认值"""
    config_path = os.path.join(paths["launcher_dir"], _CONFIG_FILE)
    data = dict(_DEFAULTS)
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            data.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return data


def save_config(paths, domain, judge0_address="", agent_address=""):
    """保存域名 + Judge0 + Agent 地址到配置文件（每次全量写入）"""
    # 去掉协议前缀，只存纯域名
    while "://" in domain:
        domain = domain.split("://", 1)[-1]
    config_path = os.path.join(paths["launcher_dir"], _CONFIG_FILE)
    try:
        data = {
            "domain": domain,
            "judge0_address": judge0_address.strip(),
            "agent_address": agent_address.strip(),
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

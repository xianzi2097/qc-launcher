"""
QC Launcher — 系统硬件信息检测
CPU / 内存 / data 所在磁盘。
"""

import psutil


def get_cpu_info():
    """获取 CPU 信息：型号、物理核心数、逻辑线程数"""
    info = {"model": "未知", "physical_cores": 0, "logical_cores": 0}
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        info["model"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        winreg.CloseKey(key)
    except Exception:
        info["model"] = f"{psutil.cpu_count(logical=False)}核{psutil.cpu_count()}线程"
    info["physical_cores"] = psutil.cpu_count(logical=False)
    info["logical_cores"] = psutil.cpu_count(logical=True)
    return info


def get_memory_info():
    """获取内存信息：总量(GB)、可用(GB)、使用率(%)"""
    mem = psutil.virtual_memory()
    return {
        "total_gb": round(mem.total / (1024**3), 1),
        "available_gb": round(mem.available / (1024**3), 1),
        "percent": mem.percent,
    }


def get_disk_info(disk_path):
    """获取指定路径所在磁盘的信息"""
    if len(disk_path) == 2 and disk_path[1] == ":":
        disk_path += "\\"
    try:
        usage = psutil.disk_usage(disk_path)
        return {
            "total_gb": round(usage.total / (1024**3), 1),
            "free_gb": round(usage.free / (1024**3), 1),
            "percent": usage.percent,
        }
    except Exception:
        return {"total_gb": 0, "free_gb": 0, "percent": 0}


def get_wifi_ssid() -> str:
    """获取当前连接的 Wi-Fi 名称"""
    import subprocess, re
    try:
        out = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout
        for line in out.splitlines():
            line = line.strip()
            if "SSID" in line and "BSSID" not in line:
                m = re.search(r':\s*(.+)$', line)
                if m:
                    ssid = m.group(1).strip()
                    if ssid and ssid != "(没有网络)":
                        return ssid
    except Exception:
        pass
    return ""

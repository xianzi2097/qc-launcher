@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python.exe main.py
if errorlevel 1 (
    echo.
    echo 启动失败，请确认虚拟环境已创建
    echo 运行: python -m venv .venv
    pause
)

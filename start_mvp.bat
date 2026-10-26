@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 未找到项目虚拟环境 .venv
  echo 请先按 README 的快速开始创建环境并安装依赖。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run_mvp.py
pause

@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist server\.venv\Scripts\python.exe (
  echo 請先執行 windows\setup.bat
  pause & exit /b 1
)
server\.venv\Scripts\python.exe windows\run_server.py
pause

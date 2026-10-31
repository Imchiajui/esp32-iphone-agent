@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
echo [1/3] 檢查 Python 3.10 以上...
set PY=
where py >nul 2>nul && (py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" && set "PY=py -3")
if not defined PY (where python >nul 2>nul && (python -c "import sys; sys.exit(sys.version_info < (3, 10))" && set "PY=python"))
if not defined PY (
  echo 找不到 Python 3.10 以上。請到 python.org 安裝後再執行一次。
  pause & exit /b 1
)
echo [2/3] 建立 server\.venv 並安裝套件...
if not exist server\.venv\Scripts\python.exe %PY% -m venv server\.venv || (pause & exit /b 1)
server\.venv\Scripts\python.exe -m pip install --upgrade pip >nul
server\.venv\Scripts\python.exe -m pip install -e server || (echo 安裝失敗 & pause & exit /b 1)
echo [3/3] 設定檔...
if not exist server\.env (
  copy windows\env.windows.example server\.env >nul
  echo 已建立 server\.env：請用記事本填入 LLM_API_KEY（和模型名稱）。
) else (
  echo server\.env 已存在，保留原內容。
)
if not exist uxplay-win64\bin\uxplay.exe echo 注意：還沒放 uxplay-win64 資料夾（AirPlay 接收程式）。
echo.
echo 完成。之後用 start.bat 啟動。
pause

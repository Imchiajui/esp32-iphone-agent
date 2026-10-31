"""Start the legacy server on Windows with server/.env loaded (what `set -a && . ./.env` does in Git Bash).

Run by start.bat with the server's venv Python. Defaults for this setup: the board is a classic ESP32 BLE bridge on
USB serial (SERIAL_PORT=auto) and UxPlay is the bundled uxplay-win64 next to this folder.
"""

import os
import runpy
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / "server" / ".env"


def parse_env(text: str) -> dict[str, str]:
    """KEY=VALUE lines; # starts a comment outside quotes; backslashes are kept as typed (Windows paths)."""
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export ").strip(), value.strip()
        if value[:1] in ("'", '"'):
            end = value.find(value[0], 1)
            value = value[1:end] if end > 0 else value[1:]
        else:
            value = value.split(" #", 1)[0].split("\t#", 1)[0].strip()
        values[key] = value
    return values


def main() -> None:
    if not ENV.exists():
        sys.exit(f"找不到 {ENV}，請先執行 setup.bat")
    env = parse_env(ENV.read_text(encoding="utf-8"))
    bundled = ROOT / "uxplay-win64" / "bin" / "uxplay.exe"
    env.setdefault("SERIAL_PORT", "auto")
    if bundled.exists():
        env.setdefault("UXPLAY", str(bundled))
    if not env.get("LLM_API_KEY") and "localhost" not in env.get("LLM_BASE_URL", ""):
        print("提醒：server\\.env 的 LLM_API_KEY 是空的，手動操作可以用，但 AI 代理會失敗。")
    os.environ.update(env)
    url = f"http://{os.environ.get('HOST', '127.0.0.1')}:{os.environ.get('PORT', '8890')}"
    print(f"網頁介面：{url}（關掉這個視窗就會停止）")
    threading.Timer(3, webbrowser.open, (url,)).start()
    os.chdir(ROOT / "server")
    runpy.run_module("hidagent", run_name="__main__")


if __name__ == "__main__":
    main()

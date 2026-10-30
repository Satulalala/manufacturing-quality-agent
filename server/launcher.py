"""Start the local API, wait until it is ready, then open the workbench."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser


URL = "http://127.0.0.1:8000"


def _health() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/api/v1/health", timeout=1.2) as response:
            return response.status == 200 and b"quality-agent-workbench" in response.read(2048)
    except (OSError, urllib.error.URLError):
        return False


def main() -> int:
    process = None
    if not _health():
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "info"],
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                print("API 服务启动失败，请查看上方日志。")
                return int(process.returncode or 1)
            if _health():
                break
            time.sleep(0.4)
        else:
            process.terminate()
            print("等待 API 服务就绪超时。")
            return 1

    print(f"质量 Agent 工作台已就绪：{URL}")
    print("按 Ctrl+C 停止本地服务。")
    webbrowser.open(URL)
    if process is None:
        print("检测到已有本地服务；本窗口不会停止该服务。")
        return 0
    try:
        return int(process.wait() or 0)
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Start the Hindi PDF Translator: the web app, the background worker, and the browser.

    python run.py                 # normal start, opens http://127.0.0.1:8080
    python run.py --no-browser    # don't open a browser window

Environment variables (optional): PDFT_PROFILE, PDFT_HOME, PDFT_PORT, PDFT_LLAMA_BIN,
PDFT_TESSERACT. See backend/app/config.py.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"


def wait_until_up(url: str, timeout: float = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            time.sleep(0.3)
    return False


def port_in_use(host: str, port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex((host, port)) == 0


def main() -> int:
    host = "127.0.0.1"  # only this laptop can reach the app
    port = int(os.environ.get("PDFT_PORT", "8080"))
    url = f"http://{host}:{port}"
    if port_in_use(host, port):
        if wait_until_up(f"{url}/api/health", timeout=3):
            print(f"The translator is already running at {url}")
            if "--no-browser" not in sys.argv:
                webbrowser.open(url)
            return 0
        print(f"Port {port} is used by another program. Set PDFT_PORT to a free port and try again.")
        return 1

    # Stop the web app and worker too when this launcher is asked to stop.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    py = sys.executable
    worker = subprocess.Popen([py, "-m", "app.worker"], cwd=BACKEND)
    server = subprocess.Popen(
        [py, "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port), "--log-level", "warning"],
        cwd=BACKEND,
    )
    try:
        if wait_until_up(f"{url}/api/health"):
            print(f"Hindi PDF Translator is running at {url}  (Ctrl+C to stop)")
            if "--no-browser" not in sys.argv:
                webbrowser.open(url)
        else:
            print("The web app did not start; see the messages above.")
        return server.wait()
    except (KeyboardInterrupt, SystemExit):
        return 0
    finally:
        for proc in (server, worker):
            proc.terminate()
        for proc in (server, worker):
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())

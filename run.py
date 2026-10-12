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
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
IS_WINDOWS = os.name == "nt"

# How long the worker gets to unload its model (and stop llama-server) before it is killed.
WORKER_STOP_TIMEOUT = 20.0
# The worker's exit code when another worker already runs for this data folder.
WORKER_LOCKED_EXIT = 3


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


def start_worker(cmd: list[str] | None = None, cwd: Path = BACKEND) -> subprocess.Popen:
    """Start the worker in its own process group on Windows, so it can be sent
    CTRL_BREAK_EVENT (a graceful stop) without stopping this launcher too."""
    kwargs: dict = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(cmd or [sys.executable, "-m", "app.worker"], cwd=cwd, **kwargs)


def request_stop(proc: subprocess.Popen) -> None:
    """Ask the worker to stop: it unloads its model (and stops llama-server) first.
    proc.terminate() would kill it at once on Windows and leave llama-server running."""
    if proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGTERM)
    except (OSError, ValueError):
        pass


def wait_or_kill(proc: subprocess.Popen, timeout: float) -> int | None:
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            return proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return None


def stop_worker(proc: subprocess.Popen, timeout: float = WORKER_STOP_TIMEOUT) -> int | None:
    """Stop the worker gracefully, and only kill it if it doesn't stop in time."""
    if proc.poll() is not None:
        return proc.returncode
    request_stop(proc)
    return wait_or_kill(proc, timeout)




class WorkerSupervisor:
    """Keeps one worker running: if it exits unexpectedly it is started again, with a
    growing delay so a worker that crashes at once doesn't spin."""

    def __init__(self, start: Callable[[], subprocess.Popen], log: Callable[[str], None] = print):
        self._start = start
        self._log = log
        self.proc = start()
        self.started_at = time.monotonic()
        self.restarts = 0
        self._restart_at: float | None = None

    def check(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self._restart_at is not None:
            if now >= self._restart_at:
                self._restart_at = None
                self.proc = self._start()
                self.started_at = now
            return
        code = self.proc.poll()
        if code is None:
            return
        if now - self.started_at > 300:
            self.restarts = 0  # it ran fine for a while: start counting afresh
        self.restarts += 1
        delay = min(2 ** (self.restarts - 1), 60)
        if code == WORKER_LOCKED_EXIT:
            delay = max(delay, 30)
            self._log("Another copy of the translator's worker is already running; it will be used "
                      f"(checking again in {delay}s).")
        else:
            self._log(f"The background worker stopped unexpectedly (exit code {code}); "
                      f"restarting it in {delay}s.")
        self._restart_at = now + delay

    def request_stop(self) -> None:
        self._restart_at = None
        request_stop(self.proc)

    def wait(self, timeout: float = WORKER_STOP_TIMEOUT) -> None:
        if self.proc.poll() is None:
            wait_or_kill(self.proc, timeout)

    def stop(self) -> None:
        self.request_stop()
        self.wait()


def _ignore_further_signals() -> None:
    """While shutting down, a second Ctrl+C or stop request must not cut the clean-up short."""
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, signal.SIG_IGN)
            except (OSError, ValueError):
                pass


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
    for name in ("SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            signal.signal(sig, lambda *_: sys.exit(0))
    py = sys.executable
    worker = WorkerSupervisor(start_worker)
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
        while True:
            code = server.poll()
            if code is not None:
                return code
            worker.check()
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        return 0
    finally:
        _ignore_further_signals()
        # Ask the worker first: it needs time to unload its model and stop llama-server.
        worker.request_stop()
        if server.poll() is None:
            server.terminate()
        worker.wait()
        wait_or_kill(server, 10)


if __name__ == "__main__":
    sys.exit(main())

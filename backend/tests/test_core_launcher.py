"""run.py: the worker is stopped gracefully (so it can unload its model) and restarted
if it exits unexpectedly."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def launcher():
    spec = importlib.util.spec_from_file_location("pdft_launcher", ROOT / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GRACEFUL = """
import signal, sys, time
from pathlib import Path
marker = Path(sys.argv[1])
def stop(*_):
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
if hasattr(signal, "SIGBREAK"):
    signal.signal(signal.SIGBREAK, stop)
print("ready", flush=True)
try:
    while True:
        time.sleep(0.05)
finally:
    marker.write_text("unloaded")
"""

STUBBORN = """
import signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
print("ready", flush=True)
while True:
    time.sleep(0.05)
"""


def test_stop_worker_lets_it_clean_up(launcher, tmp_path):
    marker = tmp_path / "marker"
    proc = launcher.start_worker([sys.executable, "-c", GRACEFUL, str(marker)], cwd=ROOT)
    try:
        time.sleep(1.0)
        assert proc.poll() is None
        code = launcher.stop_worker(proc, timeout=10)
        assert code == 0
        assert marker.read_text() == "unloaded"  # its finally block ran
    finally:
        if proc.poll() is None:
            proc.kill()


@pytest.mark.skipif(os.name == "nt", reason="ignoring SIGTERM is POSIX-only")
def test_stop_worker_kills_it_if_it_does_not_stop(launcher):
    proc = launcher.start_worker([sys.executable, "-c", STUBBORN], cwd=ROOT)
    try:
        time.sleep(1.0)
        started = time.monotonic()
        launcher.stop_worker(proc, timeout=1)
        assert proc.poll() is not None and time.monotonic() - started < 10
    finally:
        if proc.poll() is None:
            proc.kill()


def test_supervisor_restarts_a_worker_that_exits(launcher):
    started = []

    def start():
        proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(5)"])
        started.append(proc)
        return proc

    messages = []
    sup = launcher.WorkerSupervisor(start, log=messages.append)
    started[0].wait(timeout=30)
    now = time.monotonic()
    sup.check(now)  # notices the exit and schedules a restart
    assert len(started) == 1 and "exit code 5" in messages[0]
    sup.check(now + 0.5)  # not yet: first restart waits 1 s
    assert len(started) == 1
    sup.check(now + 1.5)
    assert len(started) == 2
    started[1].wait(timeout=30)
    sup.check(now + 2.0)
    assert sup.restarts == 2  # the delay grows for a worker that keeps crashing
    sup.check(now + 3.0)
    assert len(started) == 2
    sup.check(now + 4.5)
    assert len(started) == 3
    sup.stop()


def test_supervisor_waits_longer_when_another_worker_holds_the_lock(launcher):
    procs = []

    def start():
        proc = subprocess.Popen([sys.executable, "-c", f"import sys; sys.exit({launcher.WORKER_LOCKED_EXIT})"])
        procs.append(proc)
        return proc

    messages = []
    sup = launcher.WorkerSupervisor(start, log=messages.append)
    procs[0].wait(timeout=30)
    now = time.monotonic()
    sup.check(now)
    assert "already running" in messages[0]
    sup.check(now + 10)
    assert len(procs) == 1
    sup.check(now + 31)
    assert len(procs) == 2
    sup.stop()

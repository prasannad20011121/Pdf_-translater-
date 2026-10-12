"""Child-process housekeeping for llama-server (PLAN.md §4.5, §7.4).

- PID files: every llama-server the app starts is recorded under <data>/run. If the
  worker crashes or is killed, the next load() stops the orphan, so a 3-6 GB model
  never stays in memory behind the user's back.
- Windows Job Object: the child is assigned to a job with KILL_ON_JOB_CLOSE, so
  Windows kills it as soon as the worker process ends, however it ends.
- Flag probe: `llama-server --help` tells which optional flags this build knows, so
  an older or newer bundled build never refuses to start over a flag it lacks.
- Log: llama-server's stdout/stderr go to <data>/logs/llama-server.log.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

log = logging.getLogger("pdft.llama")

PID_PREFIX = "llama-server-"
PID_SUFFIX = ".pid"
SERVER_NAME = "llama-server"
LOG_MAX_BYTES = 5 * 1024 * 1024
CREATE_TIME_TOLERANCE_S = 2.0

# subprocess.CREATE_NO_WINDOW only exists on Windows builds of Python.
CREATE_NO_WINDOW = 0x08000000


def popen_flags() -> int:
    """No console window for the child on Windows (a packaged --noconsole app would
    otherwise open one, and closing it would kill Gemma mid-job)."""
    return CREATE_NO_WINDOW if os.name == "nt" else 0


# ---- PID files --------------------------------------------------------------------------

def _create_time(pid: int) -> float | None:
    try:
        return psutil.Process(pid).create_time()
    except (psutil.Error, OSError):
        return None


def _same_process(pid: int | None, create_time: float | None) -> bool:
    """True if `pid` is alive and is the process that was recorded (not a reused PID)."""
    if not pid or not psutil.pid_exists(pid):
        return False
    actual = _create_time(pid)
    if actual is None:
        return False
    return create_time is None or abs(actual - float(create_time)) <= CREATE_TIME_TOLERANCE_S


def looks_like_llama_server(proc: psutil.Process) -> bool:
    """Only ever kill a process whose name or command line is llama-server."""
    try:
        name = (proc.name() or "").lower()
        if SERVER_NAME in name:
            return True
        cmdline = proc.cmdline()
    except (psutil.Error, OSError):
        return False
    # A launcher script (tests, or a .cmd wrapper) shows up as "<interpreter> <script>".
    return any(SERVER_NAME in Path(arg).name.lower() for arg in cmdline[:2])


def write_pid_file(run_dir: Path, proc: subprocess.Popen, info: dict[str, Any]) -> Path | None:
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        me = psutil.Process()
        data = {
            "pid": proc.pid,
            "create_time": _create_time(proc.pid),
            "owner_pid": me.pid,
            "owner_create_time": me.create_time(),
            "started": datetime.now(timezone.utc).isoformat(),
            **info,
        }
        path = run_dir / f"{PID_PREFIX}{proc.pid}{PID_SUFFIX}"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path
    except (OSError, psutil.Error) as e:
        log.warning("could not write the llama-server PID file: %s", e)
        return None


def remove_pid_file(path: Path | None) -> None:
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def kill_stale_servers(run_dir: Path | None) -> list[int]:
    """Stop llama-server processes left behind by a run that crashed or was killed.

    A PID file is stale when the process that started the server is gone. The
    recorded PID is only killed if it is still the same process (same start time)
    and its name or command line is llama-server; otherwise the file is just removed.
    Servers owned by a live process (another running worker) are left alone.
    """
    killed: list[int] = []
    if run_dir is None or not run_dir.is_dir():
        return killed
    for path in sorted(run_dir.glob(f"{PID_PREFIX}*{PID_SUFFIX}")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            pid = int(data["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            remove_pid_file(path)
            continue
        if _same_process(data.get("owner_pid"), data.get("owner_create_time")):
            continue  # its owner is still running and will stop it
        if _same_process(pid, data.get("create_time")):
            try:
                proc = psutil.Process(pid)
                if looks_like_llama_server(proc):
                    log.warning("stopping a llama-server left over from an earlier run (pid %s)", pid)
                    proc.kill()
                    try:
                        proc.wait(timeout=10)
                    except psutil.TimeoutExpired:
                        pass
                    killed.append(pid)
            except psutil.NoSuchProcess:
                pass
            except (psutil.Error, OSError) as e:
                log.warning("could not stop the old llama-server (pid %s): %s", pid, e)
                continue  # keep the file: try again next time
        remove_pid_file(path)
    return killed


# ---- Windows Job Object ---------------------------------------------------------------------

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9


def _job_structures():
    """ctypes layouts of JOBOBJECT_EXTENDED_LIMIT_INFORMATION (winnt.h).

    Defined with portable ctypes types so their sizes can be checked on any OS:
    LARGE_INTEGER = int64, DWORD = uint32, SIZE_T/ULONG_PTR = size_t.
    """
    import ctypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    return JOBOBJECT_BASIC_LIMIT_INFORMATION, JOBOBJECT_EXTENDED_LIMIT_INFORMATION


class KillOnCloseJob:
    """A Windows Job Object that kills its processes when its last handle closes.

    The worker keeps the handle open while llama-server runs. If the worker ends for
    any reason (TerminateProcess from the launcher, a crash, Task Manager), Windows
    closes the handle and kills llama-server with it.
    """

    def __init__(self, handle: int, kernel32: Any = None):
        self.handle = handle
        self._kernel32 = kernel32

    @classmethod
    def assign(cls, proc: subprocess.Popen) -> "KillOnCloseJob | None":
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
            kernel32.SetInformationJobObject.restype = wintypes.BOOL
            kernel32.SetInformationJobObject.argtypes = [
                wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
            kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
            kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

            _, extended_cls = _job_structures()
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                raise ctypes.WinError(ctypes.get_last_error())
            info = extended_cls()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ok = kernel32.SetInformationJobObject(
                job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ctypes.byref(info), ctypes.sizeof(info))
            if ok:
                ok = kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle)))  # type: ignore[attr-defined]
            if not ok:
                err = ctypes.get_last_error()
                kernel32.CloseHandle(job)
                raise ctypes.WinError(err)
            return cls(job, kernel32)
        except Exception as e:  # never stop translation over housekeeping
            log.warning("could not attach llama-server to a kill-on-close job: %s", e)
            return None

    def close(self) -> None:
        """Closing the last handle kills anything still in the job."""
        if self.handle and self._kernel32 is not None:
            try:
                self._kernel32.CloseHandle(self.handle)
            except Exception:
                pass
        self.handle = 0


# ---- flag probe -------------------------------------------------------------------------

_FLAG_RE = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*)")
_flag_cache: dict[tuple[str, int, int], frozenset[str] | None] = {}


def supported_flags(server_bin: str | Path, timeout: float = 30) -> frozenset[str] | None:
    """The command-line flags `llama-server --help` lists, or None if that failed.

    Cached per binary (path, size, modification time).
    """
    path = Path(server_bin)
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key in _flag_cache:
        return _flag_cache[key]
    flags: frozenset[str] | None = None
    try:
        r = subprocess.run(
            [str(path), "--help"], stdin=subprocess.DEVNULL, capture_output=True,
            timeout=timeout, creationflags=popen_flags(),
        )
        text = (r.stdout + r.stderr).decode("utf-8", errors="replace")
        found = frozenset(_FLAG_RE.findall(text))
        flags = found or None
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("could not list llama-server's options: %s", e)
    _flag_cache[key] = flags
    return flags


# ---- log file ---------------------------------------------------------------------------

def open_log(path: Path | None, cmd: list[str]):
    """Open llama-server.log for appending (rotated at 5 MB). None = discard output."""
    if path is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))
        f = path.open("ab")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"\n===== {stamp} starting: {' '.join(cmd)}\n".encode("utf-8", errors="replace"))
        f.flush()
        return f
    except OSError as e:
        log.warning("could not open %s: %s", path, e)
        return None


def log_tail(path: Path | None, lines: int = 4, max_bytes: int = 4096) -> str:
    """The last few lines llama-server wrote, to explain why it stopped."""
    if path is None:
        return ""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    text = text.rsplit("===== ", 1)[-1]  # only this run
    kept = [ln.strip() for ln in text.splitlines()[1:] if ln.strip()]
    return " | ".join(kept[-lines:])

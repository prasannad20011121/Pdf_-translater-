"""llama-server lifecycle: flags, vision mode, proxy bypass, logs, PID files, orphans."""

from __future__ import annotations

import ctypes
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from app.pipeline.translate import proc as procutil
from app.pipeline.translate.base import DocContext, EngineUnavailable
from app.pipeline.translate.llamacpp import LlamaServerEngine

posix_only = pytest.mark.skipif(os.name == "nt", reason="uses a POSIX shebang launcher")


@pytest.fixture()
def fake_bin(tmp_path) -> Path:
    script = Path(__file__).with_name("fake_llama_server.py")
    launcher = tmp_path / "bin" / "llama-server"
    launcher.parent.mkdir()
    launcher.write_text(f"#!{sys.executable}\nimport runpy\nrunpy.run_path({str(script)!r}, run_name='__main__')\n")
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    return launcher


@pytest.fixture()
def model_files(tmp_path) -> tuple[Path, Path]:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    mmproj = tmp_path / "mmproj.gguf"
    mmproj.write_bytes(b"GGUF")
    return model, mmproj


def _engine(fake_bin, model_files, tmp_path, **kw) -> LlamaServerEngine:
    model, mmproj = model_files
    kw.setdefault("log_path", tmp_path / "logs" / "llama-server.log")
    kw.setdefault("run_dir", tmp_path / "run")
    return LlamaServerEngine("gemma4-e2b", "Gemma 4 E2B", 4.0, server_bin=str(fake_bin),
                             model_path=model, mmproj_path=mmproj, **kw)


def _flag_value(cmd: list[str], flag: str) -> str | None:
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


# ---- command line ----------------------------------------------------------------------

@posix_only
def test_text_mode_has_one_slot_no_prompt_cache_and_no_projector(fake_bin, model_files, tmp_path):
    cmd = _engine(fake_bin, model_files, tmp_path).command(1234)
    assert "--mmproj" not in cmd
    assert _flag_value(cmd, "-np") == "1"
    assert _flag_value(cmd, "--cache-ram") == "0"
    assert _flag_value(cmd, "--ctx-checkpoints") == "2"
    assert _flag_value(cmd, "--host") == "127.0.0.1"


@posix_only
def test_vision_mode_adds_the_projector(fake_bin, model_files, tmp_path):
    cmd = _engine(fake_bin, model_files, tmp_path, vision=True).command(1234)
    assert _flag_value(cmd, "--mmproj") == str(model_files[1])


@posix_only
def test_flags_an_older_build_lacks_are_left_out(fake_bin, model_files, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_OLD", "1")
    cmd = _engine(fake_bin, model_files, tmp_path).command(1234)
    assert "--cache-ram" not in cmd and "--ctx-checkpoints" not in cmd
    assert _flag_value(cmd, "-np") == "1"


@posix_only
def test_catalog_extra_args_override_the_defaults(fake_bin, model_files, tmp_path):
    engine = _engine(fake_bin, model_files, tmp_path, extra_args=["--cache-ram", "256"])
    cmd = engine.command(1234)
    assert cmd.count("--cache-ram") == 1 and _flag_value(cmd, "--cache-ram") == "256"


@posix_only
def test_none_leaves_a_flag_out(fake_bin, model_files, tmp_path):
    cmd = _engine(fake_bin, model_files, tmp_path, cache_ram_mib=None, ctx_checkpoints=None).command(1)
    assert "--cache-ram" not in cmd and "--ctx-checkpoints" not in cmd


# ---- lifecycle -----------------------------------------------------------------------------

@posix_only
def test_old_build_starts_and_translates(fake_bin, model_files, tmp_path, monkeypatch):
    """An older llama-server refuses unknown flags; the probe keeps them out."""
    monkeypatch.setenv("FAKE_LLAMA_OLD", "1")
    engine = _engine(fake_bin, model_files, tmp_path)
    engine.load()
    try:
        assert engine.translate(["एक।"], DocContext()) == ["Translated sentence."]
    finally:
        engine.unload()


@posix_only
def test_load_ignores_the_system_proxy(fake_bin, model_files, tmp_path, monkeypatch):
    """127.0.0.1 must never go through HTTP(S)_PROXY (or the Windows system proxy)."""
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")  # nothing listens there
    engine = _engine(fake_bin, model_files, tmp_path, start_timeout_s=20)
    engine.load()
    try:
        assert engine._client is not None and engine._client._trust_env is False
        assert engine.translate(["एक।"], DocContext()) == ["Translated sentence."]
    finally:
        engine.unload()


@posix_only
def test_log_file_and_pid_file(fake_bin, model_files, tmp_path):
    engine = _engine(fake_bin, model_files, tmp_path)
    engine.load()
    try:
        pid = engine._proc.pid
        pid_file = tmp_path / "run" / f"llama-server-{pid}.pid"
        data = json.loads(pid_file.read_text())
        assert data["pid"] == pid and data["owner_pid"] == os.getpid()
    finally:
        engine.unload()
    assert not pid_file.exists()
    log = (tmp_path / "logs" / "llama-server.log").read_text()
    assert "starting:" in log and "fake llama-server listening" in log


@posix_only
def test_crash_reason_comes_from_the_log(fake_bin, model_files, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LLAMA_MODE", "crash")
    engine = _engine(fake_bin, model_files, tmp_path)
    with pytest.raises(EngineUnavailable, match="tensor data is not within the file bounds"):
        engine.load()
    assert engine._proc is None and engine._client is None
    assert list((tmp_path / "run").glob("*.pid")) == []


@posix_only
def test_popen_failure_is_engine_unavailable(model_files, tmp_path):
    not_executable = tmp_path / "llama-server"
    not_executable.write_text("not a program")
    engine = _engine(not_executable, model_files, tmp_path)
    with pytest.raises(EngineUnavailable, match="could not be started"):
        engine.load()


@posix_only
def test_vision_mode_needs_the_projector_file(fake_bin, model_files, tmp_path):
    model_files[1].unlink()
    with pytest.raises(EngineUnavailable, match="mmproj"):
        _engine(fake_bin, model_files, tmp_path, vision=True).load()


def test_reread_page_needs_vision_mode(tmp_path):
    engine = LlamaServerEngine("x", "x", 1.0, server_bin="x", model_path=tmp_path / "m.gguf")
    with pytest.raises(EngineUnavailable, match="text only"):
        engine.reread_page(tmp_path / "page.png")


# ---- orphans from crashed runs ----------------------------------------------------------------

def _dead_owner() -> tuple[int, float]:
    """A process that has already exited: stands in for a crashed worker."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    create_time = psutil.Process(p.pid).create_time()
    p.wait()
    return p.pid, create_time


def _write_stale_pid_file(run_dir: Path, proc: subprocess.Popen) -> Path:
    owner_pid, owner_created = _dead_owner()
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"llama-server-{proc.pid}.pid"
    path.write_text(json.dumps({
        "pid": proc.pid, "create_time": psutil.Process(proc.pid).create_time(),
        "owner_pid": owner_pid, "owner_create_time": owner_created,
    }))
    return path


@posix_only
def test_load_stops_a_server_left_by_a_crashed_run(fake_bin, model_files, tmp_path):
    orphan = subprocess.Popen([str(fake_bin), "--port", "0"], stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.3)
        pid_file = _write_stale_pid_file(tmp_path / "run", orphan)
        engine = _engine(fake_bin, model_files, tmp_path)
        engine.load()
        engine.unload()
        assert orphan.wait(timeout=10) is not None
        assert not pid_file.exists()
    finally:
        if orphan.poll() is None:
            orphan.kill()


def test_stale_pid_file_of_another_program_is_not_killed(tmp_path):
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        pid_file = _write_stale_pid_file(tmp_path / "run", other)
        assert procutil.kill_stale_servers(tmp_path / "run") == []
        assert other.poll() is None, "a process that isn't llama-server must never be killed"
        assert not pid_file.exists()
    finally:
        other.kill()
        other.wait()


@posix_only
def test_server_with_a_live_owner_is_left_alone(fake_bin, tmp_path):
    server = subprocess.Popen([str(fake_bin), "--port", "0"], stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.3)
        procutil.write_pid_file(tmp_path / "run", server, {})  # owner = this test process
        assert procutil.kill_stale_servers(tmp_path / "run") == []
        assert server.poll() is None
    finally:
        server.kill()
        server.wait()


def test_garbage_pid_files_are_removed(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "llama-server-1.pid").write_text("not json")
    procutil.kill_stale_servers(run)
    assert list(run.iterdir()) == []


# ---- Windows Job Object and helpers --------------------------------------------------------

@pytest.mark.skipif(ctypes.sizeof(ctypes.c_void_p) != 8, reason="layout checked for 64-bit")
def test_job_object_structures_match_winnt_h():
    basic, extended = procutil._job_structures()
    assert ctypes.sizeof(basic) == 64
    assert ctypes.sizeof(extended) == 144


@pytest.mark.skipif(os.name == "nt", reason="non-Windows behaviour")
def test_job_object_is_a_no_op_off_windows():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        assert procutil.KillOnCloseJob.assign(p) is None
        assert procutil.popen_flags() == 0
    finally:
        p.wait()


def test_log_tail_shows_only_the_last_run(tmp_path):
    log = tmp_path / "llama-server.log"
    f = procutil.open_log(log, ["llama-server", "-m", "a"])
    f.write(b"old run error\n")
    f.close()
    f = procutil.open_log(log, ["llama-server", "-m", "b"])
    f.write(b"loading\nerror: out of memory\n")
    f.close()
    assert procutil.log_tail(log) == "loading | error: out of memory"


def test_log_is_rotated_when_large(tmp_path, monkeypatch):
    monkeypatch.setattr(procutil, "LOG_MAX_BYTES", 10)
    log = tmp_path / "llama-server.log"
    log.write_bytes(b"x" * 100)
    procutil.open_log(log, ["llama-server"]).close()
    assert (tmp_path / "llama-server.log.1").stat().st_size == 100
    assert log.stat().st_size < 100

"""Gemma 4 (or any catalog GGUF model) through llama.cpp's llama-server (PLAN.md §4.5).

The app starts llama-server as a child process only for the translation stage, on
127.0.0.1 and a random free port, and stops it afterwards so all its memory returns.
For development, base_url can point at a server that is already running.

Memory: the server runs with one slot and its host-memory prompt cache switched off
(by default llama-server keeps up to 8 GiB of old prompt states and opens 4 slots,
which grows during a long job). The vision projector (--mmproj) is only loaded when
the engine is created for page re-reading (vision=True); text translation doesn't
need it. Flags this llama-server build doesn't know are left out (see proc.py).

Housekeeping (proc.py): stdout/stderr go to <data>/logs/llama-server.log, a PID file
under <data>/run lets the next start stop a server orphaned by a crash, and on
Windows the child is tied to a kill-on-close Job Object.
"""

from __future__ import annotations

import base64
import socket
import subprocess
import time
from pathlib import Path

import httpx

from . import proc as procutil
from .base import DocContext, EngineUnavailable, Translator
from .prompts import SYSTEM, output_schema, parse_output, user_prompt

START_TIMEOUT_S = 180

# Optional memory-limiting flags: (aliases this build may use, setting name).
# They are checked against `llama-server --help`, so a build without them still starts.
OPTIONAL_FLAGS = {
    "parallel": ("-np", "--parallel"),
    "cache_ram_mib": ("--cache-ram", "-cram"),
    "ctx_checkpoints": ("--ctx-checkpoints", "-ctxcp", "--swa-checkpoints"),
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def local_client(base_url: str, timeout: float = 30) -> httpx.Client:
    """An HTTP client for 127.0.0.1 that never goes through a proxy.

    httpx reads HTTP(S)_PROXY and, on Windows, the system proxy from the registry
    (without its "<local>" bypass list). Through a proxy, /health fails and the
    document text would be sent to the proxy, so environment settings are ignored.
    """
    return httpx.Client(base_url=base_url, timeout=timeout, trust_env=False)


class LlamaServerEngine(Translator):
    unit = "paragraph"
    uses_placeholders = True

    def __init__(
        self,
        model_id: str,
        label: str,
        ram_gb: float,
        server_bin: str | None = None,
        model_path: Path | None = None,
        mmproj_path: Path | None = None,
        ctx: int = 6144,
        threads: int = 3,
        temperature: float = 0.2,
        timeout_s_per_sentence: float = 90,
        extra_args: list[str] | None = None,
        base_url: str | None = None,
        *,
        vision: bool = False,
        parallel: int | None = 1,
        cache_ram_mib: int | None = 0,
        ctx_checkpoints: int | None = 2,
        log_path: Path | None = None,
        run_dir: Path | None = None,
        start_timeout_s: float | None = None,
    ):
        self.id = model_id
        self.label = label
        self.ram_gb = ram_gb
        self.server_bin = server_bin
        self.model_path = model_path
        self.mmproj_path = mmproj_path
        self.ctx = ctx
        self.threads = threads
        self.temperature = temperature
        self.timeout_s_per_sentence = timeout_s_per_sentence
        self.extra_args = list(extra_args or [])
        self.base_url = base_url
        # vision=True: started for page re-reading, with the --mmproj projector.
        self.vision = vision
        self.parallel = parallel
        self.cache_ram_mib = cache_ram_mib
        self.ctx_checkpoints = ctx_checkpoints
        self.log_path = Path(log_path) if log_path else None
        self.run_dir = Path(run_dir) if run_dir else None
        self.start_timeout_s = start_timeout_s
        self._external = base_url is not None
        self._proc: subprocess.Popen | None = None
        self._client: httpx.Client | None = None
        self._log_file = None
        self._pid_file: Path | None = None
        self._job: procutil.KillOnCloseJob | None = None

    # ---- lifecycle -------------------------------------------------------------

    def _optional_args(self) -> list[str]:
        wanted = {
            "parallel": self.parallel,
            "cache_ram_mib": self.cache_ram_mib,
            "ctx_checkpoints": self.ctx_checkpoints,
        }
        known = procutil.supported_flags(self.server_bin) if self.server_bin else None
        args: list[str] = []
        for key, value in wanted.items():
            if value is None:
                continue
            aliases = OPTIONAL_FLAGS[key]
            if any(a in self.extra_args for a in aliases):
                continue  # the catalog's extra_args set it explicitly
            if known is None:
                flag = aliases[0]  # couldn't ask the binary: assume a current build
            else:
                flag = next((a for a in aliases if a in known), None)
                if flag is None:
                    continue  # this build doesn't have it
            args += [flag, str(value)]
        return args

    def command(self, port: int) -> list[str]:
        cmd = [
            str(self.server_bin), "-m", str(self.model_path),
            "-c", str(self.ctx), "-t", str(self.threads),
            "--host", "127.0.0.1", "--port", str(port),
        ]
        cmd += self._optional_args()
        if self.vision and self.mmproj_path and Path(self.mmproj_path).exists():
            cmd += ["--mmproj", str(self.mmproj_path)]
        return cmd + list(self.extra_args)

    def _start_process(self) -> None:
        if not self.server_bin or not Path(self.server_bin).exists():
            raise EngineUnavailable("llama-server was not found (see the install guide)")
        if not self.model_path or not Path(self.model_path).exists():
            raise EngineUnavailable(f"model file not found: {self.model_path}")
        if self.vision and not (self.mmproj_path and Path(self.mmproj_path).exists()):
            raise EngineUnavailable("the vision file (mmproj) for page re-reading is not installed")
        procutil.kill_stale_servers(self.run_dir)
        port = _free_port()
        self.base_url = f"http://127.0.0.1:{port}"
        cmd = self.command(port)
        self._log_file = procutil.open_log(self.log_path, cmd)
        out = self._log_file if self._log_file is not None else subprocess.DEVNULL
        try:
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                creationflags=procutil.popen_flags(),
            )
        except OSError as e:  # e.g. antivirus blocked llama-server.exe
            raise EngineUnavailable(f"llama-server could not be started: {e}") from e
        self._job = procutil.KillOnCloseJob.assign(self._proc)
        if self.run_dir is not None:
            self._pid_file = procutil.write_pid_file(self.run_dir, self._proc, {
                "exe": str(self.server_bin), "port": port, "model": str(self.model_path),
            })

    def _exit_reason(self) -> str:
        code = self._proc.returncode if self._proc is not None else None
        tail = procutil.log_tail(self.log_path)
        return f"llama-server exited with code {code}" + (f": {tail}" if tail else "")

    def load(self) -> None:
        try:
            if not self._external:
                self._start_process()
            self._client = local_client(self.base_url)
            deadline = time.monotonic() + (self.start_timeout_s or START_TIMEOUT_S)
            while time.monotonic() < deadline:
                if self._proc is not None and self._proc.poll() is not None:
                    raise EngineUnavailable(self._exit_reason())
                try:
                    if self._client.get("/health").status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            raise EngineUnavailable("llama-server did not become ready in time")
        except EngineUnavailable:
            self.unload()
            raise
        except Exception as e:  # anything else is still "this engine can't run here"
            self.unload()
            raise EngineUnavailable(f"llama-server could not be started: {type(e).__name__}: {e}") from e

    def unload(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._proc is not None:
            if self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    try:
                        self._proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
            self._proc = None
        if self._job is not None:
            self._job.close()
            self._job = None
        procutil.remove_pid_file(self._pid_file)
        self._pid_file = None
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None

    # ---- translation -----------------------------------------------------------

    def _chat(self, messages: list[dict], schema: dict | None, timeout: float, max_tokens: int) -> str:
        if self._client is None:
            raise EngineUnavailable("engine not loaded")
        body: dict = {
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "translation", "schema": schema},
            }
        try:
            r = self._client.post("/v1/chat/completions", json=body, timeout=timeout)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"] or ""
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            if self._proc is not None and self._proc.poll() is not None:
                raise EngineUnavailable("llama-server stopped") from e
            raise

    def translate(self, texts: list[str], ctx: DocContext) -> list[str | None]:
        """texts = the protected sentences of one paragraph."""
        if not texts:
            return []
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_prompt(texts, ctx)},
        ]
        # English needs far fewer tokens than the Hindi has characters; this is only a cap
        # that stops a looping model early.
        max_tokens = 64 + sum(len(t) for t in texts)
        timeout = self.timeout_s_per_sentence * len(texts)
        try:
            content = self._chat(messages, output_schema(len(texts)), timeout, max_tokens)
        except EngineUnavailable:
            raise
        except Exception:
            return [None] * len(texts)
        return parse_output(content, len(texts))

    def reread_page(self, png_path: Path, timeout: float = 600) -> str | None:
        """Read the Hindi text of a page image. Phase 2.

        Needs an engine created with vision=True (ModelManager.create(model_id, vision=True)),
        which starts llama-server with the mmproj projector.
        """
        if not self.vision:
            raise EngineUnavailable("this engine was started for text only (create it with vision=True)")
        data = base64.b64encode(Path(png_path).read_bytes()).decode()
        messages = [
            {"role": "system", "content": "You transcribe Hindi documents exactly. Output only the text."},
            {"role": "user", "content": [
                {"type": "text", "text": "Transcribe all text on this page exactly as written, in reading "
                                          "order. Mark stamps as [STAMP], signatures as [SIGNATURE], and "
                                          "handwriting as [HANDWRITTEN: ...]."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
            ]},
        ]
        try:
            return self._chat(messages, None, timeout, max_tokens=4096).strip() or None
        except EngineUnavailable:
            raise
        except Exception:
            return None

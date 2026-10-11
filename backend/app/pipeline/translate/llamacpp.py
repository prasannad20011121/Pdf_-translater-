"""Gemma 4 (or any catalog GGUF model) through llama.cpp's llama-server (PLAN.md §4.5).

The app starts llama-server as a child process only for the translation stage, on
127.0.0.1 and a random free port, and stops it afterwards so all its memory returns.
For development, base_url can point at a server that is already running.
"""

from __future__ import annotations

import base64
import socket
import subprocess
import time
from pathlib import Path

import httpx

from .base import DocContext, EngineUnavailable, Translator
from .prompts import SYSTEM, output_schema, parse_output, user_prompt

START_TIMEOUT_S = 180


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
        self.extra_args = extra_args or []
        self.base_url = base_url
        self._external = base_url is not None
        self._proc: subprocess.Popen | None = None
        self._client: httpx.Client | None = None

    # ---- lifecycle -------------------------------------------------------------

    def command(self, port: int) -> list[str]:
        cmd = [
            str(self.server_bin), "-m", str(self.model_path),
            "-c", str(self.ctx), "-t", str(self.threads),
            "--host", "127.0.0.1", "--port", str(port),
        ]
        if self.mmproj_path and Path(self.mmproj_path).exists():
            cmd += ["--mmproj", str(self.mmproj_path)]
        return cmd + list(self.extra_args)

    def load(self) -> None:
        if not self._external:
            if not self.server_bin or not Path(self.server_bin).exists():
                raise EngineUnavailable("llama-server was not found (see the install guide)")
            if not self.model_path or not Path(self.model_path).exists():
                raise EngineUnavailable(f"model file not found: {self.model_path}")
            port = _free_port()
            self.base_url = f"http://127.0.0.1:{port}"
            self._proc = subprocess.Popen(
                self.command(port), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        self._client = httpx.Client(base_url=self.base_url, timeout=30)
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise EngineUnavailable(f"llama-server exited with code {self._proc.returncode}")
            try:
                if self._client.get("/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        self.unload()
        raise EngineUnavailable("llama-server did not become ready in time")

    def unload(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

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
        """Read the Hindi text of a page image (needs the mmproj vision file). Phase 2."""
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

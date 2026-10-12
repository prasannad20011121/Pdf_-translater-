"""A stand-in for llama.cpp's llama-server, for tests.

Accepts the same command-line flags the app passes, serves /health and an
OpenAI-style /v1/chat/completions that "translates" each numbered sentence by
keeping its placeholders, so the app's JSON and placeholder handling is exercised.

Environment switches:
- FAKE_LLAMA_MODE=garbage  return unusable output
- FAKE_LLAMA_MODE=crash    write an error to stderr and exit at once
- FAKE_LLAMA_OLD=1         behave like an older build: no --cache-ram/--ctx-checkpoints,
                           and refuse unknown flags (as llama-server does)
- FAKE_LLAMA_ARGV_FILE     write the command-line arguments (JSON) to this file
"""

import argparse
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PLACEHOLDER = re.compile(r"⟦[A-Z]\d+⟧")


def fake_translate(sentence: str) -> str:
    tokens = PLACEHOLDER.findall(sentence)
    return ("Translated sentence " + " ".join(tokens)).strip() + "."


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length))
        user = req["messages"][-1]["content"]
        text = user if isinstance(user, str) else ""
        sentences = re.findall(r"^\[(\d+)\] (.*)$", text, flags=re.MULTILINE)
        if os.environ.get("FAKE_LLAMA_MODE") == "garbage":
            content = "Sure! Here is the translation you asked for."
        else:
            content = json.dumps({n: fake_translate(s) for n, s in sentences}, ensure_ascii=False)
        self._send(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})


def main() -> None:
    old = os.environ.get("FAKE_LLAMA_OLD") == "1"
    ap = argparse.ArgumentParser(prog="llama-server")
    ap.add_argument("-m")
    ap.add_argument("-c")
    ap.add_argument("-t")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--mmproj")
    ap.add_argument("-np", "--parallel")
    if not old:
        ap.add_argument("-cram", "--cache-ram")
        ap.add_argument("-ctxcp", "--ctx-checkpoints")
    args = ap.parse_args() if old else ap.parse_known_args()[0]
    if os.environ.get("FAKE_LLAMA_ARGV_FILE"):
        with open(os.environ["FAKE_LLAMA_ARGV_FILE"], "w", encoding="utf-8") as f:
            json.dump(sys.argv[1:], f)
    if os.environ.get("FAKE_LLAMA_MODE") == "crash":
        print("error: failed to load model: tensor data is not within the file bounds", file=sys.stderr)
        sys.exit(3)
    print(f"fake llama-server listening on {args.host}:{args.port}", file=sys.stderr, flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())

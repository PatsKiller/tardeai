#!/usr/bin/env python3
"""chatgpt_oauth_proxy.py — local OpenAI-compatible proxy to the FREE ChatGPT (openai-codex OAuth) lane,
mirroring the Grok xAI-OAuth proxy on :8645. It drives the operator's already-authenticated `hermes` codex
CLI inside a real pseudo-TTY (pexpect) — **Hermes manages the OAuth; this proxy never reads or refreshes raw
tokens**. No API key, no metered OpenAI API. Advisory / oversight use only.

Endpoints (127.0.0.1:8646 by default):
  GET  /health               -> {status, upstream, authenticated, token_expired, note}
  GET  /v1/models            -> codex model list
  POST /v1/chat/completions  -> OpenAI chat-completions response (streaming + non-streaming)

If the ChatGPT session has ended, a call returns 401 with a re-login hint:
  hermes auth add openai-codex --type oauth   (free under your ChatGPT subscription)
"""
import base64
import json
import os
import re
import shlex
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERMES = os.environ.get("HERMES_BIN", os.path.expanduser("~/.local/bin/hermes"))
HOST = os.environ.get("CHATGPT_PROXY_HOST", "127.0.0.1")
PORT = int(os.environ.get("CHATGPT_PROXY_PORT", "8646"))
# Probed against this account 2026-09-05, one request per slug:
#   gpt-5.5        200 OK
#   gpt-5.4-mini   200 OK
#   gpt-5.4        400 "not supported when using Codex with a ChatGPT account"
#   gpt-5.3-codex  400        gpt-5.1-codex 400        gpt-5-codex 400
#
# The default was gpt-5.4, so EVERY request through this proxy returned 400 —
# 11 of 11 attempts on 2026-09-05, a 100% error rate that the research-lane
# monitor reported as an error streak without ever naming the cause. The slug
# was presumably valid when it was written; the account's Codex model set moved
# and the constant did not.
DEFAULT_MODEL = os.environ.get("CHATGPT_PROXY_MODEL", "gpt-5.5")
AUTH_JSON = os.path.expanduser("~/.hermes/auth.json")
TIMEOUT = int(os.environ.get("CHATGPT_PROXY_TIMEOUT", "240"))
KEEPALIVE_INTERVAL = int(os.environ.get("CHATGPT_PROXY_KEEPALIVE_INTERVAL", "25"))
# Slugs this ChatGPT account's Codex backend actually accepts, verified by
# request on 2026-09-05. The previous list contained two that 400 —
# gpt-5.4 and gpt-5.3-codex — and its comment asserted the opposite of what the
# backend does, which is how the broken default survived: the list looked like
# evidence and was an assumption. Re-probe before adding a slug here.
MODELS = ["gpt-5.5", "gpt-5.4-mini"]
_SESSION_LINE = re.compile(r"\n?session_id:\s*\S+\s*$")

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07")
_RELOGIN = "hermes auth add openai-codex --type oauth   (free under your ChatGPT subscription)"


def _codex_token_state():
    """Returns (present, expired) from ~/.hermes/auth.json WITHOUT extracting/using the secret — only the
    access_token's `exp` claim (public, unsigned-read) to flag a stale session. Never sends the token."""
    try:
        d = json.load(open(AUTH_JSON))
        cdx = (d.get("providers") or {}).get("openai-codex") or {}
        tokens = cdx.get("tokens") or {}
        at = tokens.get("access_token")
        if not at:
            return False, None
        has_refresh = bool(tokens.get("refresh_token"))
        try:
            p = at.split(".")[1]
            p += "=" * (-len(p) % 4)
            exp = json.loads(base64.urlsafe_b64decode(p)).get("exp")
            jwt_expired = bool(exp) and exp < time.time()
            if jwt_expired and has_refresh:
                return True, False
            return True, jwt_expired
        except Exception:
            return True, None
    except Exception:
        return False, None


def _flatten(messages):
    parts = []
    for m in messages or []:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if role == "system":
            parts.append(f"[system]\n{content}")
        elif role == "assistant":
            parts.append(f"[assistant]\n{content}")
        else:
            parts.append(str(content))
    return "\n\n".join(p for p in parts if p).strip()


def _run_codex(prompt, model):
    """One-shot codex completion via `hermes chat -q ... -Q` (non-interactive programmatic mode). Plain
    subprocess — no TTY needed. Stateless per request. Hermes owns the OAuth (no raw token handling here)."""
    import subprocess
    r = subprocess.run([HERMES, "chat", "-q", prompt, "-Q", "-m", model, "--provider", "openai-codex"],
                       capture_output=True, text=True, timeout=TIMEOUT,
                       env={**os.environ, "TERM": "dumb"})
    out = _ANSI.sub("", r.stdout or "").replace("\r", "").strip()
    out = _SESSION_LINE.sub("", out).strip()  # drop the trailing "session_id: ..." line hermes appends
    err = (r.stderr or "").strip()
    low = (out + " " + err).lower()
    if any(s in low for s in ("session has ended", "please log in again", "token refresh failed",
                              "not logged in", "auth_pending")):
        raise RuntimeError("AUTH_EXPIRED")
    if r.returncode != 0 or not out:
        raise RuntimeError(f"CODEX_RUN_FAILED: {(err or out)[-300:] or 'empty response'}")
    return out


def _sse_chunk(completion_id, model, created, delta, finish_reason=None, usage=None):
    obj = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason,
        }],
    }
    if usage is not None:
        obj["usage"] = usage
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _begin_sse_stream(handler):
    # HTTP/1.1 + chunked framing is required: Node/undici clients (OpenClaw) cannot
    # consume an unframed HTTP/1.0 stream — they hang waiting for body length and
    # eventually abort with "terminated". curl tolerates read-until-close; undici doesn't.
    handler.send_response(200)
    handler.send_header("content-type", "text/event-stream; charset=utf-8")
    handler.send_header("cache-control", "no-cache")
    handler.send_header("transfer-encoding", "chunked")
    handler.end_headers()


def _write_chunked(handler, data: bytes):
    handler.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
    handler.wfile.flush()


def _write_sse_chunk(handler, completion_id, model, created, delta, finish_reason=None, usage=None):
    _write_chunked(handler, _sse_chunk(
        completion_id, model, created, delta, finish_reason=finish_reason, usage=usage
    ).encode())


def _finish_sse_stream(handler, completion_id, model, created, text, include_usage=False):
    if text:
        _write_sse_chunk(handler, completion_id, model, created, {"content": text})
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0} if include_usage else None
    _write_sse_chunk(handler, completion_id, model, created, {}, finish_reason="stop", usage=usage)
    _write_chunked(handler, b"data: [DONE]\n\n")
    handler.wfile.write(b"0\r\n\r\n")
    handler.wfile.flush()


def _run_codex_streaming(handler, completion_id, model, created, prompt, model_name):
    """Run hermes in a worker thread and emit empty SSE keepalives while waiting."""
    state = {"text": None, "error": None}
    done = threading.Event()

    def worker():
        try:
            state["text"] = _run_codex(prompt, model_name)
        except Exception as exc:
            state["error"] = exc
        finally:
            done.set()

    threading.Thread(target=worker, daemon=True).start()
    while not done.wait(timeout=KEEPALIVE_INTERVAL):
        _write_sse_chunk(handler, completion_id, model, created, {"content": ""})

    if state["error"]:
        raise state["error"]
    return state["text"]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # required for chunked streaming (see _begin_sse_stream)

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/health"):
            present, expired = _codex_token_state()
            note = ("ready" if present and not expired else
                    "session may be expired — a call will confirm; re-login: " + _RELOGIN
                    if present else "openai-codex not logged in — " + _RELOGIN)
            return self._send(200, {"status": "ok", "upstream": "ChatGPT openai-codex OAuth",
                                    "authenticated": bool(present), "token_expired": expired, "note": note})
        if self.path.startswith("/v1/models"):
            return self._send(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in MODELS]})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(n) or "{}")
        except Exception:
            return self._send(400, {"error": "bad json"})
        prompt = _flatten(body.get("messages"))
        model = body.get("model") or DEFAULT_MODEL
        if model not in MODELS:
            model = DEFAULT_MODEL
        if not prompt:
            return self._send(400, {"error": "no messages"})
        t0 = time.time()
        completion_id = f"chatcmpl-codex-{int(t0)}"
        created = int(t0)
        stream = bool(body.get("stream"))
        stream_opts = body.get("stream_options") or {}
        include_usage = stream_opts.get("include_usage") is True
        if stream:
            # Emit the role preamble before hermes runs so the client's idle
            # timeout does not fire while the upstream OAuth call is in flight.
            _begin_sse_stream(self)
            _write_sse_chunk(self, completion_id, model, created, {"role": "assistant", "content": ""})
        try:
            text = (_run_codex_streaming(self, completion_id, model, created, prompt, model)
                    if stream else _run_codex(prompt, model))
        except RuntimeError as e:
            msg = str(e)
            if msg.startswith("AUTH_EXPIRED"):
                if stream:
                    _finish_sse_stream(self, completion_id, model, created,
                                       "ChatGPT openai-codex session ended — re-login: " + _RELOGIN,
                                       include_usage=include_usage)
                    return
                return self._send(401, {"error": {"message": "ChatGPT openai-codex session ended — re-login: "
                                                  + _RELOGIN, "type": "auth_expired"}})
            if stream:
                _finish_sse_stream(self, completion_id, model, created, f"Codex proxy error: {msg[:300]}",
                                   include_usage=include_usage)
                return
            return self._send(502, {"error": {"message": msg[:300], "type": "codex_proxy_error"}})
        except Exception as e:
            if stream:
                _finish_sse_stream(self, completion_id, model, created, f"Codex proxy error: {str(e)[:300]}",
                                   include_usage=include_usage)
                return
            return self._send(502, {"error": {"message": str(e)[:300], "type": "codex_proxy_error"}})
        if stream:
            _finish_sse_stream(self, completion_id, model, created, text, include_usage=include_usage)
            return
        return self._send(200, {
            "id": completion_id, "object": "chat.completion", "created": created, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "_proxy": "chatgpt-oauth (openai-codex, free OAuth, no API key)"})


def main():
    print(f"ChatGPT OAuth proxy → http://{HOST}:{PORT}  (upstream: hermes openai-codex OAuth, model {DEFAULT_MODEL})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

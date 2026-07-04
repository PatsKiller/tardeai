#!/usr/bin/env python3
"""grok_oauth_proxy.py — local OpenAI-compatible proxy to the FREE Grok (xai-oauth) lane,
mirroring chatgpt_oauth_proxy.py on :8646. Drives the operator's authenticated `hermes` CLI
(`--provider xai-oauth`). Hermes manages OAuth; this proxy never reads or refreshes raw tokens.
No API key, no metered xAI API. Advisory / oversight use only.

Endpoints (127.0.0.1:8645 by default):
  GET  /health               -> {status, upstream, authenticated, token_expired, note}
  GET  /v1/models            -> grok model list
  POST /v1/chat/completions  -> OpenAI chat-completions response (streaming + non-streaming)

If the Grok session has ended, a call returns 401 with a re-login hint:
  hermes auth add xai-oauth --type oauth
"""
import base64
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERMES = os.environ.get("HERMES_BIN", os.path.expanduser("~/.local/bin/hermes"))
HOST = os.environ.get("GROK_PROXY_HOST", "127.0.0.1")
PORT = int(os.environ.get("GROK_PROXY_PORT", "8645"))
DEFAULT_MODEL = os.environ.get("GROK_PROXY_MODEL", "grok-3-mini")
AUTH_JSON = os.path.expanduser("~/.hermes/auth.json")
TIMEOUT = int(os.environ.get("GROK_PROXY_TIMEOUT", "240"))
KEEPALIVE_INTERVAL = int(os.environ.get("GROK_PROXY_KEEPALIVE_INTERVAL", "25"))
MODELS = ["grok-4", "grok-3", "grok-3-mini"]
_SESSION_LINE = re.compile(r"\n?session_id:\s*\S+\s*$")

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07")
_RELOGIN = "hermes auth add xai-oauth --type oauth"


def _xai_token_state():
    """Returns (present, expired) from ~/.hermes/auth.json — exp claim only, no secret use."""
    try:
        d = json.load(open(AUTH_JSON))
        xai = (d.get("providers") or {}).get("xai-oauth") or {}
        at = (xai.get("tokens") or {}).get("access_token")
        if not at:
            return False, None
        try:
            p = at.split(".")[1]
            p += "=" * (-len(p) % 4)
            exp = json.loads(base64.urlsafe_b64decode(p)).get("exp")
            return True, (bool(exp) and exp < time.time())
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


def _run_grok(prompt, model):
    import subprocess
    r = subprocess.run(
        [HERMES, "chat", "-q", prompt, "-Q", "-m", model, "--provider", "xai-oauth"],
        capture_output=True, text=True, timeout=TIMEOUT,
        env={**os.environ, "TERM": "dumb"},
    )
    out = _ANSI.sub("", r.stdout or "").replace("\r", "").strip()
    out = _SESSION_LINE.sub("", out).strip()
    err = (r.stderr or "").strip()
    low = (out + " " + err).lower()
    if any(s in low for s in (
        "session has ended", "please log in again", "token refresh failed",
        "not logged in", "auth_pending", "unauthorized", "invalid_grant",
    )):
        raise RuntimeError("AUTH_EXPIRED")
    if r.returncode != 0 or not out:
        raise RuntimeError(f"GROK_RUN_FAILED: {(err or out)[-300:] or 'empty response'}")
    return out


def _run_grok_streaming(handler, completion_id, model, created, prompt, model_name):
    """Run hermes in a worker thread and emit empty SSE keepalives while waiting."""
    state = {"text": None, "error": None}
    done = threading.Event()

    def worker():
        try:
            state["text"] = _run_grok(prompt, model_name)
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
            present, expired = _xai_token_state()
            note = ("ready" if present and not expired else
                    "session may be expired — a call will confirm; re-login: " + _RELOGIN
                    if present else "xai-oauth not logged in — " + _RELOGIN)
            return self._send(200, {"status": "ok", "upstream": "Grok xAI OAuth",
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
        completion_id = f"chatcmpl-grok-{int(t0)}"
        created = int(t0)
        stream = bool(body.get("stream"))
        stream_opts = body.get("stream_options") or {}
        include_usage = stream_opts.get("include_usage") is True
        if stream:
            # Emit the role preamble before hermes runs so OpenClaw's 120s idle
            # timeout does not fire while the upstream OAuth call is in flight.
            _begin_sse_stream(self)
            _write_sse_chunk(self, completion_id, model, created, {"role": "assistant", "content": ""})
        try:
            text = (_run_grok_streaming(self, completion_id, model, created, prompt, model)
                    if stream else _run_grok(prompt, model))
        except RuntimeError as e:
            msg = str(e)
            if msg.startswith("AUTH_EXPIRED"):
                if stream:
                    _finish_sse_stream(self, completion_id, model, created,
                                        "Grok xai-oauth session ended — re-login: " + _RELOGIN,
                                        include_usage=include_usage)
                    return
                return self._send(401, {"error": {"message": "Grok xai-oauth session ended — re-login: "
                                                  + _RELOGIN, "type": "auth_expired"}})
            if stream:
                _finish_sse_stream(self, completion_id, model, created, f"Grok proxy error: {msg[:300]}",
                                    include_usage=include_usage)
                return
            return self._send(502, {"error": {"message": msg[:300], "type": "grok_proxy_error"}})
        except Exception as e:
            if stream:
                _finish_sse_stream(self, completion_id, model, created, f"Grok proxy error: {str(e)[:300]}",
                                    include_usage=include_usage)
                return
            return self._send(502, {"error": {"message": str(e)[:300], "type": "grok_proxy_error"}})
        if stream:
            _finish_sse_stream(self, completion_id, model, created, text, include_usage=include_usage)
            return
        return self._send(200, {
            "id": completion_id, "object": "chat.completion", "created": created, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "_proxy": "grok-oauth (xai-oauth, free OAuth, no API key)"})


def main():
    print(f"Grok OAuth proxy → http://{HOST}:{PORT}  (upstream: hermes xai-oauth, model {DEFAULT_MODEL})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
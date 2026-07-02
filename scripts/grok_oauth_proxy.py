#!/usr/bin/env python3
"""grok_oauth_proxy.py — local OpenAI-compatible proxy to the FREE Grok (xai-oauth) lane,
mirroring chatgpt_oauth_proxy.py on :8646. Drives the operator's authenticated `hermes` CLI
(`--provider xai-oauth`). Hermes manages OAuth; this proxy never reads or refreshes raw tokens.
No API key, no metered xAI API. Advisory / oversight use only.

Endpoints (127.0.0.1:8645 by default):
  GET  /health               -> {status, upstream, authenticated, token_expired, note}
  GET  /v1/models            -> grok model list
  POST /v1/chat/completions  -> OpenAI chat-completions response (non-streaming)

If the Grok session has ended, a call returns 401 with a re-login hint:
  hermes auth add xai-oauth --type oauth
"""
import base64
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERMES = os.environ.get("HERMES_BIN", os.path.expanduser("~/.local/bin/hermes"))
HOST = os.environ.get("GROK_PROXY_HOST", "127.0.0.1")
PORT = int(os.environ.get("GROK_PROXY_PORT", "8645"))
DEFAULT_MODEL = os.environ.get("GROK_PROXY_MODEL", "grok-3-mini")
AUTH_JSON = os.path.expanduser("~/.hermes/auth.json")
TIMEOUT = int(os.environ.get("GROK_PROXY_TIMEOUT", "240"))
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


class Handler(BaseHTTPRequestHandler):
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
        try:
            text = _run_grok(prompt, model)
        except RuntimeError as e:
            msg = str(e)
            if msg.startswith("AUTH_EXPIRED"):
                return self._send(401, {"error": {"message": "Grok xai-oauth session ended — re-login: "
                                                  + _RELOGIN, "type": "auth_expired"}})
            return self._send(502, {"error": {"message": msg[:300], "type": "grok_proxy_error"}})
        except Exception as e:
            return self._send(502, {"error": {"message": str(e)[:300], "type": "grok_proxy_error"}})
        return self._send(200, {
            "id": f"chatcmpl-grok-{int(t0)}", "object": "chat.completion", "created": int(t0), "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "_proxy": "grok-oauth (xai-oauth, free OAuth, no API key)"})


def main():
    print(f"Grok OAuth proxy → http://{HOST}:{PORT}  (upstream: hermes xai-oauth, model {DEFAULT_MODEL})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
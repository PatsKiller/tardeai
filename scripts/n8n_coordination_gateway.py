#!/usr/bin/env python3
"""Localhost coordination gateway process.

Refuses to bind unless TRADEAI_N8N_GATEWAY_HMAC_KEY is present and the
address is 127.0.0.1 on a port that is not a live Trade AI, DOF, Postgres,
or n8n port. The process store is memory only. Loopback is a bind constraint,
not a caller identity. Proxy headers are ignored. It is not installed as a
service by this module.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_coordination_gateway import handle_request  # noqa: E402

KEY_ENV = "TRADEAI_N8N_GATEWAY_HMAC_KEY"
PREVIOUS_KEY_ENV = "TRADEAI_N8N_GATEWAY_HMAC_KEY_PREVIOUS"
BLOCKED_PORTS = frozenset({5432, 5433, 55432, 5678, 7776, 7777, 8088, 8766, 18090})
MIN_KEY_BYTES = 32
MAX_BODY_BYTES = 65536
ALLOWED_PATHS = frozenset({"/healthz", "/v1/coordination"})
PROXY_HEADERS = ("X-Forwarded-For", "X-Real-Ip", "Forwarded")


class BindRefused(RuntimeError):
    pass


def guard_bind(host: str, port: int) -> None:
    if host != "127.0.0.1":
        raise BindRefused("refusing non-loopback bind")
    if port != 0 and (port in BLOCKED_PORTS or port < 1024):
        raise BindRefused("refusing blocked or privileged port")


def load_key(environ: dict[str, str] | None = None) -> bytes:
    source = environ if environ is not None else os.environ
    raw = source.get(KEY_ENV, "")
    key = raw.encode("utf-8")
    if len(key) < MIN_KEY_BYTES:
        raise BindRefused("refusing to bind without a gateway key")
    return key


def load_previous_key(environ: dict[str, str] | None = None) -> bytes | None:
    source = environ if environ is not None else os.environ
    raw = source.get(PREVIOUS_KEY_ENV, "")
    if not raw:
        return None
    key = raw.encode("utf-8")
    if len(key) < MIN_KEY_BYTES:
        raise BindRefused("refusing a short previous gateway key")
    return key


def canonical_path(target: str) -> str | None:
    """Accept only the two exact paths. Decoding must not reveal another path."""
    if not isinstance(target, str) or "\x00" in target or "\\" in target:
        return None
    path = target.split("?", 1)[0]
    decoded = unquote(unquote(path))
    if ".." in decoded or decoded != path:
        return None
    if path not in ALLOWED_PATHS:
        return None
    return path


def dispatch_http(
    method: str,
    target: str,
    headers: dict[str, str] | Any,
    body: bytes,
    *,
    key: bytes,
    expected_origin_sha: str,
    nonce_store: dict[str, float],
    idempotency_store: dict[str, dict],
    now: datetime | None = None,
    previous_key: bytes | None = None,
    max_body: int = MAX_BODY_BYTES,
) -> tuple[int, dict]:
    """One HTTP decision. Proxy headers are not copied into the claim check."""
    del headers  # identity is the HMAC claim; forwarded headers are not read
    path = canonical_path(target)
    if path is None:
        return 404, {"ok": False, "reason": "not_found", "proxy_headers_used_as_auth": False}
    if method == "GET" and path == "/healthz":
        return 200, {"ok": True}
    if method != "POST" or path != "/v1/coordination":
        if method not in {"GET", "POST"}:
            return 405, {"state": "REFUSED", "reason": "unknown_method", "proxy_headers_used_as_auth": False}
        return 404, {"ok": False, "reason": "not_found", "proxy_headers_used_as_auth": False}
    if len(body) > max_body:
        return 413, {"state": "REFUSED", "reason": "body_too_large", "proxy_headers_used_as_auth": False}
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return 400, {"state": "REFUSED", "reason": "malformed_event", "proxy_headers_used_as_auth": False}
    if not isinstance(parsed, dict):
        return 400, {"state": "REFUSED", "reason": "malformed_event", "proxy_headers_used_as_auth": False}
    parsed.pop("peer", None)
    for header in PROXY_HEADERS:
        parsed.pop(header, None)
        parsed.pop(header.lower(), None)
    result = handle_request(
        parsed,
        key=key,
        now=now or datetime.now(timezone.utc),
        nonce_store=nonce_store,
        idempotency_store=idempotency_store,
        expected_origin_sha=expected_origin_sha,
        previous_key=previous_key,
    )
    result["proxy_headers_used_as_auth"] = False
    result["durable"] = False
    status = 403 if result.get("state") == "REFUSED" else 200
    return status, result


def make_handler(key: bytes, expected_origin_sha: str, previous_key: bytes | None = None):
    nonce_store: dict[str, float] = {}
    idempotency_store: dict[str, dict] = {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET", b"")

        def do_POST(self) -> None:  # noqa: N802
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send(400, {"state": "REFUSED", "reason": "malformed_event"})
                return
            if length < 0 or length > MAX_BODY_BYTES:
                self._send(413, {"state": "REFUSED", "reason": "body_too_large", "proxy_headers_used_as_auth": False})
                return
            self._dispatch("POST", self.rfile.read(length))

        def do_PUT(self) -> None:  # noqa: N802
            self._send(405, {"state": "REFUSED", "reason": "unknown_method", "proxy_headers_used_as_auth": False})

        def do_PATCH(self) -> None:  # noqa: N802
            self.do_PUT()

        def do_DELETE(self) -> None:  # noqa: N802
            self.do_PUT()

        def log_message(self, fmt: str, *args) -> None:
            return

        def _dispatch(self, method: str, body: bytes) -> None:
            status, payload = dispatch_http(
                method,
                self.path,
                {key: self.headers.get(key) for key in PROXY_HEADERS},
                body,
                key=key,
                expected_origin_sha=expected_origin_sha,
                nonce_store=nonce_store,
                idempotency_store=idempotency_store,
                previous_key=previous_key,
            )
            self._send(status, payload)

        def _send(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def serve(
    host: str,
    port: int,
    *,
    key: bytes,
    expected_origin_sha: str,
    previous_key: bytes | None = None,
) -> ThreadingHTTPServer:
    guard_bind(host, port)
    if len(key) < MIN_KEY_BYTES:
        raise BindRefused("refusing to bind without a gateway key")
    if not expected_origin_sha:
        raise BindRefused("refusing to bind without an expected origin sha")
    httpd = ThreadingHTTPServer((host, port), make_handler(key, expected_origin_sha, previous_key))
    return httpd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loopback coordination gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args(argv)
    try:
        key = load_key()
        previous = load_previous_key()
        httpd = serve(args.host, args.port, key=key, expected_origin_sha=args.expected_sha, previous_key=previous)
    except BindRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

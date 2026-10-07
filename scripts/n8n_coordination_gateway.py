#!/usr/bin/env python3
"""Localhost coordination gateway process.

Refuses to bind unless TRADEAI_N8N_GATEWAY_HMAC_KEY is present and the
address is 127.0.0.1 on a port that is not a live Trade AI, DOF, Postgres,
or n8n port. The process store is memory only. It is not installed as a
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_coordination_gateway import handle_request  # noqa: E402

KEY_ENV = "TRADEAI_N8N_GATEWAY_HMAC_KEY"
BLOCKED_PORTS = frozenset({5432, 5433, 55432, 5678, 7776, 7777, 8088, 8766, 18090})
MIN_KEY_BYTES = 32


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


def make_handler(key: bytes, expected_origin_sha: str):
    nonce_store: dict[str, float] = {}
    idempotency_store: dict[str, dict] = {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/healthz":
                self._send(404, {"ok": False, "reason": "not_found"})
                return
            self._send(200, {"ok": True})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/coordination":
                self._send(404, {"ok": False, "reason": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send(400, {"state": "REFUSED", "reason": "malformed_event"})
                return
            if length < 0 or length > 65536:
                self._send(413, {"state": "REFUSED", "reason": "body_too_large"})
                return
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                self._send(400, {"state": "REFUSED", "reason": "malformed_event"})
                return
            if not isinstance(body, dict):
                self._send(400, {"state": "REFUSED", "reason": "malformed_event"})
                return
            body.pop("peer", None)
            result = handle_request(
                body,
                key=key,
                now=datetime.now(timezone.utc),
                nonce_store=nonce_store,
                idempotency_store=idempotency_store,
                expected_origin_sha=expected_origin_sha,
            )
            status = 403 if result.get("state") == "REFUSED" else 200
            self._send(status, result)

        def log_message(self, fmt: str, *args) -> None:
            return

        def _send(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def serve(host: str, port: int, *, key: bytes, expected_origin_sha: str) -> ThreadingHTTPServer:
    guard_bind(host, port)
    if len(key) < MIN_KEY_BYTES:
        raise BindRefused("refusing to bind without a gateway key")
    if not expected_origin_sha:
        raise BindRefused("refusing to bind without an expected origin sha")
    httpd = ThreadingHTTPServer((host, port), make_handler(key, expected_origin_sha))
    return httpd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loopback coordination gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args(argv)
    try:
        key = load_key()
        httpd = serve(args.host, args.port, key=key, expected_origin_sha=args.expected_sha)
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

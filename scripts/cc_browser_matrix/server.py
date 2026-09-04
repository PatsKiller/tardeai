#!/usr/bin/env python3
"""Hermetic server for the browser/state matrix.

Serves the REAL built Command Center bundle at /v3/ and answers every /api/*
read from a state-shaped fixture. It is not a mock of the UI — the UI under test
is the production build; only the data plane is synthetic.

Safety rails, unconditional:
  * every non-GET is refused with 403 and recorded; nothing can write
  * no upstream, broker, provider, database or production path is contacted
  * it binds 127.0.0.1 on an ephemeral port and dies with the run

READ_ONLY. Any mutation attempt is evidence, not an action.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import states as S

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".map": "application/json",
}


class MatrixState:
    """Everything the handler needs, and the ledger it writes to."""

    def __init__(self, dist: Path, fixtures: dict[str, Any], build_sha: str):
        self.dist = dist
        self.fixtures = fixtures
        self.build_sha = build_sha
        self.state = S.POPULATED
        self.requests: list[dict[str, Any]] = []
        self.mutation_attempts: list[dict[str, Any]] = []
        self.etags: dict[str, str] = {}
        self.served_304: list[str] = []
        self.lock = threading.Lock()

    def reset(self, state: str) -> None:
        with self.lock:
            self.state = state
            self.requests = []
            self.mutation_attempts = []
            self.served_304 = []


def _default_body(path: str) -> Any:
    """A generic, honest POPULATED body for an endpoint with no named fixture."""
    return {
        "ok": True,
        "data": {
            "items": [],
            "generated_for": path,
            "data_as_of": "2026-09-03",
            "last_repriced": "2026-09-03T13:45:00-04:00",
            "observation": dict(S._BASE_OBS),
            "note": "synthetic matrix fixture",
        },
    }


def make_handler(st: MatrixState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        # ── plumbing ────────────────────────────────────────────────────────
        def _send(self, code: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-CC-Matrix-State", st.state)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _record(self, method: str) -> None:
            with st.lock:
                st.requests.append({"method": method, "path": self.path, "state": st.state})

        # ── reads ───────────────────────────────────────────────────────────
        def do_GET(self) -> None:  # noqa: N802
            self._record("GET")
            path = urlparse(self.path).path
            if path.startswith("/api/") or path == "/api/health":
                return self._api(path)
            return self._static(path)

        def do_HEAD(self) -> None:  # noqa: N802
            self._record("HEAD")
            self._send(200, b"", "text/plain")

        def _api(self, path: str) -> None:
            state = st.state
            base = st.fixtures.get(path) or _default_body(path)

            if state == S.LOADING:
                # A pending read: hold the socket long enough for the browser to
                # render its pending state, then answer. Never a fabricated zero.
                # Held per request but briefly — the driver's settle window is what
                # guarantees the pending render is the one measured.
                time.sleep(0.6)
            if state == S.DISCONNECTED:
                self.close_connection = True
                return
            if state == S.TIMEOUT:
                time.sleep(0.4)
                return self._send(504, json.dumps(S.shape(state, base)).encode(), "application/json")

            body = S.shape(state, base)
            code = S.http_status(state)

            if state == S.MALFORMED:
                return self._send(200, str(body).encode(), "application/json")

            raw = json.dumps(body, separators=(",", ":"), default=str).encode()
            etag = '"' + hashlib.sha256(raw).hexdigest()[:16] + '"'

            if state == S.RETAINED_304:
                inm = self.headers.get("If-None-Match")
                st.etags[path] = etag
                if inm:
                    with st.lock:
                        st.served_304.append(path)
                    return self._send(304, b"", "application/json", {"ETag": inm})
            return self._send(code, raw, "application/json", {"ETag": etag})

        def _static(self, path: str) -> None:
            rel = path[len("/v3") :] if path.startswith("/v3") else path
            if rel in ("", "/"):
                rel = "/index.html"
            if ".." in rel:
                rel = "/index.html"
            f = st.dist / rel.lstrip("/")
            if not f.is_file():
                if f.suffix:
                    return self._send(404, b"not found", "text/plain")
                f = st.dist / "index.html"  # SPA fallback
            if not f.is_file():
                return self._send(404, b"no bundle", "text/plain")
            body = f.read_bytes()
            return self._send(200, body, CONTENT_TYPES.get(f.suffix, "application/octet-stream"))

        # ── every write is refused and recorded ─────────────────────────────
        def _refuse(self, method: str) -> None:
            self._record(method)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                parsed = json.loads(raw) if raw else None
            except Exception:  # noqa: BLE001
                parsed = {"_unparsed_bytes": len(raw)}
            with st.lock:
                st.mutation_attempts.append(
                    {
                        "method": method,
                        "path": self.path,
                        "bytes": len(raw),
                        "body": parsed,
                        "state": st.state,
                        "refused": True,
                    }
                )
            self._send(
                403,
                json.dumps(
                    {
                        "ok": False,
                        "error": "mutation_refused_by_matrix",
                        "method": method,
                        "path": self.path,
                        "detail": "the browser/state matrix is a no-write environment",
                    }
                ).encode(),
                "application/json",
            )

        def do_POST(self) -> None:  # noqa: N802
            self._refuse("POST")

        def do_PUT(self) -> None:  # noqa: N802
            self._refuse("PUT")

        def do_PATCH(self) -> None:  # noqa: N802
            self._refuse("PATCH")

        def do_DELETE(self) -> None:  # noqa: N802
            self._refuse("DELETE")

    return Handler


class _QuietServer(ThreadingHTTPServer):
    """The DISCONNECTED state closes sockets on purpose.

    The resulting BrokenPipe/ConnectionReset is the behaviour under test, not an
    error: logging a traceback per request buries the run's real output. Any other
    exception is still raised.
    """

    daemon_threads = True

    def handle_error(self, request, client_address):  # noqa: D102
        import sys as _sys

        exc = _sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def start(dist: Path, fixtures: dict[str, Any], build_sha: str) -> tuple[ThreadingHTTPServer, MatrixState, str]:
    st = MatrixState(dist, fixtures, build_sha)
    httpd = _QuietServer(("127.0.0.1", 0), make_handler(st))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, st, f"http://127.0.0.1:{httpd.server_address[1]}"

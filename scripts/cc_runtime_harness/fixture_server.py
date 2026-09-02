"""Ephemeral local HTTP server serving synthetic CC fixtures."""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class FixtureState:
    def __init__(self, fixture_root: Path, build_sha: str, synthetic_now: str):
        self.fixture_root = fixture_root
        self.build_sha = build_sha
        self.synthetic_now = synthetic_now
        self.positive = fixture_root / "positive"
        self.mutation_log: list[dict[str, Any]] = []
        self.state_hashes_before: dict[str, str] = {}
        self.etag_map: dict[str, str] = {}
        self.force_304_paths: set[str] = set()
        self.force_partial_paths: set[str] = set()
        self.force_malformed_paths: set[str] = set()
        self.force_network_fail_paths: set[str] = set()
        self.allow_mutation = False
        self.requests: list[dict[str, Any]] = []

    def load_json(self, name: str) -> Any:
        path = self.positive / name
        if not path.exists():
            # try bare name
            path = self.fixture_root / name
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def hash_state(self) -> str:
        payload = {
            "build_sha": self.build_sha,
            "files": {},
        }
        if self.positive.exists():
            for p in sorted(self.positive.glob("*.json")):
                payload["files"][p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def make_handler(state: FixtureState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        def _send(
            self,
            code: int,
            body: bytes,
            content_type: str = "application/json",
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-CC-Harness-Build-Sha", state.build_sha)
            self.send_header("X-CC-Harness-Synthetic-Now", state.synthetic_now)
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: Any, etag: str | None = None) -> None:
            raw = json.dumps(obj, separators=(",", ":"), default=str).encode()
            headers = {}
            if etag:
                headers["ETag"] = etag
                state.etag_map[self.path.split("?")[0]] = etag
            self._send(code, raw, extra_headers=headers)

        def _record(self, method: str) -> None:
            state.requests.append({"method": method, "path": self.path, "client": self.client_address[0]})

        def do_GET(self) -> None:  # noqa: N802
            self._record("GET")
            path = urlparse(self.path).path
            if path in state.force_network_fail_paths:
                self.close_connection = True
                return
            if path in state.force_malformed_paths:
                self._send(200, b"{not-json", content_type="application/json")
                return
            if path in state.force_304_paths:
                inm = self.headers.get("If-None-Match")
                etag = state.etag_map.get(path, '"fixture-etag"')
                if inm == etag or inm is not None:
                    self._send(304, b"", extra_headers={"ETag": etag})
                    return
                # First response sets etag then subsequent 304
                state.etag_map[path] = etag

            mapping = {
                "/api/v2/overview": "overview.json",
                "/api/v2/risk": "risk.json",
                "/api/v2/portfolio/performance": "performance.json",
                "/api/v2/portfolio/book-map": "book_map.json",
                "/api/v2/health": "health.json",
                "/api/v2/trade-ai/summary": "trade_ai_summary.json",
                "/api/v2/trade-ai": "trade_ai_summary.json",
                "/api/v2/risk-regime/latest": "risk_regime.json",
                "/api/v2/paper-proposals": "paper_proposals.json",
                "/api/v2/health/proposals": "health_proposals.json",
                "/api/v2/journal": "journal.json",
                "/api/v2/research-intelligence/freshness": "research_freshness.json",
                "/api/v2/command": "command.json",
                "/api/v2/defense/posture": "defense_posture.json",
                "/api/v2/hermes/health": "hermes_health.json",
                "/api/v2/market-movers": "market_movers.json",
                "/api/v2/paper-trade-readiness": "paper_trade_readiness.json",
                "/api/v2/system/metrics-history": "metrics_history.json",
                "/api/health": "api_health.json",
                "/v3/build-meta.json": "build_meta.json",
            }

            fname = mapping.get(path)
            if fname is None and path.startswith("/v3"):
                # SPA shells (build-meta handled via mapping above)
                html = (
                    "<!doctype html><html><head><title>CC Fixture</title></head>"
                    f'<body data-build-sha="{state.build_sha}">fixture-spa:{path}</body></html>'
                )
                self._send(
                    200,
                    html.encode(),
                    content_type="text/html; charset=utf-8",
                    extra_headers={"X-CC-Build-Sha": state.build_sha},
                )
                return

            if not fname:
                self._json(404, {"ok": False, "error": "not_found", "path": path})
                return

            data = state.load_json(fname)
            if data is None:
                self._json(404, {"ok": False, "error": "fixture_missing", "file": fname})
                return

            if path in state.force_partial_paths and isinstance(data, dict):
                # Drop nested fields to simulate partial
                if "data" in data and isinstance(data["data"], dict):
                    slim = {
                        "ok": data.get("ok", True),
                        "data": {k: data["data"][k] for k in list(data["data"].keys())[:3]},
                        "partial": True,
                    }
                    data = slim
                else:
                    data = {"partial": True, "ok": True}

            etag = '"' + hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16] + '"'
            inm = self.headers.get("If-None-Match")
            if path in state.force_304_paths and inm == etag:
                self._send(304, b"", extra_headers={"ETag": etag})
                return
            self._json(200, data, etag=etag)

        def do_POST(self) -> None:  # noqa: N802
            self._handle_mutation("POST")

        def do_PUT(self) -> None:  # noqa: N802
            self._handle_mutation("PUT")

        def do_PATCH(self) -> None:  # noqa: N802
            self._handle_mutation("PATCH")

        def do_DELETE(self) -> None:  # noqa: N802
            self._handle_mutation("DELETE")

        def _handle_mutation(self, method: str) -> None:
            self._record(method)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            state.mutation_log.append(
                {
                    "method": method,
                    "path": self.path,
                    "bytes": len(body),
                }
            )
            if not state.allow_mutation:
                self._json(
                    403,
                    {
                        "ok": False,
                        "error": "mutation_refused_by_harness",
                        "method": method,
                        "path": self.path,
                    },
                )
                return
            self._json(200, {"ok": True, "mutated": True})

    return Handler


class FixtureServer:
    def __init__(self, state: FixtureState, host: str = "127.0.0.1", port: int = 0):
        self.state = state
        self.httpd = ThreadingHTTPServer((host, port), make_handler(state))
        self.thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> str:
        self.state.state_hashes_before["root"] = self.state.hash_state()
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self.base_url

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread:
            self.thread.join(timeout=5)

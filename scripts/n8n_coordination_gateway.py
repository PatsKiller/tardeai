#!/usr/bin/env python3
"""Localhost coordination gateway process.

Refuses to bind unless TRADEAI_N8N_GATEWAY_HMAC_KEY is present and the
address is 127.0.0.1 on a port that is not a live Trade AI, DOF, Postgres,
or n8n port. Since 2026-10-07 the store is the SQLite coordination ledger
(``--ledger``, default under the persistent-state governance dir): nonces,
receipts and artifact references survive a restart and ``durable`` on a
receipt means the COMMIT returned. ``--no-ledger`` keeps the old memory-only
mode for tests. Loopback is a bind constraint, not a caller identity. Proxy
headers are ignored. The unit file in config/systemd/user/ is installed and
active on the host (tradeai-n8n-coordination-gateway.service, Phase 1).

2026-10-08 (tranche N1): the ``run`` operation on route ``coordination/run``.
A second, optional key (TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N) identifies the
``n8n-relay`` caller and is the only key that may claim scope
``coordination_run``; without it the run scope is unavailable. A run is
recorded as a REQUESTED row in the ledger ``runs`` table for the lanes named in
config/n8n_run_allowlist.json (``--run-allowlist``). This process never spawns
the lane; scripts/n8n_run_executor.py does, from its own unit.

2026-10-09 (n8n maturity B5.3): the read operation ``due`` on route
``coordination/due`` computes the due slots from the lane registry
(``--registry``) and the retry policies (``--retry-policies``), re-read on every
call, plus the run allowlist; a server-minted ``d:`` run key is checked against
the same computation. ``due`` writes nothing.
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

from scripts.lib.n8n_coordination_gateway import PILOT_LANES, build_caller_keys, handle_request  # noqa: E402
from scripts.lib.n8n_due import DEFAULT_REGISTRY_PATH, file_sources  # noqa: E402
from scripts.lib.n8n_retry_policy import DEFAULT_PATH as DEFAULT_RETRY_POLICIES  # noqa: E402
from scripts.lib.n8n_coordination_ledger import (  # noqa: E402
    CoordinationLedger,
    LedgerNonceStore,
    LedgerReceiptStore,
    LedgerRunStore,
)

KEY_ENV = "TRADEAI_N8N_GATEWAY_HMAC_KEY"
PREVIOUS_KEY_ENV = "TRADEAI_N8N_GATEWAY_HMAC_KEY_PREVIOUS"
N8N_KEY_ENV = "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N"
N8N_PREVIOUS_KEY_ENV = "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N_PREVIOUS"
RUN_ALLOWLIST_SCHEMA = "N8nRunAllowlist@v1"
DEFAULT_RUN_ALLOWLIST = ROOT / "config" / "n8n_run_allowlist.json"
BLOCKED_PORTS = frozenset({5432, 5433, 55432, 5678, 7776, 7777, 8088, 8766, 18090})
MIN_KEY_BYTES = 32
MAX_BODY_BYTES = 65536
ALLOWED_PATHS = frozenset({"/healthz", "/v1/coordination"})
PROXY_HEADERS = ("X-Forwarded-For", "X-Real-Ip", "Forwarded")


class BindRefused(RuntimeError):
    pass


class GatewayServer(ThreadingHTTPServer):
    """2026-10-08 (first N1 shadow burst): the stock listen backlog is 5, so a :00 burst wider than that
    overflows the accept queue and the overflowed clients sit on the kernel's 1 s SYN retransmit
    (measured: 16-wide burst 1.05 s with backlog 5, 24 ms with 64). daemon_threads is already True on
    ThreadingHTTPServer; nothing else changes."""

    request_queue_size = 64


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


def load_n8n_key(environ: dict[str, str] | None = None) -> bytes | None:
    """The relay caller's key. Optional: absent means the run scope is unavailable, never a bind refusal."""
    source = environ if environ is not None else os.environ
    raw = source.get(N8N_KEY_ENV, "")
    if not raw:
        return None
    key = raw.encode("utf-8")
    if len(key) < MIN_KEY_BYTES:
        raise BindRefused("refusing a short n8n gateway key")
    return key


def load_n8n_previous_key(environ: dict[str, str] | None = None) -> bytes | None:
    """Overlap key for the relay caller. Empty is the pre-rotation state. A short value refuses the bind."""
    source = environ if environ is not None else os.environ
    raw = source.get(N8N_PREVIOUS_KEY_ENV, "")
    if not raw:
        return None
    key = raw.encode("utf-8")
    if len(key) < MIN_KEY_BYTES:
        raise BindRefused("refusing a short previous n8n gateway key")
    return key


def load_run_allowlist(path: Path | None) -> frozenset[str]:
    """lane_ids with a command in config/n8n_run_allowlist.json. A missing or malformed file yields an
    empty set (every run refused as run_lane_not_allowlisted) rather than a bind refusal."""
    if path is None or not Path(path).is_file():
        return frozenset()
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frozenset()
    if not isinstance(doc, dict) or doc.get("schema") != RUN_ALLOWLIST_SCHEMA:
        return frozenset()
    out = set()
    for entry in doc.get("lanes") or []:
        if isinstance(entry, dict) and isinstance(entry.get("lane_id"), str) and isinstance(entry.get("command"), list):
            out.add(entry["lane_id"])
    return frozenset(out)


def default_ledger_path(environ: dict[str, str] | None = None) -> Path:
    source = environ if environ is not None else os.environ
    explicit = source.get("TRADEAI_N8N_COORDINATION_LEDGER")
    if explicit:
        return Path(explicit)
    root = source.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(root) / "data" / "governance" / "n8n_coordination_ledger.sqlite"


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
    nonce_store: Any,
    idempotency_store: Any,
    now: datetime | None = None,
    previous_key: bytes | None = None,
    max_body: int = MAX_BODY_BYTES,
    ledger_path: Path | None = None,
    lane_allowlist: frozenset[str] | None = None,
    caller_keys: dict | None = None,
    run_store: Any = None,
    run_allowlist: frozenset[str] | None = None,
    due_sources: Any = None,
) -> tuple[int, dict]:
    """One HTTP decision. Proxy headers are not copied into the claim check."""
    del headers  # identity is the HMAC claim; forwarded headers are not read
    path = canonical_path(target)
    if path is None:
        return 404, {"ok": False, "reason": "not_found", "proxy_headers_used_as_auth": False}
    durable = bool(getattr(idempotency_store, "durable", False))
    if method == "GET" and path == "/healthz":
        run_scope = bool(caller_keys and "n8n-relay" in caller_keys) and run_store is not None
        return 200, {"ok": True, "durable": durable, "ledger": str(ledger_path) if ledger_path else None,
                     "run_scope": run_scope, "run_lanes": len(run_allowlist or ())}
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
        lane_allowlist=lane_allowlist,
        caller_keys=caller_keys,
        run_store=run_store,
        run_allowlist=run_allowlist,
        due_sources=due_sources,
    )
    if result.get("schema") == "DueResponse@v1" and result.get("ok") is True:
        return 200, result                   # closed schema (additionalProperties: false); nothing was written
    result["proxy_headers_used_as_auth"] = False
    if result.get("state") == "REFUSED":
        result["durable"] = False            # nothing was written for a refusal
    else:
        result["durable"] = durable and bool(result.get("durable", durable))
    status = 403 if result.get("state") == "REFUSED" else 200
    return status, result


def make_handler(key: bytes, expected_origin_sha: str, previous_key: bytes | None = None,
                 ledger: CoordinationLedger | None = None, ledger_path: Path | None = None,
                 lane_allowlist: frozenset[str] | None = None, n8n_key: bytes | None = None,
                 run_allowlist: frozenset[str] | None = None,
                 n8n_previous_key: bytes | None = None, due_sources: Any = None):
    nonce_store: Any = LedgerNonceStore(ledger) if ledger is not None else {}
    idempotency_store: Any = LedgerReceiptStore(ledger) if ledger is not None else {}
    # runs are durable or nothing: memory-only mode has no executor to drain it, so no run store
    run_store: Any = LedgerRunStore(ledger) if ledger is not None else None
    caller_keys = build_caller_keys(
        key, previous_key=previous_key, n8n_key=n8n_key, n8n_previous_key=n8n_previous_key
    )

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
                ledger_path=ledger_path,
                lane_allowlist=lane_allowlist,
                caller_keys=caller_keys,
                run_store=run_store,
                run_allowlist=run_allowlist,
                due_sources=due_sources,
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
    ledger_path: Path | None = None,
    extra_lanes: frozenset[str] | set[str] | None = None,
    n8n_key: bytes | None = None,
    n8n_previous_key: bytes | None = None,
    run_allowlist_path: Path | None = None,
    registry_path: Path | None = None,
    retry_policies_path: Path | None = None,
) -> ThreadingHTTPServer:
    guard_bind(host, port)
    if len(key) < MIN_KEY_BYTES:
        raise BindRefused("refusing to bind without a gateway key")
    if not expected_origin_sha:
        raise BindRefused("refusing to bind without an expected origin sha")
    ledger = CoordinationLedger(ledger_path) if ledger_path is not None else None
    # 2026-10-07 roadmap: non-pilot lanes (incident-fanin) are allowed ONLY when named on the
    # command line; the five pilot lanes stay allowed. Nothing widens the forbidden-route list.
    allow = frozenset(PILOT_LANES) | frozenset(extra_lanes or ())
    # 2026-10-08: the run allowlist is read once at serve time; a change needs a restart (promote restarts the unit).
    run_allow = load_run_allowlist(run_allowlist_path)
    # 2026-10-09 (B5.3): due inputs are re-read per call; the allowlist is narrowed to run_allow in the gateway.
    due = file_sources(registry_path or DEFAULT_REGISTRY_PATH, run_allowlist_path or DEFAULT_RUN_ALLOWLIST,
                       retry_policies_path or DEFAULT_RETRY_POLICIES)
    httpd = GatewayServer((host, port), make_handler(key, expected_origin_sha, previous_key, ledger=ledger, ledger_path=ledger_path,
                                                     lane_allowlist=allow, n8n_key=n8n_key, run_allowlist=run_allow,
                                                     n8n_previous_key=n8n_previous_key, due_sources=due))
    httpd.coordination_ledger = ledger  # type: ignore[attr-defined]
    httpd.run_allowlist = run_allow  # type: ignore[attr-defined]
    return httpd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loopback coordination gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--ledger", default=None, help="SQLite coordination ledger (default: persistent-state governance dir)")
    parser.add_argument("--no-ledger", action="store_true", help="memory-only store; receipts are never durable")
    parser.add_argument("--allow-lane", action="append", default=[],
                        help="additional lane_id accepted besides the five pilots (e.g. incident-fanin); repeatable")
    parser.add_argument("--run-allowlist", default=str(DEFAULT_RUN_ALLOWLIST),
                        help="N8nRunAllowlist@v1 naming the lanes the run operation may request (read at start)")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH),
                        help="lane registry read by the due operation (re-read per call)")
    parser.add_argument("--retry-policies", default=str(DEFAULT_RETRY_POLICIES),
                        help="N8nRetryPolicies@v1 read by the due operation (re-read per call)")
    args = parser.parse_args(argv)
    try:
        key = load_key()
        previous = load_previous_key()
        n8n_key = load_n8n_key()
        n8n_previous = load_n8n_previous_key()
        ledger_path = None if args.no_ledger else (Path(args.ledger) if args.ledger else default_ledger_path())
        httpd = serve(args.host, args.port, key=key, expected_origin_sha=args.expected_sha, previous_key=previous,
                      ledger_path=ledger_path, extra_lanes=frozenset(args.allow_lane), n8n_key=n8n_key,
                      n8n_previous_key=n8n_previous, run_allowlist_path=Path(args.run_allowlist),
                      registry_path=Path(args.registry), retry_policies_path=Path(args.retry_policies))
        print(json.dumps({"bound": f"{args.host}:{httpd.server_address[1]}", "durable": ledger_path is not None,
                          "ledger": str(ledger_path) if ledger_path else None,
                          "run_scope": n8n_key is not None and ledger_path is not None,
                          "n8n_key_previous": n8n_previous is not None,
                          "run_lanes": sorted(httpd.run_allowlist)}), flush=True)  # type: ignore[attr-defined]
    except BindRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        httpd.server_close()
        if getattr(httpd, "coordination_ledger", None) is not None:
            httpd.coordination_ledger.close()  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

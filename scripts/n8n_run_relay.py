#!/usr/bin/env python3
"""Bearer-authenticated n8n run relay; never spawns and never holds provider credentials."""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from scripts.lib.n8n_coordination_gateway import RUN_ID_RE, SCOPE_RUN, RELAY_CALLER, sign_claim
from scripts.n8n_coordination_gateway import BLOCKED_PORTS, DEFAULT_RUN_ALLOWLIST, load_run_allowlist

NO_CONSUMER_REASON = (
    "Entrypoint of config/systemd/user/tradeai-n8n-run-relay.service; installed by the operator only "
    "(AGENTS.md §23.3). Nothing imports this module."
)

BEARER_ENV = "TRADEAI_N8N_RELAY_BEARER"
N8N_KEY_ENV = "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N"
LIVE_LANES_ENV = "TRADEAI_N8N_RELAY_LIVE_LANES"
DEFAULT_GATEWAY = "http://127.0.0.1:18091"
MAX_BODY = 1024
MIN_KEY_BYTES = 32
REFUSALS = frozenset(
    {
        "relay_bad_path",
        "relay_bad_bearer",
        "relay_body_too_large",
        "relay_malformed_body",
        "relay_lane_not_allowlisted",
        "relay_bad_mode",
        "relay_live_not_enabled",
        "relay_bad_run_id",
        "relay_gateway_unreachable",
        "relay_missing_secret",
        "relay_bad_bind",
    }
)


def guard_bind(host: str, port: int) -> None:
    if port < 1024 or port in BLOCKED_PORTS:
        raise ValueError("relay_bad_bind")
    if host == "127.0.0.1":
        return
    try:
        addr = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("relay_bad_bind") from exc
    if not (
        addr.version == 4
        and str(addr).startswith(("172.16.", "172.17.", "172.18.", "172.19.", "172.2", "172.30.", "172.31."))
    ):
        raise ValueError("relay_bad_bind")
    octets = str(addr).split(".")
    if not 16 <= int(octets[1]) <= 31 or int(octets[3]) != 1:
        raise ValueError("relay_bad_bind")


def _secret(environ: dict[str, str], name: str) -> bytes:
    value = environ.get(name, "").encode()
    if len(value) < MIN_KEY_BYTES:
        raise ValueError("relay_missing_secret")
    return value


def _safe_run_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value if RUN_ID_RE.fullmatch(value) else None


def _derived_run_id(workflow_id: Any, execution_id: Any) -> str | None:
    if not isinstance(workflow_id, str) or not isinstance(execution_id, str):
        return None
    raw = f"n8n-wf-{workflow_id}-{execution_id}"
    value = re.sub(r"[^A-Za-z0-9._:-]", "", raw)
    return value if RUN_ID_RE.fullmatch(value) else None


def _requested_by(workflow_id: Any) -> str:
    if not isinstance(workflow_id, str) or not workflow_id:
        return "n8n:relay"
    value = re.sub(r"[^A-Za-z0-9._:-]", "", workflow_id)
    return (f"n8n:workflow:{value}"[:128]) or "n8n:relay"


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Relay:
    def __init__(
        self,
        *,
        environ: dict[str, str] | None = None,
        allowlist: frozenset[str] | None = None,
        transport: Callable[[str, dict[str, Any]], tuple[int, dict[str, Any]]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.environ = dict(environ or os.environ)
        self.bearer = _secret(self.environ, BEARER_ENV)
        self.key = _secret(self.environ, N8N_KEY_ENV)
        self.allowlist = allowlist if allowlist is not None else load_run_allowlist(DEFAULT_RUN_ALLOWLIST)
        self.live_lanes = frozenset(x for x in self.environ.get(LIVE_LANES_ENV, "").split() if x)
        self.gateway_url = self.environ.get("TRADEAI_N8N_GATEWAY_URL", DEFAULT_GATEWAY).rstrip("/")
        self.clock = clock
        self.transport = transport or self._transport
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.counts = {"requested": 0, "refused": 0, "auth_failures": 0, "gateway_unreachable": 0}
        self.last: dict[str, Any] | None = None
        root = Path(self.environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))
        self.log_dir = root / "data" / "runtime" / "n8n_relay"
        self.log_path = self.log_dir / "relay_log.jsonl"
        self.last_path = self.log_dir / "n8n_run_relay_last.json"
        self._lock = threading.Lock()

    def _transport(self, url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload, separators=(",", ":")).encode()
        request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode())

    def _log(self, row: dict[str, Any]) -> None:
        with self._lock:
            self.last = row
            try:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                tmp = self.last_path.with_suffix(".tmp")
                tmp.write_text(json.dumps({"last": row, "counts": self.counts}, separators=(",", ":")) + "\n")
                os.replace(tmp, self.last_path)
            except OSError:
                pass

    def _refuse(self, reason: str, status: int, **extra: Any) -> tuple[int, dict[str, Any]]:
        assert reason in REFUSALS
        self.counts["refused"] += 1
        row = {"at": datetime.now(timezone.utc).isoformat(), "state": "REFUSED", "reason": reason, **extra}
        self._log(row)
        return status, {"state": "REFUSED", "reason": reason}

    def _auth(self, authorization: str | None) -> bool:
        prefix = "Bearer "
        return bool(
            authorization
            and authorization.startswith(prefix)
            and hmac.compare_digest(authorization[len(prefix) :].encode(), self.bearer)
        )

    def status(self, authorization: str | None) -> tuple[int, dict[str, Any]]:
        if not self._auth(authorization):
            self.counts["auth_failures"] += 1
            return self._refuse("relay_bad_bearer", 401)
        return 200, {
            "schema": "N8nRunRelayStatus@v1",
            "ok": True,
            "authority": "READ_ONLY_ADVISORY",
            "started_at": self.started_at,
            "allowlisted_lanes": len(self.allowlist),
            "live_lanes": sorted(self.live_lanes),
            "gateway_url": self.gateway_url,
            "counts": dict(self.counts),
            "last": self.last,
        }

    def run(self, authorization: str | None, body: bytes) -> tuple[int, dict[str, Any]]:
        if not self._auth(authorization):
            self.counts["auth_failures"] += 1
            return self._refuse("relay_bad_bearer", 401)
        if len(body) > MAX_BODY:
            return self._refuse("relay_body_too_large", 413)
        try:
            data = json.loads(body.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._refuse("relay_malformed_body", 400)
        if not isinstance(data, dict):
            return self._refuse("relay_malformed_body", 400)
        lane = data.get("lane_id")
        mode = data.get("mode")
        if lane not in self.allowlist:
            return self._refuse("relay_lane_not_allowlisted", 403, lane_id=lane)
        if mode not in {"dry_run", "live"}:
            return self._refuse("relay_bad_mode", 403, lane_id=lane)
        if mode == "live" and lane not in self.live_lanes:
            return self._refuse("relay_live_not_enabled", 403, lane_id=lane)
        run_id = _safe_run_id(data.get("idempotency_key")) or _derived_run_id(
            data.get("workflow_id"), data.get("execution_id")
        )
        if not run_id:
            return self._refuse("relay_bad_run_id", 403, lane_id=lane)
        now = self.clock()
        claim = {
            "v": 1,
            "caller_id": RELAY_CALLER,
            "project": "trade-ai",
            "iat": now,
            "exp": now + 120,
            "nonce": secrets.token_urlsafe(12),
            "scope": SCOPE_RUN,
        }
        payload = {
            "route": "coordination/run",
            "operation": "run",
            "claim": claim,
            "signature": sign_claim(claim, self.key),
            "lane_id": lane,
            "mode": mode,
            "idempotency_key": run_id,
            "requested_by": _requested_by(data.get("workflow_id")),
        }
        try:
            gateway_status, reply = self.transport(self.gateway_url + "/v1/coordination", payload)
        except (OSError, urllib.error.URLError, TimeoutError):
            self.counts["gateway_unreachable"] += 1
            return self._refuse("relay_gateway_unreachable", 502, lane_id=lane)
        status = 200 if reply.get("state") == "REQUESTED" else 403
        if status == 200:
            self.counts["requested"] += 1
        row = {
            "at": datetime.now(timezone.utc).isoformat(),
            "state": reply.get("state"),
            "reason": reply.get("reason"),
            "lane_id": lane,
            "mode": mode,
            "run_id": run_id,
            "gateway_http_status": gateway_status,
            "requested_by": payload["requested_by"],
        }
        self._log(row)
        reply = dict(reply)
        reply["gateway_http_status"] = gateway_status
        return status, reply


def serve(host: str, port: int, relay: Relay) -> None:
    guard_bind(host, port)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/status":
                _json_response(self, 404, {"state": "REFUSED", "reason": "relay_bad_path"})
                return
            status, payload = relay.status(self.headers.get("Authorization"))
            _json_response(self, status, payload)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/run":
                _json_response(self, 404, {"state": "REFUSED", "reason": "relay_bad_path"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = MAX_BODY + 1
            body = self.rfile.read(min(max(length, 0), MAX_BODY + 1))
            status, payload = relay.run(
                self.headers.get("Authorization"), body if length <= MAX_BODY + 1 else b"x" * (MAX_BODY + 1)
            )
            _json_response(self, status, payload)

        def do_PUT(self) -> None:  # noqa: N802
            _json_response(self, 405, {"state": "REFUSED", "reason": "relay_bad_path"})

        do_DELETE = do_PUT
        do_PATCH = do_PUT

    server = ThreadingHTTPServer((host, port), Handler)
    print(json.dumps({"ok": True, "host": host, "port": port, "authority": "READ_ONLY_ADVISORY"}), flush=True)
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18092)
    parser.add_argument("--run-allowlist", type=Path, default=DEFAULT_RUN_ALLOWLIST)
    args = parser.parse_args()
    try:
        guard_bind(args.host, args.port)
        relay = Relay(allowlist=load_run_allowlist(args.run_allowlist))
        serve(args.host, args.port, relay)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

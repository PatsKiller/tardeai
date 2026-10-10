#!/usr/bin/env python3
"""Bearer-authenticated n8n run relay; never spawns and never holds provider credentials.

2026-10-09 (n8n maturity B5.3, design 02 §3.1/§4): GET /due?source=&lane=&limit= signs a coordination_read
claim and forwards to the gateway's read-only `coordination/due`; every forwarded call appends one
{"op": "due"} line to relay_log.jsonl, the dispatcher's liveness signal. GET /runs/<lane>/last?mode=dry_run|live
filters the last run by mode (no query keeps the old any-mode answer).

During rotation the relay accepts TRADEAI_N8N_RELAY_BEARER or TRADEAI_N8N_RELAY_BEARER_PREVIOUS.
A missing previous bearer is the pre-rotation state. A short one refuses to start.

2026-10-10 (W0 relay fix, design 02 §8/§11): POST /event takes the incident router's shaped Error Trigger body
{lane_id, workflow_id, execution_id, node, message}, accepts only lane `n8n-workflow-error`, and forwards one
read-scope `accept_event` to the gateway (the gateway's coordination ledger is the only store written; nothing is
sent and nothing is run). W0 published the six generic workflows against a relay without this route and every
error event came back 404 relay_bad_path. ROUTES is the route table the handler serves; `--routes` prints it so a
pre-import dry run can check every workflow HTTP node against the relay it will call.
"""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

# Support direct execution from outside the repository, as systemd does.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_coordination_gateway import (  # noqa: E402
    RELAY_CALLER,
    RUN_ID_RE,
    SCHEMA_VERSION as EVENT_SCHEMA_VERSION,
    SCOPE_READ,
    SCOPE_RUN,
    sign_claim,
)
from scripts.lib.n8n_coordination_projection import ledger_path, project_runs
from scripts.lib.n8n_due import DEFAULT_LIMIT as DUE_DEFAULT_LIMIT  # noqa: E402  (config/n8n_due.json)
from scripts.lib.n8n_due import MAX_LANE_FILTER as DUE_MAX_LANES  # noqa: E402
from scripts.lib.n8n_due import MAX_LIMIT as DUE_MAX_LIMIT  # noqa: E402
from scripts.lib.n8n_due import SOURCES as DUE_SOURCES  # noqa: E402
from scripts.n8n_coordination_gateway import BLOCKED_PORTS, DEFAULT_RUN_ALLOWLIST, load_run_allowlist

NO_CONSUMER_REASON = (
    "Entrypoint of config/systemd/user/tradeai-n8n-run-relay.service; installed by the operator only "
    "(AGENTS.md §23.3). Nothing imports this module."
)

BEARER_ENV = "TRADEAI_N8N_RELAY_BEARER"
BEARER_PREVIOUS_ENV = "TRADEAI_N8N_RELAY_BEARER_PREVIOUS"
N8N_KEY_ENV = "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N"
LIVE_LANES_ENV = "TRADEAI_N8N_RELAY_LIVE_LANES"
DEFAULT_GATEWAY = "http://127.0.0.1:18091"
#: limit is at most 3 ASCII digits before int(): no Unicode digits ("²", "١٢"), no huge-int parsing.
DUE_LIMIT_DIGITS = len(str(DUE_MAX_LIMIT))
DUE_QUERY_KEYS = frozenset({"source", "lane", "limit"})
RUN_MODES = frozenset({"dry_run", "live"})
MAX_BODY = 1024
MIN_KEY_BYTES = 32
LAST_SCHEMA = "N8nRunRelayLast@v1"
_LANE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_LAST_FIELDS = ("run_id", "lane_id", "state", "finished_at", "requested_at", "mode")
# Dropped first when the body would exceed MAX_BODY. state and finished_at stay until nothing else will.
_LAST_OPTIONAL = ("requested_at", "mode", "run_id", "finished_at", "lane_id")
#: The routes the handler serves, (method, path). `<lane_id>` is the one path parameter (parse_last_path).
ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/status"),
    ("GET", "/due"),
    ("GET", "/runs/<lane_id>/last"),
    ("POST", "/run"),
    ("POST", "/event"),
)
ROUTES_SCHEMA = "N8nRunRelayRoutes@v1"
#: POST /event (design 02 §8): the only lane, the exact body keys, and the bounds.
EVENT_LANE = "n8n-workflow-error"
EVENT_BODY_KEYS = frozenset({"lane_id", "workflow_id", "execution_id", "node", "message"})
EVENT_MESSAGE_MAX = 160
EVENT_NODE_MAX = 64
EVENT_DEADLINE_S = 24 * 3600
#: Retries of one execution's error replay the first event byte for byte (gateway payload-hash idempotency).
EVENT_CACHE_MAX = 512
_WORKFLOW_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_EXECUTION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_REDACT_RES = (
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"(?i)postgres(?:ql)?://\S+"),
    re.compile(r"(?<![A-Za-z])sk-[A-Za-z0-9_-]+"),
    re.compile(r"[A-Za-z0-9+/=_-]{32,}"),
)
REFUSALS = frozenset(
    {
        "relay_bad_path",
        "relay_bad_event",
        "relay_event_lane_refused",
        "relay_no_origin_sha",
        "relay_bad_bearer",
        "relay_body_too_large",
        "relay_malformed_body",
        "relay_lane_not_allowlisted",
        "relay_bad_mode",
        "relay_live_not_enabled",
        "relay_bad_run_id",
        "relay_gateway_unreachable",
        "relay_gateway_http_error",
        "relay_missing_secret",
        "relay_bad_bind",
        "relay_bad_query",
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


def _optional_secret(environ: dict[str, str], name: str) -> bytes | None:
    """Empty is absent. A present value shorter than MIN_KEY_BYTES refuses startup."""
    raw = environ.get(name, "")
    if raw == "":
        return None
    value = raw.encode()
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


def parse_last_path(path: str) -> str | None:
    """Return the lane id for exactly /runs/<lane_id>/last, else None.

    lane_id is letters, digits, and . _ - only. Extra segments, a query, or any other character
    are not a last-run route (the caller answers relay_bad_path).
    """
    parts = path.split("/")
    if len(parts) != 4 or parts[0] != "" or parts[1] != "runs" or parts[3] != "last":
        return None
    lane_id = parts[2]
    if not _LANE_ID_RE.fullmatch(lane_id):
        return None
    return lane_id


def _encoded(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


def _compact_last(lane_id: str, proj: dict[str, Any]) -> dict[str, Any] | None:
    """Small stable last-run body, or None when it cannot be made to fit MAX_BODY."""
    items = proj.get("items") or []
    item = items[0] if items else None
    last: dict[str, Any] | None
    if isinstance(item, dict):
        last = {key: item.get(key) for key in _LAST_FIELDS}
    else:
        last = None
    payload: dict[str, Any] = {
        "schema": LAST_SCHEMA,
        "lane_id": lane_id,
        "status": proj.get("status"),
        "last": last,
    }
    if len(_encoded(payload)) <= MAX_BODY:
        return payload
    if isinstance(payload["last"], dict):
        for key in _LAST_OPTIONAL:
            payload["last"].pop(key, None)
            if len(_encoded(payload)) <= MAX_BODY:
                return payload
        if not payload["last"]:
            payload["last"] = None
            if len(_encoded(payload)) <= MAX_BODY:
                return payload
    return None


def _requested_by(workflow_id: Any) -> str:
    if not isinstance(workflow_id, str) or not workflow_id:
        return "n8n:relay"
    value = re.sub(r"[^A-Za-z0-9._:-]", "", workflow_id)
    return (f"n8n:workflow:{value}"[:128]) or "n8n:relay"


def _clean_text(value: str, limit: int) -> str:
    """Control characters folded to one space, secret-shaped runs redacted, then cut to ``limit``."""
    text = _CONTROL_RE.sub(" ", value)
    for pattern in _REDACT_RES:
        text = pattern.sub("[redacted]", text)
    return text.strip()[:limit]


def _origin_sha(environ: dict[str, str]) -> str | None:
    """The release's own GIT_SHA (the gateway refuses any other as stale_origin_sha); None outside a release."""
    raw = environ.get("TRADEAI_N8N_RELAY_ORIGIN_SHA", "").strip()
    if not raw:
        try:
            raw = (ROOT / "GIT_SHA").read_text(encoding="utf-8").strip()
        except OSError:
            return None
    return raw if re.fullmatch(r"[0-9a-f]{40}", raw) else None


def route_supported(method: str, path: str) -> bool:
    """True when the handler serves ``method path`` (query ignored), from ROUTES."""
    bare = path.partition("?")[0]
    for m, pattern in ROUTES:
        if m != method:
            continue
        if pattern == bare or (pattern == "/runs/<lane_id>/last" and parse_last_path(bare) is not None):
            return True
    return False


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
        self.bearer_previous = _optional_secret(self.environ, BEARER_PREVIOUS_ENV)
        self.key = _secret(self.environ, N8N_KEY_ENV)
        self.allowlist = allowlist if allowlist is not None else load_run_allowlist(DEFAULT_RUN_ALLOWLIST)
        self.live_lanes = frozenset(x for x in self.environ.get(LIVE_LANES_ENV, "").split() if x)
        self.gateway_url = self.environ.get("TRADEAI_N8N_GATEWAY_URL", DEFAULT_GATEWAY).rstrip("/")
        self.clock = clock
        self.transport = transport or self._transport
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.counts = {"requested": 0, "refused": 0, "auth_failures": 0, "gateway_unreachable": 0, "due": 0,
                       "events": 0}
        self.last: dict[str, Any] | None = None
        root = Path(self.environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))
        self.log_dir = root / "data" / "runtime" / "n8n_relay"
        self.log_path = self.log_dir / "relay_log.jsonl"
        self.last_path = self.log_dir / "n8n_run_relay_last.json"
        self._lock = threading.Lock()
        self.origin_sha = _origin_sha(self.environ)
        self._events: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def _transport(self, url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload, separators=(",", ":")).encode()
        request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode())
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = {"state": "REFUSED", "reason": "relay_gateway_http_error"}
            return exc.code, payload

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
        if not authorization or not authorization.startswith(prefix):
            return False
        presented = authorization[len(prefix) :].encode()
        if hmac.compare_digest(presented, self.bearer):
            return True
        previous = self.bearer_previous
        return previous is not None and hmac.compare_digest(presented, previous)

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

    def event(self, authorization: str | None, body: bytes) -> tuple[int, dict[str, Any]]:
        """POST /event (design 02 §8): one n8n workflow error -> one gateway ``accept_event`` on lane
        n8n-workflow-error. Validated and bounded here; idempotent per (workflow_id, execution_id); one
        {"op": "event"} relay_log line per call that reaches the gateway. Writes nothing itself, sends nothing."""
        if not self._auth(authorization):
            self.counts["auth_failures"] += 1
            return self._refuse("relay_bad_bearer", 401, op="event")
        if len(body) > MAX_BODY:
            return self._refuse("relay_body_too_large", 413, op="event")
        try:
            data = json.loads(body.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._refuse("relay_malformed_body", 400, op="event")
        if not isinstance(data, dict) or set(data) != EVENT_BODY_KEYS:
            return self._refuse("relay_bad_event", 400, op="event")
        if data.get("lane_id") != EVENT_LANE:
            lane = data.get("lane_id")
            return self._refuse("relay_event_lane_refused", 403, op="event",
                                lane_id=lane[:64] if isinstance(lane, str) else None)
        workflow_id, execution_id = data.get("workflow_id"), data.get("execution_id")
        node, message = data.get("node"), data.get("message")
        if not (isinstance(workflow_id, str) and _WORKFLOW_ID_RE.fullmatch(workflow_id)
                and isinstance(execution_id, str) and _EXECUTION_ID_RE.fullmatch(execution_id)
                and isinstance(node, str) and isinstance(message, str)):
            return self._refuse("relay_bad_event", 400, op="event")
        if self.origin_sha is None:
            return self._refuse("relay_no_origin_sha", 503, op="event")
        node = _clean_text(node, EVENT_NODE_MAX)
        message = _clean_text(message, EVENT_MESSAGE_MAX)
        idem = f"wferr-{workflow_id}-{execution_id}"[:128]
        with self._lock:
            event = self._events.get(idem)
            if event is None:
                at = datetime.fromtimestamp(self.clock(), timezone.utc)
                event = {
                    "event_id": f"evt-{EVENT_LANE}-{workflow_id}-{execution_id}"[:128],
                    "source_project": "trade-ai",
                    "lane_id": EVENT_LANE,
                    "schema_version": EVENT_SCHEMA_VERSION,
                    "origin_sha": self.origin_sha,
                    "subject_key": f"wf={workflow_id};exec={execution_id};node={node};msg={message}"[:200],
                    "source_timestamp": at.isoformat(),
                    "deadline": (at + timedelta(seconds=EVENT_DEADLINE_S)).isoformat(),
                    "artifact_ref": f"relay_log:data/runtime/n8n_relay/relay_log.jsonl#{idem}",
                    "authority_class": "coordination_read",
                    "correlation_id": f"corr-{idem}",
                    "idempotency_key": idem,
                }
                self._events[idem] = event
                while len(self._events) > EVENT_CACHE_MAX:
                    self._events.popitem(last=False)
        now = self.clock()
        claim = {
            "v": 1,
            "caller_id": RELAY_CALLER,
            "project": "trade-ai",
            "iat": now,
            "exp": now + 120,
            "nonce": secrets.token_urlsafe(12),
            "scope": SCOPE_READ,
        }
        payload = {
            "route": "coordination/event",
            "operation": "accept_event",
            "claim": claim,
            "signature": sign_claim(claim, self.key),
            "event": event,
        }
        self.counts["events"] += 1
        try:
            gateway_status, reply = self.transport(self.gateway_url + "/v1/coordination", payload)
        except (OSError, urllib.error.URLError, TimeoutError):
            self.counts["gateway_unreachable"] += 1
            return self._refuse("relay_gateway_unreachable", 502, op="event", idempotency_key=idem)
        ok = reply.get("state") == "ACCEPTED"
        self._log({
            "at": datetime.now(timezone.utc).isoformat(),
            "op": "event",
            "state": reply.get("state"),
            "reason": None if ok else str(reply.get("reason") or "")[:64],
            "lane_id": EVENT_LANE,
            "workflow_id": workflow_id,
            "execution_id": execution_id,
            "node": node,
            "message": message,
            "idempotency_key": idem,
            "duplicate": bool(reply.get("duplicate")),
            "gateway_http_status": gateway_status,
        })
        reply = dict(reply)
        reply["gateway_http_status"] = gateway_status
        if ok:
            return 200, reply
        return (gateway_status if isinstance(gateway_status, int) and gateway_status >= 400 else 403), reply

    def due(self, authorization: str | None, query: str = "") -> tuple[int, dict[str, Any]]:
        """GET /due passthrough to the gateway's read-only coordination/due (design 02 §3.1). The relay validates
        only the query shape; the gateway owns source / lane_filter / clock checks. One {"op": "due"} log line
        per forwarded call (dispatcher liveness, §4)."""
        if not self._auth(authorization):
            self.counts["auth_failures"] += 1
            return self._refuse("relay_bad_bearer", 401, op="due")
        try:
            params = parse_qs(query, keep_blank_values=True, strict_parsing=bool(query))
        except ValueError:
            return self._refuse("relay_bad_query", 400, op="due")
        if set(params) - DUE_QUERY_KEYS or any(len(params.get(k, [])) > 1 for k in ("source", "limit")):
            return self._refuse("relay_bad_query", 400, op="due")
        source = params.get("source", ["schedule"])[0]
        if source not in DUE_SOURCES:                      # validated before anything logs it
            return self._refuse("relay_bad_query", 400, op="due")
        lane_values = params.get("lane", [])
        if sum(len(v) for v in lane_values) > DUE_MAX_LANES * 65:   # bound before splitting (64-char ids + commas)
            return self._refuse("relay_bad_query", 400, op="due")
        lanes = [x for v in lane_values for x in v.split(",") if x]
        if any(not _LANE_ID_RE.fullmatch(x) for x in lanes) or len(lanes) > DUE_MAX_LANES:
            return self._refuse("relay_bad_query", 400, op="due")
        raw_limit = params.get("limit", [str(DUE_DEFAULT_LIMIT)])[0]
        if not (raw_limit.isascii() and raw_limit.isdigit() and len(raw_limit) <= DUE_LIMIT_DIGITS) \
                or int(raw_limit) < 1:
            return self._refuse("relay_bad_query", 400, op="due")
        limit = min(int(raw_limit), DUE_MAX_LIMIT)
        now = self.clock()
        claim = {
            "v": 1,
            "caller_id": RELAY_CALLER,
            "project": "trade-ai",
            "iat": now,
            "exp": now + 120,
            "nonce": secrets.token_urlsafe(12),
            "scope": SCOPE_READ,
        }
        payload: dict[str, Any] = {
            "route": "coordination/due",
            "operation": "due",
            "claim": claim,
            "signature": sign_claim(claim, self.key),
            "source": source,
            "now": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "limit": limit,
        }
        if lanes:
            payload["lane_filter"] = lanes
        self.counts["due"] += 1
        try:
            gateway_status, reply = self.transport(self.gateway_url + "/v1/coordination", payload)
        except (OSError, urllib.error.URLError, TimeoutError):
            self.counts["gateway_unreachable"] += 1
            return self._refuse("relay_gateway_unreachable", 502, op="due", source=source)
        ok = reply.get("schema") == "DueResponse@v1" and reply.get("ok") is True
        items = reply.get("items") if ok and isinstance(reply.get("items"), list) else []
        self._log({
            "at": datetime.now(timezone.utc).isoformat(),
            "op": "due",
            "state": "OK" if ok else "REFUSED",
            "reason": None if ok else str(reply.get("reason") or "")[:64],
            "source": source,
            "limit": limit,
            "items": len(items),
            "truncated": reply.get("truncated", 0) if ok else 0,
            "gateway_http_status": gateway_status,
        })
        if ok:
            return 200, reply
        return (gateway_status if isinstance(gateway_status, int) and gateway_status >= 400 else 403), reply

    def last_run(self, authorization: str | None, lane_id: str, query: str = "") -> tuple[int, dict[str, Any]]:
        """Read-only newest runs row for one lane. Never calls the gateway and never runs a command.

        2026-10-09 (B5.3): ``?mode=dry_run|live`` filters by mode (design 02 §3.2 step 4: a dry_run row must not
        answer a live question). No query keeps the old any-mode answer; any other query is 400."""
        if not self._auth(authorization):
            self.counts["auth_failures"] += 1
            return self._refuse("relay_bad_bearer", 401)
        mode = None
        if query:
            try:
                params = parse_qs(query, keep_blank_values=True, strict_parsing=True)
            except ValueError:
                return self._refuse("relay_bad_query", 400, lane_id=lane_id)
            if set(params) - {"mode"}:
                return self._refuse("relay_bad_query", 400, lane_id=lane_id)
            values = params.get("mode", [])
            if len(values) != 1 or values[0] not in RUN_MODES:
                return self._refuse("relay_bad_mode", 400, lane_id=lane_id)
            mode = values[0]
        proj = project_runs(ledger_path(self.environ), lane_id=lane_id, limit=1, mode=mode)
        payload = _compact_last(lane_id, proj)
        if payload is None:
            return self._refuse("relay_body_too_large", 413, lane_id=lane_id)
        return 200, payload


class RelayServer(ThreadingHTTPServer):
    """2026-10-08: listen backlog 64 (stock 5) so a :00 burst of n8n workflows does not wait on the kernel's
    1 s SYN retransmit; same change as the gateway's GatewayServer, which this relay sits in front of."""

    request_queue_size = 64


def handler_for(relay: Relay) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            path, _, query = self.path.partition("?")
            lane_id = parse_last_path(path)
            if self.path == "/status":
                status, payload = relay.status(self.headers.get("Authorization"))
            elif path == "/due":
                status, payload = relay.due(self.headers.get("Authorization"), query)
            elif lane_id is not None:
                status, payload = relay.last_run(self.headers.get("Authorization"), lane_id, query)
            else:
                _json_response(self, 404, {"state": "REFUSED", "reason": "relay_bad_path"})
                return
            _json_response(self, status, payload)

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/run":
                op = relay.run
            elif self.path == "/event":
                op = relay.event
            else:
                _json_response(self, 404, {"state": "REFUSED", "reason": "relay_bad_path"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = MAX_BODY + 1
            body = self.rfile.read(min(max(length, 0), MAX_BODY + 1))
            status, payload = op(
                self.headers.get("Authorization"), body if length <= MAX_BODY + 1 else b"x" * (MAX_BODY + 1)
            )
            _json_response(self, status, payload)

        def do_PUT(self) -> None:  # noqa: N802
            _json_response(self, 405, {"state": "REFUSED", "reason": "relay_bad_path"})

        do_DELETE = do_PUT
        do_PATCH = do_PUT

    return Handler


def serve(host: str, port: int, relay: Relay) -> None:
    guard_bind(host, port)
    server = RelayServer((host, port), handler_for(relay))
    print(json.dumps({"ok": True, "host": host, "port": port, "authority": "READ_ONLY_ADVISORY"}), flush=True)
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18092)
    parser.add_argument("--run-allowlist", type=Path, default=DEFAULT_RUN_ALLOWLIST)
    parser.add_argument("--routes", action="store_true", help="print the served route table as JSON and exit")
    args = parser.parse_args()
    if args.routes:
        print(json.dumps({"schema": ROUTES_SCHEMA, "routes": [{"method": m, "path": p} for m, p in ROUTES]}))
        return 0
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

"""GET-only reads for the first n8n Agent (explain why a lane failed).

The relay is the only door the container may call. These three paths are the
whole read surface:

    GET /runs/<lane>/last
    GET /runs/<lane>/recent?n=<1..10>
    GET /lanes/<lane>

A call needs an HMAC claim with scope coordination_read. Every other path and
every write verb on this surface is a typed refusal. Nothing here spawns, sends,
or imports a workflow.

The shadow workflow generator is scripts/n8n_lane_failure_explainer_workflow.
That module name is the consumer link for the generator.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from scripts.lib.n8n_coordination_gateway import (
    FORBIDDEN_ROUTE_TOKENS,
    SCOPE_READ,
    GatewayError,
    _refused,
    _verify_claim,
)
from scripts.lib.n8n_coordination_projection import project_runs

CLAIM_HEADER = "X-TradeAI-Claim"
SIGNATURE_HEADER = "X-TradeAI-Signature"
LAST_SCHEMA = "N8nRunRelayLast@v1"
RECENT_SCHEMA = "N8nAgentRunRecent@v1"
LANE_SCHEMA = "N8nAgentLaneRead@v1"
EXPLAINER_WORKFLOW_GENERATOR = "n8n_lane_failure_explainer_workflow"
STDERR_TAIL_MAX_BYTES = 2048
RECENT_MAX_N = 10
RECENT_DEFAULT_N = 10
LAST_FIELDS = ("run_id", "lane_id", "state", "finished_at", "requested_at", "mode")
RECEIPT_FIELDS = ("state", "exit_code", "duration_s", "stderr_tail", "output_signal_age_s")
DEFAULT_REGISTRY = Path(__file__).resolve().parents[2] / "config" / "lane_registry.json"
_LANE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_N_RE = re.compile(r"[1-9][0-9]*$")
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ReadTarget:
    kind: str
    lane_id: str
    n: int | None = None


def forbidden_token(text: str) -> str | None:
    """A gateway forbidden-route token in text, or None.

    Same split-and-substring test as route_forbidden, without the coordination
    route allowlist. Static path segments (runs, last, recent, lanes) match none.
    """
    lowered = (text or "").lower()
    tokens = [tok for tok in _TOKEN_SPLIT.split(lowered) if tok]
    collapsed = lowered.replace("-", "").replace("/", "").replace("?", "").replace("=", "").replace("&", "")
    for token in tokens:
        if token in FORBIDDEN_ROUTE_TOKENS:
            return token
    for token in FORBIDDEN_ROUTE_TOKENS:
        if token in collapsed and token not in {"title"}:
            return token
    return None


def _is_read_surface(path: str) -> bool:
    return path == "/runs" or path.startswith("/runs/") or path == "/lanes" or path.startswith("/lanes/")


def _parse_n(query: str) -> tuple[int | None, str | None]:
    if query == "":
        return RECENT_DEFAULT_N, None
    if not query.startswith("n=") or query.count("=") != 1 or "&" in query:
        return None, "read_path_refused"
    raw = query[2:]
    if not _N_RE.fullmatch(raw):
        return None, "read_bad_n"
    n = int(raw)
    if n > RECENT_MAX_N:
        return None, "read_bad_n"
    return n, None


def _parse_get(path: str, query: str) -> ReadTarget | str:
    parts = path.split("/")
    if len(parts) == 3 and parts[0] == "" and parts[1] == "lanes":
        if query or not _LANE_RE.fullmatch(parts[2] or ""):
            return "read_path_refused"
        return ReadTarget("lane", parts[2], None)
    if len(parts) == 4 and parts[0] == "" and parts[1] == "runs" and parts[3] in {"last", "recent"}:
        if not _LANE_RE.fullmatch(parts[2] or ""):
            return "read_path_refused"
        if parts[3] == "last":
            if query:
                return "read_path_refused"
            return ReadTarget("last", parts[2], None)
        n, err = _parse_n(query)
        if err:
            return err
        return ReadTarget("recent", parts[2], n)
    return "read_path_refused"


def classify_read(target: str, *, method: str) -> tuple[str, ReadTarget | None, str | None]:
    """Classify one request against the three read paths.

    Returns (decision, target, token). decision is not_read_surface,
    read_method_refused, read_path_refused, read_bad_n, forbidden_route, or ok.
    """
    if not isinstance(target, str) or not isinstance(method, str):
        return "not_read_surface", None, None
    path, _, query = target.partition("?")
    dirty = any(ch in target for ch in ("\x00", "\\", "#", " ")) or ".." in path
    if not _is_read_surface(path):
        return "not_read_surface", None, None
    if method.upper() != "GET":
        return "read_method_refused", None, None
    if dirty:
        return "read_path_refused", None, None
    token = forbidden_token(path) or (forbidden_token(query) if query else None)
    if token:
        return "forbidden_route", None, token
    parsed = _parse_get(path, query)
    if isinstance(parsed, str):
        return parsed, None, None
    return "ok", parsed, None


def _refusal(reason: str) -> tuple[int, dict[str, Any]]:
    if reason == "read_method_refused":
        status = 405
    elif reason in {"read_path_refused", "unknown_lane"}:
        status = 404
    elif reason == "read_bad_n":
        status = 400
    else:
        status = 403
    body = _refused(None, reason, peer_ignored=None)
    body["proxy_headers_used_as_auth"] = False
    return status, body


def _clip_tail(value: Any) -> str | None:
    if not isinstance(value, str) or value == "":
        return None
    raw = value.encode("utf-8")
    if len(raw) <= STDERR_TAIL_MAX_BYTES:
        return value
    return raw[:STDERR_TAIL_MAX_BYTES].decode("utf-8", errors="ignore")


def _age_s(mtime: Any, now: datetime) -> float | None:
    if isinstance(mtime, bool) or not isinstance(mtime, (int, float)):
        return None
    return round(now.timestamp() - float(mtime), 3)


def _receipt_fields(row: sqlite3.Row, now: datetime) -> dict[str, Any]:
    receipt: dict[str, Any] = {}
    raw = row["receipt_json"]
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            receipt = parsed
    state = receipt.get("state") if receipt.get("state") is not None else row["state"]
    exit_code = receipt.get("exit_code") if "exit_code" in receipt else row["exit_code"]
    duration = receipt.get("duration_s") if "duration_s" in receipt else row["duration_s"]
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        exit_code = row["exit_code"] if isinstance(row["exit_code"], int) else None
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        row_duration = row["duration_s"]
        duration = (
            row_duration if isinstance(row_duration, (int, float)) and not isinstance(row_duration, bool) else None
        )
    return {
        "state": state,
        "exit_code": exit_code,
        "duration_s": duration,
        "stderr_tail": _clip_tail(receipt.get("stderr_tail")),
        "output_signal_age_s": _age_s(receipt.get("output_signal_mtime_after"), now),
    }


def recent_payload(ledger_path: Path | None, lane_id: str, n: int, now: datetime) -> dict[str, Any]:
    status = "NO_LEDGER"
    items: list[dict[str, Any]] = []
    if ledger_path is not None and Path(ledger_path).is_file():
        try:
            conn = sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True, timeout=2)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error:
            status = "UNREADABLE"
        else:
            try:
                has = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone()
                if not has:
                    status = "OK"
                else:
                    rows = conn.execute(
                        "SELECT state, exit_code, duration_s, receipt_json "
                        "FROM runs WHERE lane_id = ? "
                        "ORDER BY COALESCE(finished_at, started_at, requested_at) DESC LIMIT ?",
                        (lane_id, n),
                    ).fetchall()
                    items = [_receipt_fields(row, now) for row in rows]
                    status = "OK"
            except sqlite3.Error:
                status = "UNREADABLE"
            finally:
                conn.close()
    return {
        "schema": RECENT_SCHEMA,
        "lane_id": lane_id,
        "n": n,
        "status": status,
        "items": items,
        "authority": "READ_ONLY_ADVISORY",
    }


def last_payload(ledger_path: Path | None, lane_id: str) -> dict[str, Any]:
    """Same projection the relay's existing /runs/<lane>/last already serves."""
    if ledger_path is None:
        proj: dict[str, Any] = {"status": "NO_LEDGER", "items": []}
    else:
        proj = project_runs(Path(ledger_path), lane_id=lane_id, limit=1)
    items = proj.get("items") or []
    item = items[0] if items else None
    last = {key: item.get(key) for key in LAST_FIELDS} if isinstance(item, dict) else None
    return {
        "schema": LAST_SCHEMA,
        "lane_id": lane_id,
        "status": proj.get("status"),
        "last": last,
        "authority": "READ_ONLY_ADVISORY",
    }


def _cadence(row: Mapping[str, Any]) -> Any:
    sched = row.get("scheduler") if isinstance(row.get("scheduler"), dict) else {}
    named = sched.get("cadence")
    if isinstance(named, str) and named:
        return named
    return row.get("expected_cadence_hours")


def lane_payload(registry_path: Path, lane_id: str) -> tuple[int, dict[str, Any]]:
    if not registry_path.is_file():
        return _refusal("read_registry_unreadable")
    try:
        doc = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _refusal("read_registry_unreadable")
    lanes = doc.get("lanes") if isinstance(doc, dict) else None
    if not isinstance(lanes, list):
        return _refusal("read_registry_unreadable")
    row = next((item for item in lanes if isinstance(item, dict) and item.get("lane_id") == lane_id), None)
    if row is None:
        return _refusal("unknown_lane")
    sched = row.get("scheduler") if isinstance(row.get("scheduler"), dict) else {}
    signal = row.get("output_signal") if isinstance(row.get("output_signal"), dict) else None
    return 200, {
        "schema": LANE_SCHEMA,
        "lane_id": lane_id,
        "owner": row.get("owner"),
        "cadence": _cadence(row),
        "output_signal": signal,
        "scheduler_kind": sched.get("kind"),
        "authority": "READ_ONLY_ADVISORY",
    }


def _authenticate(
    headers: Mapping[str, Any] | None,
    *,
    key: bytes,
    now: datetime,
    nonce_store: Any,
    previous_key: bytes | None,
    caller_keys: Mapping[str, Any] | None,
) -> dict[str, Any]:
    raw = headers.get(CLAIM_HEADER) if isinstance(headers, Mapping) else None
    signature = headers.get(SIGNATURE_HEADER) if isinstance(headers, Mapping) else None
    if not isinstance(raw, str) or not raw or not isinstance(signature, str) or not signature:
        raise GatewayError("missing_signature")
    try:
        claim = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GatewayError("malformed_claim") from exc
    verified = _verify_claim(
        {"claim": claim, "signature": signature},
        key=key,
        now=now,
        nonce_store=nonce_store,
        previous_key=previous_key,
        caller_keys=caller_keys,
    )
    if verified.get("scope") != SCOPE_READ:
        raise GatewayError("bad_scope")
    return verified


def dispatch_agent_read(
    method: str,
    target: str,
    headers: Mapping[str, Any] | None,
    *,
    key: bytes,
    now: datetime,
    nonce_store: Any,
    previous_key: bytes | None = None,
    caller_keys: Mapping[str, Any] | None = None,
    ledger_path: Path | None = None,
    registry_path: Path | None = None,
) -> tuple[int, dict[str, Any]] | None:
    """Serve one agent read, or None when the path is not this surface.

    Proxy headers are not read. The HMAC claim is the only identity.
    """
    decision, parsed, token = classify_read(target, method=method)
    if decision == "not_read_surface":
        return None
    try:
        now = aware(now)
    except GatewayError as exc:
        return _refusal(exc.reason)
    if decision == "forbidden_route":
        return _refusal(f"forbidden_route:{token}")
    if decision != "ok" or parsed is None:
        return _refusal(decision)
    try:
        _authenticate(
            headers,
            key=key,
            now=now,
            nonce_store=nonce_store,
            previous_key=previous_key,
            caller_keys=caller_keys,
        )
    except GatewayError as exc:
        return _refusal(exc.reason)
    if parsed.kind == "last":
        body = last_payload(ledger_path, parsed.lane_id)
    elif parsed.kind == "recent":
        body = recent_payload(ledger_path, parsed.lane_id, int(parsed.n or RECENT_DEFAULT_N), now)
    else:
        return lane_payload(registry_path or DEFAULT_REGISTRY, parsed.lane_id)
    body["proxy_headers_used_as_auth"] = False
    return 200, body


def aware(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise GatewayError("naive_clock")
    return now

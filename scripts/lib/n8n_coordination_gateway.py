"""Trade AI coordination gateway for an n8n caller.

Authenticates a short-lived HMAC claim. Localhost is not a credential.
Accepts an event reference and refuses broker, grant, 2FA, promote, and bid
routes. The in-process store is not a durable production ledger and this
module does not bind a socket, send a message, or open a database.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "event-reference/v0"
RECEIPT_SCHEMA = "N8nCoordinationReceipt@v1"
ALLOWED_PROJECTS = frozenset({"trade-ai", "nyc-dof-auction"})
PILOT_LANES = frozenset(
    {
        "morning-brief-0730",
        "research-scheduler-holdings",
        "material-change-digest",
        "llm-spend-report-daily",
        "approval-package-reminder",
    }
)
EVENT_FIELDS = frozenset(
    {
        "event_id",
        "source_project",
        "lane_id",
        "schema_version",
        "origin_sha",
        "subject_key",
        "source_timestamp",
        "deadline",
        "artifact_ref",
        "authority_class",
        "correlation_id",
        "idempotency_key",
    }
)
CLAIM_FIELDS = frozenset({"v", "caller_id", "project", "iat", "exp", "nonce", "scope"})
FORBIDDEN_ROUTE_TOKENS = frozenset(
    {
        "broker",
        "order",
        "orders",
        "size",
        "approve",
        "grant",
        "2fa",
        "twofactor",
        "two_factor",
        "totp",
        "liveflag",
        "live_flag",
        "promote",
        "rollback",
        "bid",
        "payment",
        "title",
        "titlestatus",
        "title_status",
        "brokertruth",
        "broker_truth",
        "financial",
        "financial_authority",
        "protect",
        "telegram",
        "email",
        "send",
        "sql",
        "postgres",
    }
)
SECRET_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "dsn",
        "private_key",
        "totp",
        "seed",
        "webhook_secret",
    }
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SECRET_VALUE_RE = re.compile(r"(postgres(?:ql)?://|(?<![A-Za-z])sk-|bearer\s)", re.I)
MAX_CLAIM_LIFE_S = 300
MAX_SKEW_S = 5
TERMINAL = frozenset(
    {
        "CONSUMED",
        "REFUSED",
        "FAILED",
        "DEAD_LETTER",
        "SUPPRESSED",
        "SUPERSEDED",
        "CANCELLED",
        "EXPIRED",
    }
)
EDGES = {
    "EXPECTED": {"ACCEPTED", "REFUSED", "CANCELLED", "SUPPRESSED"},
    "ACCEPTED": {"CLAIMED", "REFUSED", "EXPIRED", "CANCELLED"},
    "CLAIMED": {"STARTED", "REFUSED", "CANCELLED"},
    "STARTED": {"ARTIFACT_WRITTEN", "FAILED", "REFUSED"},
    "ARTIFACT_WRITTEN": {"CONSUMED", "FAILED", "DEAD_LETTER", "SUPERSEDED"},
}


class GatewayError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sign_claim(claim: Mapping[str, Any], key: bytes) -> str:
    _require_key(key)
    body = {k: claim[k] for k in CLAIM_FIELDS}
    return hmac.new(key, canonical(body), hashlib.sha256).hexdigest()


def payload_hash(event: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical(event)).hexdigest()


def route_forbidden(route: str) -> str | None:
    text = (route or "").strip().lower()
    if not text:
        return "missing_route"
    tokens = [tok for tok in re.split(r"[^a-z0-9]+", text) if tok]
    collapsed = text.replace("-", "").replace("/", "")
    for token in tokens:
        if token in FORBIDDEN_ROUTE_TOKENS:
            return token
    for token in FORBIDDEN_ROUTE_TOKENS:
        if token in collapsed and token not in {"title"}:
            return token
    if text not in {"coordination/event", "coordination/status"}:
        return "route_not_allowlisted"
    return None


def handle_request(
    request: Mapping[str, Any],
    *,
    key: bytes,
    now: datetime | float,
    nonce_store: dict[str, float],
    idempotency_store: dict[str, dict[str, Any]],
    expected_origin_sha: str,
    lane_allowlist: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Authenticate and accept, or return a typed refusal. Never sends."""
    peer = request.get("peer")
    route = str(request.get("route") or "")
    blocked = route_forbidden(route)
    if blocked:
        return _refused(None, f"forbidden_route:{blocked}", peer_ignored=peer)

    try:
        claim = _verify_claim(request, key=key, now=now, nonce_store=nonce_store)
    except GatewayError as exc:
        return _refused(None, exc.reason, peer_ignored=peer)

    operation = str(request.get("operation") or "")
    allow = frozenset(lane_allowlist) if lane_allowlist is not None else PILOT_LANES
    if operation == "status":
        return _status(request, claim, idempotency_store, peer)
    if operation == "accept_event":
        return _accept(
            request,
            claim,
            now=_unix(now),
            store=idempotency_store,
            expected_origin_sha=expected_origin_sha,
            allow=allow,
            peer=peer,
        )
    if operation in {"claim", "start", "artifact", "consumer_ack", "refuse", "cancel"}:
        return _transition(operation, request, claim, idempotency_store, peer)
    return _refused(None, "unknown_operation", peer_ignored=peer)


def _accept(
    request: Mapping[str, Any],
    claim: Mapping[str, Any],
    *,
    now: float,
    store: dict[str, dict[str, Any]],
    expected_origin_sha: str,
    allow: frozenset[str],
    peer: Any,
) -> dict[str, Any]:
    event = request.get("event")
    if not isinstance(event, Mapping):
        return _refused(None, "malformed_event", peer_ignored=peer)
    try:
        _validate_event(event, expected_origin_sha=expected_origin_sha, allow=allow)
        _reject_secret_material(event)
    except GatewayError as exc:
        return _refused(event if isinstance(event, Mapping) else None, exc.reason, peer_ignored=peer)
    if claim["project"] != event["source_project"]:
        return _refused(event, "project_mismatch", peer_ignored=peer)
    key = _idem_key(event)
    digest = payload_hash(event)
    prior = store.get(key)
    if prior is not None:
        if prior.get("payload_hash") != digest:
            return _refused(event, "idempotency_conflict", peer_ignored=peer)
        replay = dict(prior["receipt"])
        replay["duplicate"] = True
        return replay
    receipt = _receipt(event, state="ACCEPTED", reason=None, at=now)
    store[key] = {"payload_hash": digest, "receipt": receipt}
    return dict(receipt)


def _transition(
    operation: str,
    request: Mapping[str, Any],
    claim: Mapping[str, Any],
    store: dict[str, dict[str, Any]],
    peer: Any,
) -> dict[str, Any]:
    found = _find(request, claim, store)
    if isinstance(found, dict) and found.get("state") == "REFUSED":
        return found
    slot, receipt = found
    target = {
        "claim": "CLAIMED",
        "start": "STARTED",
        "artifact": "ARTIFACT_WRITTEN",
        "consumer_ack": "CONSUMED",
        "refuse": "REFUSED",
        "cancel": "CANCELLED",
    }[operation]
    if target not in EDGES.get(receipt["state"], ()):
        return _refused(None, f"illegal_transition:{receipt['state']}->{target}", peer_ignored=peer)
    if operation == "consumer_ack":
        ack = request.get("consumer_receipt")
        if not isinstance(ack, Mapping) or not ack.get("consumer") or not ack.get("receipt_id"):
            return _refused(None, "no_consumer_receipt", peer_ignored=peer)
        try:
            _reject_secret_material(ack)
        except GatewayError as exc:
            return _refused(None, exc.reason, peer_ignored=peer)
    if operation == "refuse" and not request.get("reason"):
        return _refused(None, "missing_refusal_reason", peer_ignored=peer)
    updated = dict(receipt)
    updated["state"] = target
    updated["reason"] = request.get("reason") if target == "REFUSED" else receipt.get("reason")
    if target == "CONSUMED":
        updated["consumer"] = str(request["consumer_receipt"].get("consumer"))
        updated["consumer_receipt_id"] = str(request["consumer_receipt"].get("receipt_id"))
    updated["effects"] = []
    updated["outbound"] = "blocked"
    updated["mutation"] = "blocked"
    slot["receipt"] = updated
    return dict(updated)


def _status(request, claim, store, peer) -> dict[str, Any]:
    found = _find(request, claim, store)
    if isinstance(found, dict) and found.get("state") == "REFUSED":
        return found
    _slot, receipt = found
    out = dict(receipt)
    out["duplicate"] = False
    return out


def _find(request, claim, store):
    event = request.get("event") if isinstance(request.get("event"), Mapping) else None
    idem = request.get("idempotency_key") or (event or {}).get("idempotency_key")
    project = claim["project"]
    if event is not None and event.get("source_project") not in (None, project):
        return _refused(event, "project_mismatch", peer_ignored=request.get("peer"))
    if not idem or not isinstance(idem, str):
        return _refused(None, "missing_idempotency_key", peer_ignored=request.get("peer"))
    slot = store.get(f"{project}:{idem}")
    if slot is None:
        return _refused(None, "unknown_event", peer_ignored=request.get("peer"))
    return slot, dict(slot["receipt"])


def _validate_event(event: Mapping[str, Any], *, expected_origin_sha: str, allow: frozenset[str]) -> None:
    for key in event:
        if str(key).lower() in SECRET_KEYS:
            raise GatewayError("secret_material")
    extra = set(event) - EVENT_FIELDS
    if extra:
        raise GatewayError("unexpected_field")
    missing = [name for name in EVENT_FIELDS if name not in event]
    if missing:
        raise GatewayError("malformed_event")
    if not isinstance(event["event_id"], str) or len(event["event_id"]) < 8:
        raise GatewayError("malformed_event")
    if event["source_project"] not in ALLOWED_PROJECTS:
        raise GatewayError("unknown_project")
    if event["schema_version"] != SCHEMA_VERSION:
        raise GatewayError("bad_schema_version")
    if event["authority_class"] != "coordination_read":
        raise GatewayError("authority_refused")
    if event["lane_id"] not in allow:
        raise GatewayError("unknown_lane")
    if not isinstance(event["origin_sha"], str) or not SHA_RE.fullmatch(event["origin_sha"]):
        raise GatewayError("malformed_sha")
    if not expected_origin_sha or event["origin_sha"] != expected_origin_sha:
        raise GatewayError("stale_origin_sha")
    minimum = {"subject_key": 1, "artifact_ref": 1, "correlation_id": 8, "idempotency_key": 8}
    for name, size in minimum.items():
        if not isinstance(event[name], str) or len(event[name]) < size:
            raise GatewayError("malformed_event")
    _parse_time(event["source_timestamp"])
    _parse_time(event["deadline"])


def _verify_claim(request, *, key: bytes, now, nonce_store: dict[str, float]) -> dict[str, Any]:
    _require_key(key)
    claim = request.get("claim")
    signature = request.get("signature")
    if not isinstance(claim, Mapping) or not isinstance(signature, str) or not signature:
        raise GatewayError("missing_signature")
    if set(claim) != CLAIM_FIELDS:
        raise GatewayError("malformed_claim")
    if claim.get("v") != 1 or claim.get("scope") != "coordination_read":
        raise GatewayError("bad_scope")
    if claim.get("project") not in ALLOWED_PROJECTS:
        raise GatewayError("unknown_project")
    if not isinstance(claim.get("caller_id"), str) or len(claim["caller_id"]) < 3:
        raise GatewayError("malformed_claim")
    if not isinstance(claim.get("nonce"), str) or len(claim["nonce"]) < 8:
        raise GatewayError("malformed_claim")
    try:
        iat = float(claim["iat"])
        exp = float(claim["exp"])
    except (TypeError, ValueError) as exc:
        raise GatewayError("malformed_claim") from exc
    instant = _unix(now)
    if exp <= iat or (exp - iat) > MAX_CLAIM_LIFE_S:
        raise GatewayError("claim_lifetime")
    if iat > instant + MAX_SKEW_S or exp < instant:
        raise GatewayError("claim_expired")
    signed = {k: claim[k] for k in CLAIM_FIELDS}
    expected = hmac.new(key, canonical(signed), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        raise GatewayError("bad_signature")
    nonce = claim["nonce"]
    prior = nonce_store.get(nonce)
    if prior is not None and prior >= instant:
        raise GatewayError("replayed_nonce")
    nonce_store[nonce] = exp
    return signed


def _reject_secret_material(payload: Mapping[str, Any]) -> None:
    for key, value in payload.items():
        if str(key).lower() in SECRET_KEYS:
            raise GatewayError("secret_material")
        if isinstance(value, str) and SECRET_VALUE_RE.search(value):
            raise GatewayError("secret_material")
        if isinstance(value, Mapping):
            _reject_secret_material(value)


def _receipt(event: Mapping[str, Any], *, state: str, reason: str | None, at: float) -> dict[str, Any]:
    return {
        "schema": RECEIPT_SCHEMA,
        "state": state,
        "reason": reason,
        "event_id": event.get("event_id"),
        "source_project": event.get("source_project"),
        "lane_id": event.get("lane_id"),
        "idempotency_key": event.get("idempotency_key"),
        "origin_sha": event.get("origin_sha"),
        "payload_hash": payload_hash(event) if event else None,
        "recorded_at": datetime.fromtimestamp(at, timezone.utc).isoformat(),
        "effects": [],
        "outbound": "blocked",
        "mutation": "blocked",
        "durable": False,
        "duplicate": False,
        "peer_used_as_auth": False,
    }


def _refused(event: Mapping[str, Any] | None, reason: str, *, peer_ignored: Any) -> dict[str, Any]:
    body = event if isinstance(event, Mapping) else {}
    receipt = _receipt(body, state="REFUSED", reason=reason, at=datetime.now(timezone.utc).timestamp())
    receipt["peer_ignored"] = peer_ignored is not None
    receipt["peer_used_as_auth"] = False
    return receipt


def _idem_key(event: Mapping[str, Any]) -> str:
    return f"{event['source_project']}:{event['idempotency_key']}"


def _unix(now: datetime | float) -> float:
    if isinstance(now, datetime):
        if now.tzinfo is None:
            raise GatewayError("naive_clock")
        return now.timestamp()
    return float(now)


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise GatewayError("malformed_event")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GatewayError("malformed_event") from exc
    if parsed.tzinfo is None:
        raise GatewayError("malformed_event")
    return parsed


def _require_key(key: bytes) -> None:
    if not isinstance(key, (bytes, bytearray)) or len(key) < 32:
        raise GatewayError("missing_gateway_key")

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


#: Every refusal reason the gateway can emit. A reason outside this set is a bug, not a new state;
#: tests/test_n8n_gateway_durable_20261007.py scans the source for literals. ``illegal_transition:A->B``
#: and ``typed_refusal:<code>`` are prefixed families.
REFUSAL_REASONS = frozenset({
    "missing_signature", "malformed_claim", "bad_scope", "unknown_project", "claim_lifetime", "claim_expired",
    "bad_signature", "replayed_nonce", "missing_gateway_key", "naive_clock", "malformed_event", "unexpected_field",
    "bad_schema_version", "authority_refused", "unknown_lane", "malformed_sha", "stale_origin_sha", "secret_material",
    "forbidden_route", "project_mismatch", "idempotency_conflict", "unknown_operation", "missing_idempotency_key",
    "unknown_event", "no_consumer_receipt", "missing_refusal_reason", "artifact_ref_required", "artifact_bytes_refused",
    "artifact_ref_too_large", "list_unsupported", "bad_time",
})
REFUSAL_PREFIXES = ("illegal_transition:", "typed_refusal:", "forbidden_route:")
ARTIFACT_REF_FIELDS = frozenset({"store", "ref", "sha256", "as_of"})
ARTIFACT_BYTES_KEYS = frozenset({"content", "bytes", "body", "data", "base64", "payload"})
MAX_ARTIFACT_REF_BYTES = 4096
LIST_SCHEMA = "N8nCoordinationList@v1"
MAX_LIST = 200


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
    previous_key: bytes | None = None,
) -> dict[str, Any]:
    """Authenticate and accept, or return a typed refusal. Never sends."""
    peer = request.get("peer")
    route = str(request.get("route") or "")
    blocked = route_forbidden(route)
    if blocked:
        return _refused(None, f"forbidden_route:{blocked}", peer_ignored=peer)

    try:
        claim = _verify_claim(
            request,
            key=key,
            now=now,
            nonce_store=nonce_store,
            previous_key=previous_key,
        )
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
    if operation == "list":
        return _list(request, claim, idempotency_store, peer)
    return _refused(None, "unknown_operation", peer_ignored=peer)


def _list(request, claim, store, peer) -> dict[str, Any]:
    """Receipts for the caller's project, newest first; filters lane_id / state / since. Read-only."""
    lane = request.get("lane_id")
    state = request.get("state")
    since = request.get("since")
    if since is not None:
        try:
            _parse_time(since)
        except GatewayError:
            return _refused(None, "bad_time", peer_ignored=peer)
    items: list[dict[str, Any]]
    if hasattr(store, "iter_receipts"):
        items = store.iter_receipts(project=claim["project"], lane_id=lane, state=state, since=since, limit=MAX_LIST)
    elif isinstance(store, dict):
        items = []
        for slot in store.values():
            r = slot.get("receipt") or {}
            if r.get("source_project") != claim["project"]:
                continue
            if lane and r.get("lane_id") != lane:
                continue
            if state and r.get("state") != state:
                continue
            if since and str(r.get("recorded_at") or "") < str(since):
                continue
            items.append(dict(r))
        items = sorted(items, key=lambda r: str(r.get("recorded_at") or ""), reverse=True)[:MAX_LIST]
    else:
        return _refused(None, "list_unsupported", peer_ignored=peer)
    return {"schema": LIST_SCHEMA, "state": "OK", "project": claim["project"], "count": len(items), "items": items,
            "durable": bool(getattr(store, "durable", False)), "peer_used_as_auth": False}


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
    receipt["durable"] = bool(getattr(store, "durable", False))
    store[key] = {"payload_hash": digest, "receipt": receipt}   # a ledger store commits here or raises
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
    artifact_ref = None
    if operation == "artifact":
        ref = request.get("artifact_ref")
        if not isinstance(ref, Mapping) or not ref.get("store") or not ref.get("ref"):
            return _refused(None, "artifact_ref_required", peer_ignored=peer)
        if set(ref) - ARTIFACT_REF_FIELDS or any(k in ARTIFACT_BYTES_KEYS for k in request):
            return _refused(None, "artifact_bytes_refused", peer_ignored=peer)
        if len(canonical(ref)) > MAX_ARTIFACT_REF_BYTES:
            return _refused(None, "artifact_ref_too_large", peer_ignored=peer)
        sha = ref.get("sha256")
        if sha is not None and not re.fullmatch(r"[0-9a-f]{64}", str(sha)):
            return _refused(None, "artifact_ref_required", peer_ignored=peer)
        try:
            _reject_secret_material(ref)
        except GatewayError as exc:
            return _refused(None, exc.reason, peer_ignored=peer)
        artifact_ref = {k: ref.get(k) for k in ("store", "ref", "sha256", "as_of")}
    updated = dict(receipt)
    updated["state"] = target
    if artifact_ref is not None:
        updated["artifact_ref"] = artifact_ref
    updated["reason"] = request.get("reason") if target == "REFUSED" else receipt.get("reason")
    if target == "CONSUMED":
        updated["consumer"] = str(request["consumer_receipt"].get("consumer"))
        updated["consumer_receipt_id"] = str(request["consumer_receipt"].get("receipt_id"))
    updated["effects"] = []
    updated["outbound"] = "blocked"
    updated["mutation"] = "blocked"
    updated["durable"] = bool(getattr(store, "durable", False))
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


def _verify_claim(
    request,
    *,
    key: bytes,
    now,
    nonce_store: dict[str, float],
    previous_key: bytes | None = None,
) -> dict[str, Any]:
    _require_key(key)
    if previous_key is not None:
        _require_key(previous_key)
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
    keys = [key] if previous_key is None else [key, previous_key]
    signature_ok = False
    for candidate in keys:
        expected = hmac.new(candidate, canonical(signed), hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, signature.lower()):
            signature_ok = True
            break
    if not signature_ok:
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
    if reason not in REFUSAL_REASONS and not reason.startswith(REFUSAL_PREFIXES):
        raise GatewayError("unknown_refusal_reason:" + reason)   # a reason outside the enum is a bug
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

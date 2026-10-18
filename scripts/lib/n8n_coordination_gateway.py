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
import math
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "event-reference/v0"
RECEIPT_SCHEMA = "N8nCoordinationReceipt@v1"
#: 2026-10-08 (n8n scheduler-of-record, tranche N1): the `run` operation. The gateway records a run
#: REQUEST in the ledger `runs` table and returns this envelope; a separate executor process claims
#: the row. The gateway never spawns, and nothing here widens the forbidden-route list.
RUN_REQUESTED_SCHEMA = "RunRequested@v1"
#: The existing v1 run envelope is closed. Current relay/host producers use only these fields; adding a field
#: requires an explicitly supported contract change, even if a producer calls the new field "optional".
RUN_REQUEST_FIELDS = frozenset({"route", "operation", "claim", "signature", "peer", "lane_id", "mode",
                                "idempotency_key", "requested_by"})
RUN_MODES = frozenset({"dry_run", "live"})
RUN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
#: Run-key namespaces the host validates before queueing (d:/e:/g: by n8n_due.check_slot_key, p: by
#: n8n_process_keys.check_process_key). Compared lower-case, so a case variant cannot pass as free-form.
VALIDATED_KEY_PREFIXES = frozenset({"d:", "e:", "g:", "p:"})
#: 2026-10-15 (#1767 follow-up): the key the relay MINTS for a body without idempotency_key,
#: n8n-wf-<workflow_id>-<execution_id> (scripts/n8n_run_relay.py _derived_run_id). One per n8n execution, bound to
#: the execution, and never caller-chosen (the relay refuses a supplied key in this namespace). The ten generated
#: per-lane workflows (four of them LIVE: crontab-snapshot-for-health-agent, n8n-pilot-dispatch, n8n-incident-fanin,
#: n8n-research-intake-consumer) send no key, so a live run from them carries this key. It is a host-minted
#: namespace, not a free-form one, and a LIVE relay run may use it.
RELAY_DERIVED_KEY_PREFIX = "n8n-wf-"
MAX_REQUESTED_BY = 128
SCOPE_READ = "coordination_read"
SCOPE_RUN = "coordination_run"
#: 2026-10-14 (n8n fabric Phase 1; AGENTS.md §23.23 + §23.3 route note, 10.0.0 PROPOSED): the send-INTENT scope.
#: It opens exactly one operation (`intent`) on exactly one route (`comms/intent`), only on the relay key. An intent
#: is queued for the host comms gateway (scripts/lib/n8n_fabric_store.py); the gateway itself never sends.
SCOPE_INTENT = "comms_intent"
SCOPES = frozenset({SCOPE_READ, SCOPE_RUN, SCOPE_INTENT})
#: Trade AI-side callers (dispatch, incident fan-in, research intake, telegram ack) all sign with
#: TRADEAI_N8N_GATEWAY_HMAC_KEY and carry read scope only. The relay identity signs with a second
#: key that never grants anything but run+read; it never falls back to the dispatch key.
DISPATCH_CALLER = "tradeai-dispatch"
RELAY_CALLER = "n8n-relay"
#: 2026-10-09 (n8n maturity B5.3, design 02 §3.1): `coordination/due` is a READ route (scope coordination_read,
#: operation `due` only). It computes what is due from the registry; it writes nothing and runs nothing.
#: 2026-10-14 (n8n fabric Phase 1): `coordination/run_outcome` is a READ route (scope coordination_read, operation
#: `run_outcome`, one run_id; writes nothing). `comms/intent` is the send-intent route (scope comms_intent only).
ALLOWED_ROUTES = frozenset(
    {
        "coordination/event",
        "coordination/status",
        "coordination/run",
        "coordination/due",
        "coordination/run_outcome",
        "comms/intent",
    }
)
DUE_ROUTE = "coordination/due"
RUN_OUTCOME_ROUTE = "coordination/run_outcome"
INTENT_ROUTE = "comms/intent"
#: `now` on a due request is advisory; more than this many seconds from the gateway clock is refused
#: (`due_clock_skew`). The value is the design's, not a tunable: docs/implementation/n8n-maturity/
#: 02-six-workflow-architecture.md §3.1 line 117 ("refuses `now` values more than 90 s from it") and failure row F12.
DUE_MAX_SKEW_S = 90
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
REFUSAL_REASONS = frozenset(
    {
        "missing_signature",
        "malformed_claim",
        "bad_scope",
        "unknown_project",
        "claim_lifetime",
        "claim_expired",
        "bad_signature",
        "replayed_nonce",
        "missing_gateway_key",
        "naive_clock",
        "malformed_event",
        "unexpected_field",
        "bad_schema_version",
        "authority_refused",
        "unknown_lane",
        "malformed_sha",
        "stale_origin_sha",
        "secret_material",
        "forbidden_route",
        "project_mismatch",
        "idempotency_conflict",
        "unknown_operation",
        "missing_idempotency_key",
        "unknown_event",
        "no_consumer_receipt",
        "missing_refusal_reason",
        "artifact_ref_required",
        "artifact_bytes_refused",
        "artifact_ref_too_large",
        "list_unsupported",
        "bad_time",
        # 2026-10-08 run route: lane not in config/n8n_run_allowlist.json; mode outside {dry_run, live}; no run-capable
        # key or no durable run store on this gateway; a caller_id that maps to no key.
        "run_lane_not_allowlisted",
        "run_bad_mode",
        "run_scope_unavailable",
        "unknown_caller",
        "process_not_registered",  # 2026-10-08 model_job: job.process_id outside n8n_model_job.PROCESS_TASK_TYPE
        # 2026-10-09 (B5.3): a d:/e:/g: key that compute_due does not currently hold DUE/RETRY_DUE in that mode.
        "run_slot_not_due",
        # 2026-10-16: host_run_request parent_run_id is not a FAILED live d:/e: run of the same lane (slot-bound retry).
        "run_retry_parent_invalid",
        # 2026-10-09 (B5.3) operation `due` (DueResponse@v1 `refused`).
        "due_clock_skew",
        "bad_source",
        "bad_lane_filter",
        "registry_unreadable",
        "allowlist_unreadable",
        "policies_unreadable",
        # Read-only lifecycle status keeps missing/unavailable sources as typed refusals.
        "momentum_lifecycle_not_configured",
        "momentum_lifecycle_source_unavailable",
        # Server-owned providers return these protocol refusals as dictionaries.
        "momentum_lifecycle_no_durable_store",
        "momentum_lifecycle_disabled",
        "momentum_monitor_admission_unproven",
        "momentum_monitor_not_measured",
        "momentum_monitor_stale",
        "momentum_monitor_deployed_sha_drift",
        "momentum_monitor_policy_or_collection_drift",
        # 2026-10-14 (n8n fabric Phase 1): run_outcome without a durable outcome store; comms/intent without an
        # intent store, a (domain, kind) outside config/n8n_comms_intent_routes.json, the hourly cap, an unreadable
        # route table, or a store error.
        "run_outcome_unavailable",
        "intent_scope_unavailable",
        "intent_unrouted",
        "intent_rate_limited",
        "intent_routes_unreadable",
        "intent_store_unavailable",
        # 2026-10-15 (hermes-learning cutover prerequisite G3): a p:<lane>:<mode>:<slot> process-step key that
        # scripts/lib/n8n_process_keys.check_process_key refuses (``key_state`` on the refusal names why).
        "run_process_key_invalid",
        # 2026-10-15 (third-party audit, finding 1): a repeated idempotency_key whose stored row names another lane,
        # mode or requesting workflow. The original row is never returned to a different request.
        "run_idempotency_conflict",
        # 2026-10-15 (audit DD03): a LIVE run from the n8n relay caller whose key is in no host-validated namespace
        # (d:/e:/g: server-minted, p: manifest-validated). Free-form keys stay available to dry runs and to host callers.
        "run_key_namespace_refused",
    }
)
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


@dataclass(frozen=True)
class CallerKey:
    """One HMAC key, the scopes it may claim, and whether unnamed Trade AI-side callers fall back to it."""

    key: bytes
    scopes: frozenset[str] = field(default_factory=lambda: frozenset({SCOPE_READ}))
    previous_key: bytes | None = None
    default: bool = False


def build_caller_keys(
    key: bytes,
    *,
    previous_key: bytes | None = None,
    n8n_key: bytes | None = None,
    n8n_previous_key: bytes | None = None,
) -> dict[str, CallerKey]:
    """CALLER_KEYS for a gateway process. The dispatch key keeps its previous-key rotation overlap and serves
    every Trade AI-side caller_id (``default=True``). The n8n relay key is optional: without it the run scope is
    simply unavailable, and ``n8n-relay`` claims are refused rather than verified against the dispatch key.
    ``n8n_previous_key`` is that relay key's own overlap (TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N_PREVIOUS). It never
    verifies a dispatch claim, and the dispatch previous key never verifies a relay claim."""
    out = {DISPATCH_CALLER: CallerKey(key=key, scopes=frozenset({SCOPE_READ}), previous_key=previous_key, default=True)}
    if n8n_key is not None:
        out[RELAY_CALLER] = CallerKey(
            key=n8n_key,
            scopes=frozenset({SCOPE_RUN, SCOPE_READ, SCOPE_INTENT}),
            previous_key=n8n_previous_key,
        )
    return out


def resolve_caller(caller_keys: Mapping[str, CallerKey], caller_id: str) -> CallerKey | None:
    """Exact caller match first; otherwise the one default entry, except for the reserved relay identity."""
    exact = caller_keys.get(caller_id)
    if exact is not None:
        return exact
    if caller_id == RELAY_CALLER:
        return None
    for entry in caller_keys.values():
        if entry.default:
            return entry
    return None


def canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sign_claim(claim: Mapping[str, Any], key: bytes) -> str:
    _require_key(key)
    body = {k: claim[k] for k in CLAIM_FIELDS}
    return hmac.new(key, canonical(body), hashlib.sha256).hexdigest()


def payload_hash(event: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical(event)).hexdigest()


def forbidden_route_token(text: str) -> str | None:
    """The first FORBIDDEN_ROUTE_TOKENS entry in ``text``: a whole token, or a substring of the text with
    '-' and '/' removed (so `placeorders` and `n8n-activation-grants` match). The matcher route_forbidden
    uses; scripts/lib/lane_dispatch.py reuses it for lane eligibility. None when clean."""
    text = (text or "").strip().lower()
    tokens = [tok for tok in re.split(r"[^a-z0-9]+", text) if tok]
    collapsed = text.replace("-", "").replace("/", "")
    for token in tokens:
        if token in FORBIDDEN_ROUTE_TOKENS:
            return token
    for token in FORBIDDEN_ROUTE_TOKENS:
        if token in collapsed and token not in {"title"}:
            return token
    return None


def route_forbidden(route: str) -> str | None:
    text = (route or "").strip().lower()
    if not text:
        return "missing_route"
    hit = forbidden_route_token(text)
    if hit is not None:
        return hit
    if text not in ALLOWED_ROUTES:
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
    caller_keys: Mapping[str, CallerKey] | None = None,
    run_store: Any = None,
    run_allowlist: frozenset[str] | set[str] | None = None,
    due_sources: Any = None,
    momentum_provider: Any = None,
    outcome_store: Any = None,
    intent_store: Any = None,
    process_sources: Any = None,
) -> dict[str, Any]:
    """Authenticate and accept, or return a typed refusal. Never sends, never spawns.

    ``process_sources`` (2026-10-15): what validates a ``p:`` process-step run key — None re-reads
    config/n8n_fabric_processes.json + the process manifests on every call (n8n_process_keys.load_sources), a
    Mapping is used as given (tests), a callable is called per request.

    ``outcome_store`` (scripts/lib/n8n_fabric_store.RunOutcomeStore) serves the read operation ``run_outcome``;
    ``intent_store`` (CommsIntentStore) the ``intent`` operation. None = that operation refuses as unavailable.

    ``due_sources`` (scripts/lib/n8n_due.DueSources) feeds the read operation ``due`` and the slot-key check in
    ``run``; None means neither is configured (``due`` refuses registry_unreadable, server-minted run keys refuse
    run_slot_not_due)."""
    peer = request.get("peer")
    if callable(run_allowlist):
        # 2026-10-15 (audit DD08): a PolicyFile / loader is resolved per request, so a revoked lane is refused on
        # the next request without a restart (scripts/lib/n8n_policy_reload.py; unreadable = empty = refuse all).
        run_allowlist = run_allowlist()
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
            caller_keys=caller_keys,
        )
    except GatewayError as exc:
        return _refused(None, exc.reason, peer_ignored=peer)

    operation = str(request.get("operation") or "")
    # The run scope opens exactly one operation on exactly one route; a read-scope claim never runs
    # anything and a run-scope claim never reads or transitions an event.
    if operation == "run" or route.strip().lower() == "coordination/run":
        if operation != "run" or route.strip().lower() != "coordination/run":
            return _refused(None, "unknown_operation", peer_ignored=peer)
        if claim["scope"] != SCOPE_RUN:
            return _refused(None, "bad_scope", peer_ignored=peer)
        return _run(
            request,
            claim,
            run_store=run_store,
            run_allowlist=run_allowlist,
            now=_unix(now),
            peer=peer,
            due_sources=due_sources,
            process_sources=process_sources,
        )
    # The intent scope likewise opens exactly one operation on exactly one route, and nothing else opens it.
    if operation == "intent" or route.strip().lower() == INTENT_ROUTE:
        if operation != "intent" or route.strip().lower() != INTENT_ROUTE:
            return _refused(None, "unknown_operation", peer_ignored=peer)
        if claim["scope"] != SCOPE_INTENT:
            return _refused(None, "bad_scope", peer_ignored=peer)
        return _intent(request, claim, intent_store=intent_store, now=_unix(now), peer=peer)
    if claim["scope"] != SCOPE_READ:
        return _refused(None, "bad_scope", peer_ignored=peer)
    if operation == "run_outcome" or route.strip().lower() == RUN_OUTCOME_ROUTE:
        if operation != "run_outcome" or route.strip().lower() != RUN_OUTCOME_ROUTE:
            return _refused(None, "unknown_operation", peer_ignored=peer)
        return _run_outcome(request, outcome_store=outcome_store, run_store=run_store, peer=peer)
    if operation == "momentum_lifecycle":
        if route.strip().lower() != "coordination/status" or set(request) - {
            "route",
            "operation",
            "claim",
            "signature",
        }:
            return _refused(None, "unexpected_field", peer_ignored=peer)
        if momentum_provider is None:
            return _refused(None, "momentum_lifecycle_not_configured", peer_ignored=peer)
        try:
            return momentum_provider(datetime.fromtimestamp(_unix(now), timezone.utc))
        except (OSError, ValueError, TypeError):
            return _refused(None, "momentum_lifecycle_source_unavailable", peer_ignored=peer)
    if operation == "due" or route.strip().lower() == DUE_ROUTE:
        if operation != "due" or route.strip().lower() != DUE_ROUTE:
            return _refused(None, "unknown_operation", peer_ignored=peer)
        return _due(
            request,
            run_store=run_store,
            run_allowlist=run_allowlist,
            due_sources=due_sources,
            now=_unix(now),
            peer=peer,
        )
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
    if operation == "model_job":
        return _model_job(request, claim, idempotency_store, peer, now=now)
    return _refused(None, "unknown_operation", peer_ignored=peer)


def _due_mod():
    """scripts/lib/n8n_due, imported lazily: n8n_due -> lane_dispatch imports this module."""
    try:
        from scripts.lib import n8n_due as D  # type: ignore
    except ImportError:
        import n8n_due as D  # type: ignore
    return D


def _due_refused(code: str, peer) -> dict[str, Any]:
    """A due refusal is the gateway's ordinary typed refusal ({state: REFUSED, reason}); it does NOT carry the
    DueResponse@v1 label, whose schema is closed and describes only a computed answer."""
    return _refused(None, code, peer_ignored=peer)


def _load_due_inputs(due_sources, run_allowlist):
    """(rows, rsha, entries, asha, policies, psha) or raise GatewayError(<source>_unreadable). The allowlist is
    narrowed to the lanes this gateway loaded at serve time, so due never emits a lane `run` would refuse."""
    D = _due_mod()
    if due_sources is None:
        raise GatewayError("registry_unreadable")
    try:
        rows, rsha = due_sources.load_registry()
    except D.DueSourceError as exc:
        raise GatewayError("registry_unreadable") from exc
    try:
        entries, asha = due_sources.load_allowlist()
    except D.DueSourceError as exc:
        raise GatewayError("allowlist_unreadable") from exc
    try:
        policies, psha = due_sources.load_policies()
    except D.DueSourceError as exc:
        raise GatewayError("policies_unreadable") from exc
    if run_allowlist is not None:
        entries = {k: v for k, v in entries.items() if k in frozenset(run_allowlist)}
    return rows, rsha, entries, asha, policies, psha


def _due(request, *, run_store, run_allowlist, due_sources, now: float, peer) -> dict[str, Any]:
    """DueResponse@v1 (design 02 §3). Read-only: nothing is written, nothing is run."""
    D = _due_mod()
    source = request.get("source", "schedule")
    if source not in D.SOURCES:
        return _due_refused("bad_source", peer)
    claimed = request.get("now")
    if claimed is not None:
        try:
            if abs(_parse_time(claimed).timestamp() - now) > DUE_MAX_SKEW_S:
                return _due_refused("due_clock_skew", peer)
        except GatewayError:
            return _due_refused("due_clock_skew", peer)
    limit = request.get("limit", D.DEFAULT_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int):
        limit = D.DEFAULT_LIMIT
    limit = max(1, min(limit, D.MAX_LIMIT))
    try:
        rows, rsha, entries, asha, policies, psha = _load_due_inputs(due_sources, run_allowlist)
    except GatewayError as exc:
        return _due_refused(exc.reason, peer)
    lane_filter = request.get("lane_filter")
    if lane_filter is not None:
        known = {r["lane_id"] for r in rows}
        if (
            not isinstance(lane_filter, list)
            or not lane_filter
            or len(lane_filter) > D.MAX_LANE_FILTER
            or not all(isinstance(x, str) and x in known for x in lane_filter)
        ):
            return _due_refused("bad_lane_filter", peer)
    return D.compute_due(
        rows,
        entries,
        policies,
        run_store,
        now,
        source=source,
        lane_filter=lane_filter,
        limit=limit,
        tz=getattr(due_sources, "tz", D.DEFAULT_TZ),
        registry_sha=rsha,
        allowlist_sha=asha,
        policies_sha=psha,
    )


def _run_envelope(row, duplicate: bool, run_store) -> dict[str, Any]:
    return {
        "schema": RUN_REQUESTED_SCHEMA,
        "state": row["state"],
        "run_id": row["run_id"],
        "lane_id": row["lane_id"],
        "mode": row["mode"],
        "requested_by": row.get("requested_by"),
        "caller_id": row.get("caller_id"),
        "requested_at": row.get("requested_at"),
        "durable": bool(getattr(run_store, "durable", False)),
        "duplicate": bool(duplicate),
        "peer_used_as_auth": False,
    }


def _norm_requested_by(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _identity_conflict(row: Mapping[str, Any], lane_id: str, mode: str, requested_by: Any) -> list[str]:
    """Which of (lane_id, mode, requested_by) a stored ``runs`` row disagrees on. Empty = same request identity."""
    out = []
    if row.get("lane_id") != lane_id:
        out.append("lane_id")
    if row.get("mode") != mode:
        out.append("mode")
    if _norm_requested_by(row.get("requested_by")) != _norm_requested_by(requested_by):
        out.append("requested_by")
    return out


def _replay_or_conflict(row, duplicate: bool, run_store, *, lane_id: str, mode: str, requested_by, peer):
    """2026-10-15 (audit finding 1, REQUEST IDENTITY): the ONE place a run reply is built. A duplicate whose stored
    row names another lane, mode or requesting workflow is ``run_idempotency_conflict`` (``conflict_fields`` names
    which), never the other request's row. Applied to the row ``run_store.request`` returned, so the check sees
    the row the atomic insert-or-return-existing settled on (no get-then-insert race)."""
    if duplicate:
        fields = _identity_conflict(row, lane_id, mode, requested_by)
        if fields:
            out = _refused(None, "run_idempotency_conflict", peer_ignored=peer)
            out["conflict_fields"] = fields
            return out
    return _run_envelope(row, duplicate, run_store)


def _process_sources(process_sources: Any):
    """The p: key validation sources, or None when unreadable (the check then fails closed)."""
    from scripts.lib import n8n_process_keys as PK

    try:
        if process_sources is None:
            return PK.load_sources()
        if callable(process_sources):
            return process_sources()
        return process_sources
    except (PK.ProcessKeyError, OSError, ValueError):
        return None


def _run_process_key(
    request,
    claim,
    *,
    run_store,
    run_id: str,
    lane_id: str,
    mode: str,
    requested_by,
    now: float,
    peer,
    process_sources: Any,
) -> dict[str, Any]:
    """2026-10-15 (AGENTS.md §23.23 "idempotency keys server-minted or manifest-validated, never free-form"): a
    ``p:<lane>:<mode>:<slot>[:aN]`` key is accepted only when it names a runnable step of a registered fabric process,
    in a mode the process spec allows, for a current slot (scripts/lib/n8n_process_keys.py). The row stores the base
    key as ``slot_key``: the executor's effect gate claims a live p: key only when that marker is present."""
    from scripts.lib import n8n_process_keys as PK

    parsed = PK.parse_process_key(run_id)
    if parsed is None or parsed[0] != lane_id or parsed[1] != mode:
        out = _refused(None, "run_process_key_invalid", peer_ignored=peer)
        out["key_state"] = "MALFORMED_KEY" if parsed is None else "KEY_MISMATCH"
        return out
    existing = run_store.get(run_id)
    if existing is not None:
        if existing.get("lane_id") != lane_id or existing.get("mode") != mode:
            out = _refused(None, "run_process_key_invalid", peer_ignored=peer)
            out["key_state"] = "KEY_MISMATCH"
            return out
        return _replay_or_conflict(
            existing, True, run_store, lane_id=lane_id, mode=mode, requested_by=requested_by, peer=peer
        )
    check = PK.check_process_key(run_id, lane_id, mode, sources=_process_sources(process_sources), now=now)
    if not check.ok:
        out = _refused(None, "run_process_key_invalid", peer_ignored=peer)
        out["key_state"] = check.state
        return out
    if check.attempt > 1:
        # 2026-10-15 (audit DD04, one retry owner): Run Lane owns p: retries, but the HOST decides whether there is
        # one. Attempt n is admitted only after attempt n-1 of the same base key FINISHED with executor verdict
        # ``retryable`` (send/learn and terminal failures never are). A missing / running / terminal / ok
        # predecessor refuses, so a retry can never run beside, or after the success of, its predecessor.
        prev_key = check.slot_key if check.attempt == 2 else f"{check.slot_key}:a{check.attempt - 1}"
        prev = run_store.get(prev_key)
        if prev is None or prev.get("verdict") != "retryable":
            out = _refused(None, "run_process_key_invalid", peer_ignored=peer)
            out["key_state"] = "ATTEMPT_NOT_RETRYABLE"
            out["previous_verdict"] = None if prev is None else prev.get("verdict")
            return out
    row, duplicate = run_store.request(
        run_id=run_id,
        lane_id=lane_id,
        mode=mode,
        requested_by=requested_by,
        caller_id=claim["caller_id"],
        now=now,
        slot_key=check.slot_key,
        attempt=check.attempt,
    )
    out = _replay_or_conflict(row, duplicate, run_store, lane_id=lane_id, mode=mode, requested_by=requested_by, peer=peer)
    if out.get("state") == "REFUSED":
        return out
    out["process_key"] = {
        "process_id": check.process_id,
        "step_id": check.step_id,
        "stage": check.stage,
        "slot": check.slot,
        "slot_kind": check.slot_kind,
    }
    return out


def _run(
    request, claim, *, run_store, run_allowlist, now: float, peer, due_sources=None, process_sources: Any = None,
    parent_run_id: str | None = None,
) -> dict[str, Any]:
    """Record a run REQUEST for an allowlisted lane. The gateway writes one ``runs`` row (state REQUESTED) and
    returns RunRequested@v1; scripts/n8n_run_executor.py claims it from the ledger. A repeated idempotency_key from the
    SAME request identity (lane_id, mode, requested_by) returns the existing row with ``duplicate: true`` whatever
    state it has reached; from any other identity it is ``run_idempotency_conflict`` (2026-10-15 audit finding 1:
    before, a free-form key replayed by another lane/mode got the first request's row back). Nothing is spawned."""
    if run_store is None:
        return _refused(None, "run_scope_unavailable", peer_ignored=peer)
    try:
        _reject_secret_material({k: v for k, v in request.items() if k not in {"claim", "signature"}})
    except GatewayError as exc:
        return _refused(None, exc.reason, peer_ignored=peer)
    if set(request) - RUN_REQUEST_FIELDS:
        return _refused(None, "unexpected_field", peer_ignored=peer)
    lane_id = request.get("lane_id")
    if not isinstance(lane_id, str) or not lane_id or lane_id not in frozenset(run_allowlist or ()):
        return _refused(None, "run_lane_not_allowlisted", peer_ignored=peer)
    mode = request.get("mode")
    if mode not in RUN_MODES:
        return _refused(None, "run_bad_mode", peer_ignored=peer)
    run_id = request.get("idempotency_key")
    if not isinstance(run_id, str) or not run_id:
        return _refused(None, "missing_idempotency_key", peer_ignored=peer)
    if not RUN_ID_RE.fullmatch(run_id):
        return _refused(None, "malformed_event", peer_ignored=peer)
    requested_by = request.get("requested_by")
    if requested_by is not None and (not isinstance(requested_by, str) or len(requested_by) > MAX_REQUESTED_BY):
        return _refused(None, "malformed_event", peer_ignored=peer)
    prefix = run_id[:2].lower()
    relay_minted = run_id[: len(RELAY_DERIVED_KEY_PREFIX)].lower() == RELAY_DERIVED_KEY_PREFIX
    if (
        mode == "live"
        and claim.get("caller_id") == RELAY_CALLER
        and prefix not in VALIDATED_KEY_PREFIXES
        and not relay_minted
    ):
        # 2026-10-15 (audit DD03 "reject unknown/unvalidated namespaces before queueing"): n8n may not name the
        # identity of a LIVE run with a free-form string; it must carry a server-minted or manifest-validated key.
        out = _refused(None, "run_key_namespace_refused", peer_ignored=peer)
        out["key_state"] = "UNVALIDATED_NAMESPACE"
        return out
    if prefix == "p:":
        return _run_process_key(
            request,
            claim,
            run_store=run_store,
            run_id=run_id,
            lane_id=lane_id,
            mode=mode,
            requested_by=requested_by,
            now=now,
            peer=peer,
            process_sources=process_sources,
        )
    if run_id[:2].lower() in ("d:", "e:", "g:"):
        # 2026-10-09 (B5.3, design 02 §3.3): a server-minted slot key. A replay of an accepted key returns the
        # existing row (it is IN_FLIGHT/DONE now, so it is no longer DUE); otherwise compute_due must currently
        # hold this exact key DUE or RETRY_DUE in this mode, or n8n invented the slot. The prefix test is
        # case-insensitive so `D:`/`E:`/`G:` cannot bypass the check as a "legacy" key: only the exact lower-case,
        # well-formed form is accepted, and its lane/mode must be the request's (a replay never returns another
        # lane's row).
        D = _due_mod()
        parsed = D.parse_key(run_id)
        if parsed is None:
            out = _refused(None, "run_slot_not_due", peer_ignored=peer)
            out["slot_state"] = "MALFORMED_KEY"
            return out
        if parsed[1] != lane_id or parsed[2] != mode:
            out = _refused(None, "run_slot_not_due", peer_ignored=peer)
            out["slot_state"] = "KEY_MISMATCH"
            return out
        existing = run_store.get(run_id)
        if existing is not None:
            if existing.get("lane_id") != lane_id or existing.get("mode") != mode:
                out = _refused(None, "run_slot_not_due", peer_ignored=peer)
                out["slot_state"] = "KEY_MISMATCH"
                return out
            return _replay_or_conflict(
                existing, True, run_store, lane_id=lane_id, mode=mode, requested_by=requested_by, peer=peer
            )
        try:
            rows, _rsha, entries, _asha, policies, _psha = _load_due_inputs(due_sources, run_allowlist)
        except GatewayError:
            return _refused(None, "run_slot_not_due", peer_ignored=peer)
        check = D.check_slot_key(
            run_id,
            lane_id,
            mode,
            registry_rows=rows,
            allowlist=entries,
            policies=policies,
            run_store=run_store,
            now=now,
            tz=getattr(due_sources, "tz", D.DEFAULT_TZ),
        )
        if not check.ok:
            out = _refused(None, "run_slot_not_due", peer_ignored=peer)
            out["slot_state"] = check.state
            return out
        row, duplicate = run_store.request(
            run_id=run_id,
            lane_id=lane_id,
            mode=mode,
            requested_by=requested_by,
            caller_id=claim["caller_id"],
            now=now,
            slot_key=check.slot_key,
            attempt=check.attempt,
            parent_run_id=check.parent_run_id,
            klass=check.klass,
            priority=check.priority,
        )
        return _replay_or_conflict(
            row, duplicate, run_store, lane_id=lane_id, mode=mode, requested_by=requested_by, peer=peer
        )
    if parent_run_id is not None:
        # 2026-10-16: a host retry bound to a failed slot (validated by host_run_request; never reachable from n8n).
        row, duplicate = run_store.request(
            run_id=run_id, lane_id=lane_id, mode=mode, requested_by=requested_by, caller_id=claim["caller_id"],
            now=now, parent_run_id=parent_run_id,
        )
    else:
        row, duplicate = run_store.request(
            run_id=run_id, lane_id=lane_id, mode=mode, requested_by=requested_by, caller_id=claim["caller_id"], now=now
        )
    return _replay_or_conflict(row, duplicate, run_store, lane_id=lane_id, mode=mode, requested_by=requested_by, peer=peer)


RUN_OUTCOME_FIELDS = frozenset({"route", "operation", "claim", "signature", "peer", "run_id"})
INTENT_REQUEST_FIELDS = frozenset(
    {
        "route",
        "operation",
        "claim",
        "signature",
        "peer",
        "domain",
        "kind",
        "subject",
        "summary",
        "workflow_id",
        "execution_id",
        "node",
    }
)


def _run_outcome(request, *, outcome_store, run_store, peer) -> dict[str, Any]:
    """RunOutcome@v1 for one run_id (n8n fabric Phase 1, REFACTOR_PLAN B4 poll route). Read-only. A run the
    ledger does not know is ``status: unknown``; one still REQUESTED/RUNNING is ``pending``; a refused run is
    ``refused_policy`` — all data with state OK, never a gateway refusal."""
    if set(request) - RUN_OUTCOME_FIELDS:
        return _refused(None, "unexpected_field", peer_ignored=peer)
    run_id = request.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        return _refused(None, "malformed_event", peer_ignored=peer)
    if outcome_store is None:
        return _refused(None, "run_outcome_unavailable", peer_ignored=peer)
    try:
        view = outcome_store.view(run_id, run_store)
    except sqlite3.Error:
        return _refused(None, "run_outcome_unavailable", peer_ignored=peer)
    view["peer_used_as_auth"] = False
    view["durable"] = True
    return view


def _intent(request, claim, *, intent_store, now: float, peer) -> dict[str, Any]:
    """CommsIntentReceipt@v1: validate, dedupe, cap, route and QUEUE one notification intent for the host comms
    gateway (§23.23, §24.1). Nothing is sent here. The store raises n8n_fabric_store.FabricStoreError (a ValueError
    with ``reason``); it is matched by that attribute so this module imports nothing new."""
    if intent_store is None:
        return _refused(None, "intent_scope_unavailable", peer_ignored=peer)
    if set(request) - INTENT_REQUEST_FIELDS:
        return _refused(None, "unexpected_field", peer_ignored=peer)
    try:
        _reject_secret_material({k: v for k, v in request.items() if k not in {"claim", "signature"}})
    except GatewayError as exc:
        return _refused(None, exc.reason, peer_ignored=peer)
    try:
        receipt = intent_store.accept(request, caller_id=claim["caller_id"], now=now)
    except ValueError as exc:
        reason = getattr(exc, "reason", None)
        return _refused(None, reason if reason in REFUSAL_REASONS else "intent_store_unavailable", peer_ignored=peer)
    except sqlite3.Error:
        return _refused(None, "intent_store_unavailable", peer_ignored=peer)
    receipt["peer_used_as_auth"] = False
    return receipt


#: Parent states a slot-bound host retry may follow (2026-10-16). Only RUN_FAILED: its effect claim is FAILED, which
#: the effect ledger re-claims (attempt + 1) only when proven pre-effect; any other state is refused here.
RETRY_PARENT_STATES = frozenset({"RUN_FAILED"})


def check_retry_parent(run_store, *, parent_run_id: str, lane_id: str, mode: str) -> str | None:
    """None when ``parent_run_id`` may parent a slot-bound live retry of ``lane_id``; else the refusal reason."""
    if mode != "live":
        return "retry_parent_needs_live"
    D = _due_mod()
    parsed = D.parse_key(str(parent_run_id or ""))
    if parsed is None or parsed[0] not in ("d", "e"):
        return "retry_parent_not_slot_key"
    getter = getattr(run_store, "get", None)
    parent = getter(parent_run_id) if callable(getter) else None
    if parent is None:
        return "retry_parent_missing"
    if parent.get("lane_id") != lane_id or parsed[1] != lane_id:
        return "retry_parent_lane_mismatch"
    if parent.get("mode") != "live" or parsed[2] != "live":
        return "retry_parent_mode_mismatch"
    if parent.get("state") not in RETRY_PARENT_STATES:
        return "retry_parent_not_failed"
    return None


def host_run_request(
    *, lane_id: str, mode: str, run_id: str, requested_by: str, caller_id: str, run_store, run_allowlist, now: float,
    parent_run_id: str | None = None,
) -> dict[str, Any]:
    """``coordination/run`` for a caller already on the host (no bearer to verify): the SAME ``_run`` validation
    (allowlist, mode, run-id shape, secret material) and the same single REQUESTED row the gateway writes for n8n.
    The executor runs it, and the executor applies the §23.11 stage clamp (a shadow lane runs dry_run). Server-minted
    slot keys (``d:``/``e:``/``g:``) are the dispatcher's and are refused here. Added 2026-10-10 for the n8n failure
    diagnoser's catalogue reruns (REMEDIATION_PLAN §6 R2; operator "Ok" ~00:35 ET)."""
    if str(run_id or "")[:2].lower() in ("d:", "e:", "g:"):
        return _refused(None, "run_slot_not_due", peer_ignored=None)
    if str(run_id or "")[:2].lower() == "p:":
        # 2026-10-15: process-step keys belong to the fabric process workflow and are validated on the n8n route only.
        out = _refused(None, "run_process_key_invalid", peer_ignored=None)
        out["key_state"] = "HOST_CALLER_REFUSED"
        return out
    if parent_run_id is not None:
        # 2026-10-16 (n8n self-healing follow-up): a live retry bound to a FAILED d:/e: slot. The executor derives the
        # effect slot from the parent, so the slot's one effect claim decides: FAILED pre-effect re-claims (attempt+1),
        # DONE / CLAIMED / UNKNOWN / unproven FAILED refuse (effect_already_claimed). Validated here, before queueing.
        why = check_retry_parent(run_store, parent_run_id=parent_run_id, lane_id=lane_id, mode=mode)
        if why is not None:
            out = _refused(None, "run_retry_parent_invalid", peer_ignored=None)
            out["retry_parent_state"] = why
            return out
    request = {"lane_id": lane_id, "mode": mode, "idempotency_key": run_id, "requested_by": requested_by}
    return _run(request, {"caller_id": caller_id}, run_store=run_store, run_allowlist=run_allowlist, now=now, peer=None,
                parent_run_id=parent_run_id)


#: Injected by tests; production uses n8n_model_job.bridge_governed_call (loopback HTTP to the governed bridge).
MODEL_JOB_GOVERNED_CALL = None
MODEL_JOB_FIELDS = frozenset({"process_id", "artifact_ref", "correlation_id", "deadline", "output_schema_id"})
#: 2026-10-08 (n8n carve-out groundwork): a caller may NAME a prompt template and a routing policy; both are
#: short identifiers resolved server-side (n8n_model_job renders the template; the bridge receives the policy
#: name as a header and ignores it today). Raw prompt text is still not a job field.
MODEL_JOB_OPTIONAL_FIELDS = frozenset({"template_id", "routing_policy"})
MODEL_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _model_job(request, claim, store, peer, *, now) -> dict[str, Any]:
    """Run a governed model job for an event that is STARTED. The gateway never chooses the model
    or holds a credential: Trade AI resolves the artifact and calls its own governed bridge. The
    result is an artifact REFERENCE on the receipt (ARTIFACT_WRITTEN) or a typed refusal."""
    found = _find(request, claim, store)
    if isinstance(found, dict) and found.get("state") == "REFUSED":
        return found
    slot, receipt = found
    if receipt["state"] != "STARTED":
        return _refused(None, f"illegal_transition:{receipt['state']}->ARTIFACT_WRITTEN", peer_ignored=peer)
    job = request.get("job")
    if (
        not isinstance(job, Mapping)
        or set(job) - (MODEL_JOB_FIELDS | MODEL_JOB_OPTIONAL_FIELDS)
        or not all(k in job for k in MODEL_JOB_FIELDS)
    ):
        return _refused(None, "malformed_event", peer_ignored=peer)
    for opt in MODEL_JOB_OPTIONAL_FIELDS:
        if opt in job and not (isinstance(job[opt], str) and MODEL_JOB_ID_RE.match(job[opt])):
            return _refused(None, "malformed_event", peer_ignored=peer)
    try:
        _reject_secret_material(job)
    except GatewayError as exc:
        return _refused(None, exc.reason, peer_ignored=peer)
    if str(job.get("correlation_id")) != str(receipt.get("idempotency_key")) and str(job.get("correlation_id")) != str(
        receipt.get("event_id")
    ):
        return _refused(None, "project_mismatch", peer_ignored=peer)
    try:
        from scripts.lib import n8n_model_job as MJ  # type: ignore
    except ImportError:
        import n8n_model_job as MJ  # type: ignore
    # 2026-10-08: the task type is derived server-side from job.process_id (PROCESS_TASK_TYPE); a process outside
    # the map is refused here, before any artifact read or call, and the event stays STARTED for a corrected job.
    if str(job.get("process_id") or "") not in MJ.PROCESS_TASK_TYPE:
        return _refused(None, "process_not_registered", peer_ignored=peer)
    call = MODEL_JOB_GOVERNED_CALL or MJ.bridge_governed_call
    result = MJ.run_model_job(
        job,
        governed_call=call,
        now=now if isinstance(now, datetime) else datetime.fromtimestamp(_unix(now), timezone.utc),
    )
    updated = dict(receipt)
    updated["effects"] = []
    updated["outbound"] = "blocked"
    updated["mutation"] = "blocked"
    updated["durable"] = bool(getattr(store, "durable", False))
    updated["model_job"] = {
        k: result.get(k)
        for k in (
            "state",
            "reason",
            "detail",
            "cost",
            "started_at",
            "ended_at",
            "output_schema_id",
            "task_type",
            "template_id",
            "routing_policy",
        )
    }
    if result.get("state") == "ARTIFACT_WRITTEN":
        try:
            out_path = MJ.write_receipt(result)
            ref = {
                "store": "data/runtime",
                "ref": f"n8n_model_jobs/{out_path.name}",
                "sha256": result["artifact_out"]["sha256"],
                "as_of": result.get("ended_at"),
            }
        except OSError as exc:
            updated["state"] = "FAILED"
            updated["reason"] = "typed_refusal:receipt_write_failed"
            updated["model_job"]["detail"] = type(exc).__name__
            slot["receipt"] = updated
            return dict(updated)
        updated["state"] = "ARTIFACT_WRITTEN"
        updated["artifact_ref"] = ref
    else:
        updated["state"] = "REFUSED"
        updated["reason"] = f"typed_refusal:{result.get('reason')}"
    slot["receipt"] = updated
    return dict(updated)


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
    return {
        "schema": LIST_SCHEMA,
        "state": "OK",
        "project": claim["project"],
        "count": len(items),
        "items": items,
        "durable": bool(getattr(store, "durable", False)),
        "peer_used_as_auth": False,
    }


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
    store[key] = {"payload_hash": digest, "receipt": receipt}  # a ledger store commits here or raises
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


#: nonce read-then-consume lock for memory-only ({}) nonce stores; the ledger adapter brings its own.
_MEMORY_NONCE_LOCK = threading.Lock()


def _verify_claim(
    request,
    *,
    key: bytes,
    now,
    nonce_store: dict[str, float],
    previous_key: bytes | None = None,
    caller_keys: Mapping[str, CallerKey] | None = None,
) -> dict[str, Any]:
    _require_key(key)
    if previous_key is not None:
        _require_key(previous_key)
    if caller_keys is None:
        caller_keys = build_caller_keys(key, previous_key=previous_key)
    claim = request.get("claim")
    signature = request.get("signature")
    if not isinstance(claim, Mapping) or not isinstance(signature, str) or not signature:
        raise GatewayError("missing_signature")
    if set(claim) != CLAIM_FIELDS:
        raise GatewayError("malformed_claim")
    if type(claim.get("v")) is not int or claim["v"] != 1 or claim.get("scope") not in SCOPES:
        raise GatewayError("bad_scope")
    if claim.get("project") not in ALLOWED_PROJECTS:
        raise GatewayError("unknown_project")
    if not isinstance(claim.get("caller_id"), str) or len(claim["caller_id"]) < 3:
        raise GatewayError("malformed_claim")
    caller = resolve_caller(caller_keys, claim["caller_id"])
    if caller is None and claim["caller_id"] == RELAY_CALLER:
        # the relay identity without its key: the run scope is unavailable on this gateway
        raise GatewayError("run_scope_unavailable")
    if caller is None:
        raise GatewayError("unknown_caller")
    if claim["scope"] not in caller.scopes:
        raise GatewayError("bad_scope")
    _require_key(caller.key)
    if caller.previous_key is not None:
        _require_key(caller.previous_key)
    if not isinstance(claim.get("nonce"), str) or len(claim["nonce"]) < 8:
        raise GatewayError("malformed_claim")
    try:
        iat = float(claim["iat"])
        exp = float(claim["exp"])
    except (TypeError, ValueError, OverflowError) as exc:
        raise GatewayError("malformed_claim") from exc
    if not math.isfinite(iat) or not math.isfinite(exp):
        raise GatewayError("malformed_claim")
    instant = _unix(now)
    if exp <= iat or (exp - iat) > MAX_CLAIM_LIFE_S:
        raise GatewayError("claim_lifetime")
    if iat > instant + MAX_SKEW_S or exp < instant:
        raise GatewayError("claim_expired")
    signed = {k: claim[k] for k in CLAIM_FIELDS}
    keys = [caller.key] if caller.previous_key is None else [caller.key, caller.previous_key]
    signature_ok = False
    for candidate in keys:
        expected = hmac.new(candidate, canonical(signed), hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, signature.lower()):
            signature_ok = True
            break
    if not signature_ok:
        raise GatewayError("bad_signature")
    nonce = claim["nonce"]
    # 2026-10-08: read-then-consume is one critical section. A durable store (LedgerNonceStore) lends the
    # ledger's RLock; the memory-only dict store gets a module lock. Without this, two handler threads
    # presenting the same nonce inside the window both pass (one accept and one replayed_nonce is the contract).
    with getattr(nonce_store, "lock", None) or _MEMORY_NONCE_LOCK:
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
        raise GatewayError("unknown_refusal_reason:" + reason)  # a reason outside the enum is a bug
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

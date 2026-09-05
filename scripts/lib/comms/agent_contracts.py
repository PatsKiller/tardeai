"""Persistent-agent consumption contracts (Phase 8) — AgentConsumptionReceipt@v1.

CIO, Hermes, Advisory, Darwin, Maria (+ future with allow_unknown) subscribe via
contracts, acknowledge consumption, emit receipts, and declare influence lineage.

Agents must not self-certify institutional truth: no helper writes knowledge_status
ACCEPTED (or other truthy institutional statuses) on behalf of a consuming agent.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from scripts.lib.comms.identity import new_event_id

SCHEMA_VERSION = "AgentConsumptionReceipt@v1"

KNOWN_AGENTS = frozenset({"cio", "hermes", "advisory", "darwin", "maria"})

# Statuses that assert institutional truth; consumers may not claim these.
SELF_CERTIFYING_STATUSES = frozenset(
    {
        "ACCEPTED",
        "CERTIFIED",
        "CANONICAL",
        "AUTHORITATIVE",
        "INSTITUTIONAL_TRUTH",
        "TRUTH",
        "VERIFIED_TRUTH",
    }
)

_SUBSCRIPTIONS: dict[str, dict[str, Any]] = {}  # subscription_id -> row
_RECEIPTS: dict[str, dict[str, Any]] = {}  # receipt_id -> row
_lock = threading.Lock()


class AgentContractError(ValueError):
    """Fail-closed agent consumption / self-certification violation."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _normalize_agent_id(agent_id: str) -> str:
    return (agent_id or "").strip().lower()


def _require_known_agent(agent_id: str, *, allow_unknown: bool = False) -> str:
    aid = _normalize_agent_id(agent_id)
    if not aid:
        raise AgentContractError("agent_id required")
    if aid not in KNOWN_AGENTS and not allow_unknown:
        raise AgentContractError(
            f"unknown agent_id={aid!r}; known={sorted(KNOWN_AGENTS)} "
            "(pass allow_unknown=True for future agents)"
        )
    return aid


def assert_not_self_certifying_truth(agent_id: str, claimed_status: Any) -> None:
    """Raise if claimed_status is an institutional truth status.

    Consuming agents acknowledge consumption and declare influence; they do not
    certify that an event is institutional truth.
    """
    aid = _normalize_agent_id(agent_id) or "unknown"
    raw = "" if claimed_status is None else str(claimed_status).strip()
    if not raw:
        return
    status = raw.upper()
    if status in SELF_CERTIFYING_STATUSES:
        raise AgentContractError(
            f"self_certification_rejected: agent={aid!r} claimed_status={raw!r}; "
            "agents must not set knowledge_status to ACCEPTED/truthy institutional statuses"
        )


def _db_conn():
    """Best-effort connection; None when unavailable or agent tables missing."""
    try:
        from db_adapter import _get_conn  # scripts/ on path in many entrypoints
    except Exception:
        try:
            from scripts.db_adapter import _get_conn  # type: ignore
        except Exception:
            return None
    try:
        conn = _get_conn()
    except Exception:
        return None
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                 WHERE table_name IN (
                     'communication_agent_subscriptions',
                     'communication_agent_consumption_receipts'
                 )
                """
            )
            n = cur.fetchone()[0]
        if int(n) < 2:
            return None
    except Exception:
        return None
    return conn


def _normalize_filter(filt: dict[str, Any] | None) -> dict[str, Any]:
    if not filt:
        return {
            "message_classes": [],
            "severities": [],
            "subject_domains": [],
        }
    out: dict[str, Any] = {
        "message_classes": [
            str(x).strip() for x in (filt.get("message_classes") or []) if str(x).strip()
        ],
        "severities": [
            str(x).strip().lower()
            for x in (filt.get("severities") or [])
            if str(x).strip()
        ],
        "subject_domains": [
            str(x).strip().lower()
            for x in (filt.get("subject_domains") or [])
            if str(x).strip()
        ],
    }
    return out


@dataclass
class AgentConsumptionReceipt:
    """AgentConsumptionReceipt@v1 — agent retrieved/used a communication artifact."""

    agent_id: str
    event_id: str
    purpose: str
    receipt_id: str | None = None
    agent_version: str | None = None
    thread_id: str | None = None
    artifact_ids: list[Any] = field(default_factory=list)
    policy_decision: str | None = None
    retrieved_at: datetime | None = None
    acknowledged_at: datetime | None = None
    derived_artifact_ids: list[Any] = field(default_factory=list)
    influence_declaration: str | None = None
    influence_event_ids: list[Any] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION
    persisted: str = "none"

    def mint_identity(self) -> "AgentConsumptionReceipt":
        if not self.receipt_id:
            self.receipt_id = f"acr_{new_event_id()}"
        if self.retrieved_at is None:
            self.retrieved_at = _now()
        return self

    def to_dict(self) -> dict[str, Any]:
        self.mint_identity()
        d = asdict(self)
        d["retrieved_at"] = _iso(self.retrieved_at)
        d["acknowledged_at"] = _iso(self.acknowledged_at)
        return d


def register_subscription(
    agent_id: str,
    *,
    agent_version: str,
    filter: dict[str, Any] | None = None,
    enabled: bool = True,
    allow_unknown: bool = False,
) -> dict[str, Any]:
    """Register (or replace matching) subscription for an agent. Returns row dict."""
    aid = _require_known_agent(agent_id, allow_unknown=allow_unknown)
    ver = (agent_version or "").strip()
    if not ver:
        raise AgentContractError("agent_version required")
    filt = _normalize_filter(filter)
    sub_id = f"sub_{new_event_id()}"
    when = _now()
    row = {
        "subscription_id": sub_id,
        "agent_id": aid,
        "agent_version": ver,
        "filter": filt,
        "enabled": bool(enabled),
        "created_at": when,
        "persisted": "memory",
    }

    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO communication_agent_subscriptions (
                        subscription_id, agent_id, agent_version, filter, enabled, created_at
                    ) VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        sub_id,
                        aid,
                        ver,
                        json.dumps(filt),
                        bool(enabled),
                        when,
                    ),
                )
            conn.commit()
            row["persisted"] = "db"
            with _lock:
                _SUBSCRIPTIONS[sub_id] = dict(row)
            return dict(row)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    with _lock:
        _SUBSCRIPTIONS[sub_id] = dict(row)
    return dict(row)


def list_subscriptions(agent_id: str | None = None) -> list[dict[str, Any]]:
    """List subscriptions; optionally filter by agent_id."""
    aid = _normalize_agent_id(agent_id) if agent_id else None

    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                if aid:
                    cur.execute(
                        """
                        SELECT subscription_id, agent_id, agent_version, filter,
                               enabled, created_at
                          FROM communication_agent_subscriptions
                         WHERE agent_id = %s
                         ORDER BY created_at DESC
                        """,
                        (aid,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT subscription_id, agent_id, agent_version, filter,
                               enabled, created_at
                          FROM communication_agent_subscriptions
                         ORDER BY created_at DESC
                        """
                    )
                cols = [
                    "subscription_id",
                    "agent_id",
                    "agent_version",
                    "filter",
                    "enabled",
                    "created_at",
                ]
                rows = []
                for tup in cur.fetchall():
                    r = dict(zip(cols, tup))
                    filt = r.get("filter")
                    if isinstance(filt, str):
                        r["filter"] = json.loads(filt)
                    elif filt is None:
                        r["filter"] = _normalize_filter(None)
                    r["persisted"] = "db"
                    rows.append(r)
                if rows:
                    return rows
        except Exception:
            pass

    with _lock:
        items = [dict(v) for v in _SUBSCRIPTIONS.values()]
    if aid:
        items = [x for x in items if x.get("agent_id") == aid]
    items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    for x in items:
        x["persisted"] = x.get("persisted") or "memory"
    return items


def _event_field(event: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in event and event[k] is not None:
            return event[k]
    return default


def _subject_domain_from_event(event: dict[str, Any]) -> str:
    explicit = _event_field(event, "subject_domain", "domain")
    if explicit:
        return str(explicit).strip().lower()
    sk = str(_event_field(event, "subject_key", default="") or "")
    if ":" in sk:
        return sk.split(":", 1)[0].strip().lower()
    return ""


def _filter_matches(filt: dict[str, Any], event: dict[str, Any]) -> bool:
    """Empty dimension lists mean match-all for that dimension."""
    classes = filt.get("message_classes") or []
    severities = filt.get("severities") or []
    domains = filt.get("subject_domains") or []

    if classes:
        mc = str(_event_field(event, "message_class", default="") or "").strip()
        if mc not in classes:
            return False
    if severities:
        sev = str(_event_field(event, "severity", default="") or "").strip().lower()
        if sev not in severities:
            return False
    if domains:
        dom = _subject_domain_from_event(event)
        if dom not in domains:
            return False
    return True


def eligible_events_for_agent(
    agent_id: str,
    events: list[dict],
    *,
    allow_unknown: bool = False,
) -> list:
    """Return events matching any enabled subscription filter for the agent.

    Agents with no enabled subscription receive an empty list.
    Empty filter dimensions match all values for that dimension.
    """
    aid = _require_known_agent(agent_id, allow_unknown=allow_unknown)
    subs = [s for s in list_subscriptions(aid) if s.get("enabled")]
    if not subs:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        eid = str(_event_field(ev, "event_id", default="") or "")
        matched = False
        for sub in subs:
            filt = sub.get("filter") or {}
            if isinstance(filt, str):
                try:
                    filt = json.loads(filt)
                except Exception:
                    filt = {}
            if _filter_matches(_normalize_filter(filt), ev):
                matched = True
                break
        if matched:
            key = eid or json.dumps(ev, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                out.append(ev)
    return out


def emit_consumption_receipt(
    agent_id: str,
    *,
    event_id: str,
    purpose: str,
    agent_version: str | None = None,
    thread_id: str | None = None,
    artifact_ids: list[Any] | None = None,
    policy_decision: str | None = None,
    derived_artifact_ids: list[Any] | None = None,
    influence_declaration: str | None = None,
    influence_event_ids: list[Any] | None = None,
    knowledge_status: Any = None,
    claimed_knowledge_status: Any = None,
    allow_unknown: bool = False,
) -> AgentConsumptionReceipt:
    """Emit AgentConsumptionReceipt@v1 for agent retrieval/use of an event.

    Requires agent_id, event_id, purpose. Optional influence_declaration.
    Rejects any attempt to claim knowledge_status ACCEPTED / truthy statuses.
    Does not write knowledge_status onto the communication event.
    """
    aid = _require_known_agent(agent_id, allow_unknown=allow_unknown)
    eid = (event_id or "").strip()
    if not eid:
        raise AgentContractError("event_id required")
    purp = (purpose or "").strip()
    if not purp:
        raise AgentContractError("purpose required")

    # Explicit anti-self-certification: consumers never stamp institutional truth.
    for claimed in (knowledge_status, claimed_knowledge_status):
        assert_not_self_certifying_truth(aid, claimed)

    receipt = AgentConsumptionReceipt(
        agent_id=aid,
        event_id=eid,
        purpose=purp,
        agent_version=(agent_version or "").strip() or None,
        thread_id=(thread_id or None),
        artifact_ids=list(artifact_ids or []),
        policy_decision=policy_decision,
        derived_artifact_ids=list(derived_artifact_ids or []),
        influence_declaration=influence_declaration,
        influence_event_ids=list(influence_event_ids or []),
    )
    receipt.mint_identity()
    row = receipt.to_dict()
    row["persisted"] = "memory"

    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO communication_agent_consumption_receipts (
                        receipt_id, agent_id, agent_version, event_id, thread_id,
                        artifact_ids, purpose, policy_decision, retrieved_at,
                        acknowledged_at, derived_artifact_ids,
                        influence_declaration, influence_event_ids, schema_version
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s::jsonb, %s, %s, %s,
                        %s, %s::jsonb,
                        %s, %s::jsonb, %s
                    )
                    ON CONFLICT (agent_id, event_id, purpose) DO UPDATE SET
                        agent_version = EXCLUDED.agent_version,
                        thread_id = EXCLUDED.thread_id,
                        artifact_ids = EXCLUDED.artifact_ids,
                        policy_decision = EXCLUDED.policy_decision,
                        derived_artifact_ids = EXCLUDED.derived_artifact_ids,
                        influence_declaration = COALESCE(
                            EXCLUDED.influence_declaration,
                            communication_agent_consumption_receipts.influence_declaration
                        ),
                        influence_event_ids = EXCLUDED.influence_event_ids
                    RETURNING receipt_id
                    """,
                    (
                        receipt.receipt_id,
                        aid,
                        receipt.agent_version,
                        eid,
                        receipt.thread_id,
                        json.dumps(receipt.artifact_ids),
                        purp,
                        receipt.policy_decision,
                        receipt.retrieved_at,
                        receipt.acknowledged_at,
                        json.dumps(receipt.derived_artifact_ids),
                        receipt.influence_declaration,
                        json.dumps(receipt.influence_event_ids),
                        SCHEMA_VERSION,
                    ),
                )
                returned = cur.fetchone()
                if returned and returned[0]:
                    receipt.receipt_id = returned[0]
                    row["receipt_id"] = receipt.receipt_id
            conn.commit()
            row["persisted"] = "db"
            receipt.persisted = "db"
            with _lock:
                _RECEIPTS[receipt.receipt_id] = dict(row)
            return receipt
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    with _lock:
        # Soft unique on (agent_id, event_id, purpose) in memory.
        for existing in _RECEIPTS.values():
            if (
                existing.get("agent_id") == aid
                and existing.get("event_id") == eid
                and existing.get("purpose") == purp
            ):
                # Update in place; keep original receipt_id / retrieved_at.
                rid = existing["receipt_id"]
                existing.update(
                    {
                        "agent_version": receipt.agent_version,
                        "thread_id": receipt.thread_id,
                        "artifact_ids": list(receipt.artifact_ids),
                        "policy_decision": receipt.policy_decision,
                        "derived_artifact_ids": list(receipt.derived_artifact_ids),
                        "influence_declaration": receipt.influence_declaration
                        or existing.get("influence_declaration"),
                        "influence_event_ids": list(receipt.influence_event_ids),
                        "persisted": "memory",
                    }
                )
                receipt.receipt_id = rid
                receipt.retrieved_at = existing.get("retrieved_at") or receipt.retrieved_at
                receipt.acknowledged_at = existing.get("acknowledged_at")
                receipt.persisted = "memory"
                return receipt
        _RECEIPTS[receipt.receipt_id] = dict(row)
    receipt.persisted = "memory"
    return receipt


def get_consumption_receipt(receipt_id: str) -> dict[str, Any] | None:
    """Lookup receipt by id (DB then memory)."""
    rid = (receipt_id or "").strip()
    if not rid:
        return None

    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT receipt_id, agent_id, agent_version, event_id, thread_id,
                           artifact_ids, purpose, policy_decision, retrieved_at,
                           acknowledged_at, derived_artifact_ids,
                           influence_declaration, influence_event_ids, schema_version
                      FROM communication_agent_consumption_receipts
                     WHERE receipt_id = %s
                    """,
                    (rid,),
                )
                tup = cur.fetchone()
                if tup:
                    cols = [
                        "receipt_id",
                        "agent_id",
                        "agent_version",
                        "event_id",
                        "thread_id",
                        "artifact_ids",
                        "purpose",
                        "policy_decision",
                        "retrieved_at",
                        "acknowledged_at",
                        "derived_artifact_ids",
                        "influence_declaration",
                        "influence_event_ids",
                        "schema_version",
                    ]
                    r = dict(zip(cols, tup))
                    for jk in ("artifact_ids", "derived_artifact_ids", "influence_event_ids"):
                        if isinstance(r.get(jk), str):
                            r[jk] = json.loads(r[jk])
                    r["persisted"] = "db"
                    return r
        except Exception:
            pass

    with _lock:
        row = _RECEIPTS.get(rid)
        return dict(row) if row else None


def acknowledge_consumption(receipt_id: str) -> dict[str, Any]:
    """Set acknowledged_at on an existing receipt."""
    rid = (receipt_id or "").strip()
    if not rid:
        raise AgentContractError("receipt_id required")
    when = _now()

    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE communication_agent_consumption_receipts
                       SET acknowledged_at = %s
                     WHERE receipt_id = %s
                 RETURNING receipt_id
                    """,
                    (when, rid),
                )
                if cur.fetchone():
                    conn.commit()
                    row = get_consumption_receipt(rid)
                    if row:
                        with _lock:
                            _RECEIPTS[rid] = dict(row)
                        return row
            conn.rollback()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    with _lock:
        row = _RECEIPTS.get(rid)
        if not row:
            raise AgentContractError(f"receipt_not_found:{rid}")
        row["acknowledged_at"] = when
        return dict(row)


def declare_influence(
    receipt_id: str,
    influence_declaration: str,
    influence_event_ids: list[Any] | None = None,
) -> dict[str, Any]:
    """Attach influence lineage to an existing consumption receipt."""
    rid = (receipt_id or "").strip()
    if not rid:
        raise AgentContractError("receipt_id required")
    decl = (influence_declaration or "").strip()
    if not decl:
        raise AgentContractError("influence_declaration required")
    ids = list(influence_event_ids or [])

    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE communication_agent_consumption_receipts
                       SET influence_declaration = %s,
                           influence_event_ids = %s::jsonb
                     WHERE receipt_id = %s
                 RETURNING receipt_id
                    """,
                    (decl, json.dumps(ids), rid),
                )
                if cur.fetchone():
                    conn.commit()
                    row = get_consumption_receipt(rid)
                    if row:
                        with _lock:
                            _RECEIPTS[rid] = dict(row)
                        return row
            conn.rollback()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    with _lock:
        row = _RECEIPTS.get(rid)
        if not row:
            raise AgentContractError(f"receipt_not_found:{rid}")
        row["influence_declaration"] = decl
        row["influence_event_ids"] = ids
        return dict(row)


def memory_agent_contracts_snapshot() -> dict[str, Any]:
    """Test helper: copy of in-process subscriptions + receipts."""
    with _lock:
        return {
            "subscriptions": {k: dict(v) for k, v in _SUBSCRIPTIONS.items()},
            "receipts": {k: dict(v) for k, v in _RECEIPTS.items()},
        }


def reset_agent_contracts_memory() -> None:
    """Test helper: clear in-process subscription and receipt stores."""
    with _lock:
        _SUBSCRIPTIONS.clear()
        _RECEIPTS.clear()

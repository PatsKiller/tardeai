"""Librarian retention for communications (Phase 6).

Owns lifecycle classification — NOT source truth. RetentionDecision@v1 actions:
KEEP, COMPACT, REDACT, DELETE_CONTENT_KEEP_TOMBSTONE, DELETE_ALL_ALLOWED, HOLD.

Knowledge promotion requires provenance, evidence, ownership, and review.
Chat is never auto-promoted to ACCEPTED.
"""
from __future__ import annotations

import copy
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from scripts.lib.comms.event import CommunicationEvent
from scripts.lib.comms.identity import new_event_id

SCHEMA_VERSION = "RetentionDecision@v1"
POLICY_VERSION = SCHEMA_VERSION
DECIDED_BY_DEFAULT = "comms.librarian"
PURGE_RECEIPT_SCHEMA = "PurgeReceipt@v1"

# ---------------------------------------------------------------------------
# Retention actions (RetentionDecision@v1)
# ---------------------------------------------------------------------------

KEEP = "KEEP"
COMPACT = "COMPACT"
REDACT = "REDACT"
DELETE_CONTENT_KEEP_TOMBSTONE = "DELETE_CONTENT_KEEP_TOMBSTONE"
DELETE_ALL_ALLOWED = "DELETE_ALL_ALLOWED"
HOLD = "HOLD"

RETENTION_ACTIONS = frozenset(
    {
        KEEP,
        COMPACT,
        REDACT,
        DELETE_CONTENT_KEEP_TOMBSTONE,
        DELETE_ALL_ALLOWED,
        HOLD,
    }
)

# Actions that purge content when executed after expiry.
_PURGE_ACTIONS = frozenset({DELETE_CONTENT_KEEP_TOMBSTONE, DELETE_ALL_ALLOWED, REDACT, COMPACT})

# ---------------------------------------------------------------------------
# Knowledge candidate statuses
# ---------------------------------------------------------------------------

CANDIDATE = "CANDIDATE"
ACCEPTED = "ACCEPTED"
DISPUTED = "DISPUTED"
SUPERSEDED = "SUPERSEDED"
RETRACTED = "RETRACTED"
REJECTED = "REJECTED"

KNOWLEDGE_STATUSES = frozenset(
    {
        CANDIDATE,
        ACCEPTED,
        DISPUTED,
        SUPERSEDED,
        RETRACTED,
        REJECTED,
    }
)

# Terminal statuses that require an explicit reviewer decision.
_DECIDABLE_STATUSES = frozenset(
    {ACCEPTED, DISPUTED, SUPERSEDED, RETRACTED, REJECTED}
)

# ---------------------------------------------------------------------------
# Retention-class heuristics (seconds)
# ---------------------------------------------------------------------------

_DAY = 86400

# (content_ttl, metadata_ttl, embedding_ttl, attachment_ttl, action, reason)
_CLASS_HEURISTICS: dict[str, tuple[int | None, int | None, int | None, int | None, str, str]] = {
    "operational_30d": (
        30 * _DAY,
        90 * _DAY,
        30 * _DAY,
        30 * _DAY,
        DELETE_CONTENT_KEEP_TOMBSTONE,
        "operational_30d: purge body after 30d; keep tombstone",
    ),
    "ops_7d": (
        7 * _DAY,
        30 * _DAY,
        7 * _DAY,
        7 * _DAY,
        DELETE_CONTENT_KEEP_TOMBSTONE,
        "ops_7d: short operational TTL",
    ),
    "inbound_7d": (
        7 * _DAY,
        30 * _DAY,
        7 * _DAY,
        7 * _DAY,
        DELETE_CONTENT_KEEP_TOMBSTONE,
        "inbound_7d: inbound chatter short TTL",
    ),
    "approval_ttl": (
        365 * _DAY,
        365 * _DAY * 3,
        90 * _DAY,
        365 * _DAY,
        KEEP,
        "approval_ttl: audit trail retained",
    ),
    "research_365d": (
        365 * _DAY,
        365 * _DAY * 2,
        365 * _DAY,
        365 * _DAY,
        COMPACT,
        "research_365d: compact narrative after 365d",
    ),
    "protection_365d": (
        365 * _DAY,
        365 * _DAY * 3,
        90 * _DAY,
        365 * _DAY,
        KEEP,
        "protection_365d: protection incidents retained",
    ),
    "audit_indefinite": (
        None,
        None,
        None,
        None,
        KEEP,
        "audit_indefinite: no automatic expiry",
    ),
}

_DEFAULT_HEURISTIC = (
    30 * _DAY,
    90 * _DAY,
    30 * _DAY,
    30 * _DAY,
    DELETE_CONTENT_KEEP_TOMBSTONE,
    "default: unknown retention_class treated as operational_30d",
)

# In-process fallback when DB / tables unavailable.
_DECISIONS: dict[str, dict[str, Any]] = {}  # decision_id → row
_DECISIONS_BY_EVENT: dict[str, list[str]] = {}  # event_id → [decision_id…]
_TOMBSTONES: dict[str, dict[str, Any]] = {}  # event_id → row
_CANDIDATES: dict[str, dict[str, Any]] = {}  # candidate_id → row
_PURGE_RECEIPTS: dict[str, dict[str, Any]] = {}  # receipt_id → row
_lock = threading.Lock()


@dataclass
class RetentionDecision:
    """RetentionDecision@v1 — lifecycle classification for one communication."""

    event_id: str
    retention_class: str
    action: str
    decision_id: str | None = None
    content_ttl_seconds: int | None = None
    metadata_ttl_seconds: int | None = None
    embedding_ttl_seconds: int | None = None
    attachment_ttl_seconds: int | None = None
    legal_hold: bool = False
    reason: str | None = None
    decided_by: str = DECIDED_BY_DEFAULT
    policy_version: str = POLICY_VERSION
    decided_at: datetime | None = None
    expires_at: datetime | None = None
    receipt: dict[str, Any] = field(default_factory=dict)
    persisted: str = "none"

    def mint_identity(self) -> "RetentionDecision":
        if not self.event_id or not str(self.event_id).strip():
            raise ValueError("event_id required for RetentionDecision")
        if self.action not in RETENTION_ACTIONS:
            raise ValueError(f"action_invalid:{self.action}")
        if not self.decision_id:
            self.decision_id = f"rtd_{new_event_id()}"
        if self.decided_at is None:
            self.decided_at = datetime.now(timezone.utc)
        return self

    def to_row(self) -> dict[str, Any]:
        self.mint_identity()
        d = asdict(self)
        d.pop("persisted", None)
        return d


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_event_dict(event_like: dict[str, Any] | CommunicationEvent) -> dict[str, Any]:
    if isinstance(event_like, CommunicationEvent):
        return event_like.to_row()
    if isinstance(event_like, dict):
        return dict(event_like)
    raise TypeError("event_like must be dict or CommunicationEvent")


def _parse_ttl_from_class_name(retention_class: str) -> int | None:
    """Best-effort parse of trailing Nd / Nh patterns (e.g. foo_14d → 14 days)."""
    rc = (retention_class or "").strip().lower()
    if not rc:
        return None
    # trailing _<n>d
    if rc.endswith("d"):
        parts = rc.rsplit("_", 1)
        if len(parts) == 2 and parts[1][:-1].isdigit():
            return int(parts[1][:-1]) * _DAY
    if rc.endswith("h"):
        parts = rc.rsplit("_", 1)
        if len(parts) == 2 and parts[1][:-1].isdigit():
            return int(parts[1][:-1]) * 3600
    return None


def _as_str_list(value: Any) -> list[str]:
    """Normalise an optional string-or-list into a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def _content_hashes_from_receipt(receipt: Any) -> list[str]:
    """Collect content hashes carried on a decision receipt, if present."""
    hashes: list[str] = []
    if isinstance(receipt, dict):
        val = receipt.get("content_hash")
        if val:
            hashes.append(str(val))
    return hashes


def record_purge_receipt(
    *,
    decision_id: str,
    action: str,
    retention_class: str,
    event_ids: Any = None,
    artifact_ids: Any = None,
    content_hashes: Any = None,
    tombstone: bool = False,
    decided_by: str | None = None,
    policy_version: str | None = None,
    decided_at: datetime | None = None,
    dry_run: bool = False,
    note: str | None = None,
) -> dict[str, Any]:
    """Record a durable purge/compaction/redaction receipt (PurgeReceipt@v1).

    Written for every destructive lifecycle action — KEEP, COMPACT, REDACT,
    DELETE_CONTENT_KEEP_TOMBSTONE, DELETE_ALL_ALLOWED, HOLD — including the
    dry-run "would-delete" path, so a destruction is auditable even when it did
    not happen. Scheduling and the retention-class table are operator-owned and
    are never wired here.
    """
    action_n = (action or "").strip()
    if not action_n:
        raise ValueError("action required for purge receipt")

    row = {
        "receipt_id": f"pr_{new_event_id()}",
        "decision_id": decision_id,
        "action": action_n,
        "retention_class": (retention_class or "").strip() or "unknown",
        "event_ids": _as_str_list(event_ids),
        "artifact_ids": _as_str_list(artifact_ids),
        "content_hashes": _as_str_list(content_hashes),
        "tombstone": bool(tombstone),
        "decided_by": (decided_by or "").strip() or DECIDED_BY_DEFAULT,
        "policy_version": (policy_version or "").strip() or POLICY_VERSION,
        "decided_at": decided_at,
        "dry_run": bool(dry_run),
        "note": note,
        "schema": PURGE_RECEIPT_SCHEMA,
        "receipt_at": _now(),
        "persisted": "memory",
    }

    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO communication_purge_receipts (
                        receipt_id, decision_id, action, retention_class,
                        event_ids, artifact_ids, content_hashes, tombstone,
                        decided_by, policy_version, decided_at, dry_run, note,
                        receipt_at
                    ) VALUES (
                        %(receipt_id)s, %(decision_id)s, %(action)s,
                        %(retention_class)s, %(event_ids)s::jsonb,
                        %(artifact_ids)s::jsonb, %(content_hashes)s::jsonb,
                        %(tombstone)s, %(decided_by)s, %(policy_version)s,
                        %(decided_at)s, %(dry_run)s, %(note)s, %(receipt_at)s
                    )
                    """,
                    {
                        **row,
                        "event_ids": json.dumps(row["event_ids"], default=str),
                        "artifact_ids": json.dumps(row["artifact_ids"], default=str),
                        "content_hashes": json.dumps(row["content_hashes"], default=str),
                    },
                )
            conn.commit()
            row["persisted"] = "db"
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            row["persisted"] = "memory"

    with _lock:
        _PURGE_RECEIPTS[row["receipt_id"]] = copy.deepcopy(row)
    return copy.deepcopy(row)


def get_purge_receipt(receipt_id: str) -> dict[str, Any] | None:
    """Return one purge receipt by id, or None."""
    with _lock:
        row = _PURGE_RECEIPTS.get(receipt_id)
        return copy.deepcopy(row) if row else None


def list_purge_receipts() -> list[dict[str, Any]]:
    """Return all in-memory purge receipts, in insertion order."""
    with _lock:
        return [copy.deepcopy(r) for r in _PURGE_RECEIPTS.values()]


def classify_retention(
    event_like: dict[str, Any] | CommunicationEvent,
) -> RetentionDecision:
    """Classify lifecycle retention for a communication.

    Heuristics keyed by ``retention_class`` (operational_30d, inbound_7d,
    approval_ttl, research_365d, …). Legal hold forces HOLD and blocks deletes.
    """
    ev = _as_event_dict(event_like)
    event_id = str(ev.get("event_id") or "").strip()
    if not event_id:
        raise ValueError("event_id required to classify retention")

    retention_class = str(ev.get("retention_class") or "").strip() or "operational_30d"
    legal_hold = bool(ev.get("legal_hold", False))
    decided_at = _now()

    if legal_hold:
        return RetentionDecision(
            event_id=event_id,
            retention_class=retention_class,
            action=HOLD,
            content_ttl_seconds=None,
            metadata_ttl_seconds=None,
            embedding_ttl_seconds=None,
            attachment_ttl_seconds=None,
            legal_hold=True,
            reason="legal_hold: retention suspended; deletes blocked",
            decided_by=DECIDED_BY_DEFAULT,
            policy_version=POLICY_VERSION,
            decided_at=decided_at,
            expires_at=None,
            receipt={
                "schema": SCHEMA_VERSION,
                "source_retention_class": retention_class,
                "legal_hold": True,
                "content_hash": ev.get("content_hash"),
            },
        )

    heuristic = _CLASS_HEURISTICS.get(retention_class)
    if heuristic is None:
        parsed = _parse_ttl_from_class_name(retention_class)
        if parsed is not None:
            heuristic = (
                parsed,
                parsed * 3,
                parsed,
                parsed,
                DELETE_CONTENT_KEEP_TOMBSTONE,
                f"{retention_class}: parsed TTL heuristic",
            )
        else:
            heuristic = _DEFAULT_HEURISTIC

    content_ttl, metadata_ttl, embedding_ttl, attachment_ttl, action, reason = heuristic

    expires_at: datetime | None = None
    if content_ttl is not None and action in _PURGE_ACTIONS:
        expires_at = decided_at + timedelta(seconds=int(content_ttl))
    elif content_ttl is not None and action == KEEP:
        # KEEP with TTL: soft review horizon only; expiry pass does not purge KEEP.
        expires_at = decided_at + timedelta(seconds=int(content_ttl))

    # Explicit expires_at on the event overrides computed horizon when earlier.
    raw_expires = ev.get("expires_at")
    if raw_expires is not None:
        if isinstance(raw_expires, datetime):
            event_expires = raw_expires if raw_expires.tzinfo else raw_expires.replace(tzinfo=timezone.utc)
        else:
            try:
                event_expires = datetime.fromisoformat(str(raw_expires).replace("Z", "+00:00"))
            except ValueError:
                event_expires = None
        if event_expires is not None:
            if expires_at is None or event_expires < expires_at:
                expires_at = event_expires

    return RetentionDecision(
        event_id=event_id,
        retention_class=retention_class,
        action=action,
        content_ttl_seconds=content_ttl,
        metadata_ttl_seconds=metadata_ttl,
        embedding_ttl_seconds=embedding_ttl,
        attachment_ttl_seconds=attachment_ttl,
        legal_hold=False,
        reason=reason,
        decided_by=DECIDED_BY_DEFAULT,
        policy_version=POLICY_VERSION,
        decided_at=decided_at,
        expires_at=expires_at,
        receipt={
            "schema": SCHEMA_VERSION,
            "source_retention_class": retention_class,
            "message_class": ev.get("message_class"),
            "direction": ev.get("direction"),
            "content_hash": ev.get("content_hash"),
        },
    )


def _db_conn():
    """Best-effort connection; None when unavailable or librarian tables missing."""
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
                     'communication_retention_decisions',
                     'communication_tombstones',
                     'communication_knowledge_candidates'
                 )
                """
            )
            n = cur.fetchone()[0]
        if int(n) < 3:
            return None
    except Exception:
        return None
    return conn


def apply_retention_decision(
    decision: RetentionDecision | None = None,
    *,
    event_like: dict[str, Any] | CommunicationEvent | None = None,
) -> RetentionDecision:
    """Persist a RetentionDecision (memory + optional DB).

    Pass an existing ``decision`` or ``event_like`` to classify then store.
    """
    if decision is None:
        if event_like is None:
            raise ValueError("decision or event_like required")
        decision = classify_retention(event_like)
    decision.mint_identity()

    if decision.action == HOLD or decision.legal_hold:
        record_purge_receipt(
            decision_id=decision.decision_id,
            action=decision.action,
            retention_class=decision.retention_class,
            event_ids=[decision.event_id],
            artifact_ids=[],
            content_hashes=_content_hashes_from_receipt(decision.receipt),
            tombstone=False,
            decided_by=decision.decided_by,
            policy_version=decision.policy_version,
            decided_at=decision.decided_at,
            dry_run=False,
            note="hold: retention suspended; deletes blocked",
        )

    conn = _db_conn()
    if conn is not None:
        try:
            return _apply_decision_db(conn, decision)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            # Fall through to memory.

    return _apply_decision_memory(decision)


def _apply_decision_memory(decision: RetentionDecision) -> RetentionDecision:
    row = decision.to_row()
    with _lock:
        _DECISIONS[decision.decision_id] = copy.deepcopy(row)
        _DECISIONS_BY_EVENT.setdefault(decision.event_id, [])
        if decision.decision_id not in _DECISIONS_BY_EVENT[decision.event_id]:
            _DECISIONS_BY_EVENT[decision.event_id].append(decision.decision_id)
    decision.persisted = "memory"
    return decision


def _apply_decision_db(conn: Any, decision: RetentionDecision) -> RetentionDecision:
    row = decision.to_row()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO communication_retention_decisions (
                decision_id, event_id, retention_class,
                content_ttl_seconds, metadata_ttl_seconds,
                embedding_ttl_seconds, attachment_ttl_seconds,
                legal_hold, reason, decided_by, policy_version,
                decided_at, expires_at, action, receipt
            ) VALUES (
                %(decision_id)s, %(event_id)s, %(retention_class)s,
                %(content_ttl_seconds)s, %(metadata_ttl_seconds)s,
                %(embedding_ttl_seconds)s, %(attachment_ttl_seconds)s,
                %(legal_hold)s, %(reason)s, %(decided_by)s, %(policy_version)s,
                %(decided_at)s, %(expires_at)s, %(action)s, %(receipt)s::jsonb
            )
            ON CONFLICT (decision_id) DO UPDATE SET
                retention_class = EXCLUDED.retention_class,
                content_ttl_seconds = EXCLUDED.content_ttl_seconds,
                metadata_ttl_seconds = EXCLUDED.metadata_ttl_seconds,
                embedding_ttl_seconds = EXCLUDED.embedding_ttl_seconds,
                attachment_ttl_seconds = EXCLUDED.attachment_ttl_seconds,
                legal_hold = EXCLUDED.legal_hold,
                reason = EXCLUDED.reason,
                decided_by = EXCLUDED.decided_by,
                policy_version = EXCLUDED.policy_version,
                decided_at = EXCLUDED.decided_at,
                expires_at = EXCLUDED.expires_at,
                action = EXCLUDED.action,
                receipt = EXCLUDED.receipt
            """,
            {
                **row,
                "receipt": json.dumps(row.get("receipt") or {}, default=str),
            },
        )
    conn.commit()
    decision.persisted = "db"
    # Mirror in memory for expiry pass visibility in mixed mode.
    _apply_decision_memory(decision)
    decision.persisted = "db"
    return decision


def get_retention_decision(decision_id: str) -> dict[str, Any] | None:
    with _lock:
        row = _DECISIONS.get(decision_id)
        return copy.deepcopy(row) if row else None


def list_decisions_for_event(event_id: str) -> list[dict[str, Any]]:
    with _lock:
        ids = list(_DECISIONS_BY_EVENT.get(event_id, []))
        return [copy.deepcopy(_DECISIONS[i]) for i in ids if i in _DECISIONS]


def _write_tombstone_memory(
    *,
    event_id: str,
    action: str,
    content_hash: str | None,
    decided_by: str | None,
    note: str | None,
    purged_at: datetime,
) -> dict[str, Any]:
    row = {
        "event_id": event_id,
        "purged_at": purged_at,
        "action": action,
        "content_hash": content_hash,
        "decided_by": decided_by,
        "note": note,
    }
    with _lock:
        _TOMBSTONES[event_id] = copy.deepcopy(row)
    return row


def _execute_one(
    decision_row: dict[str, Any],
    *,
    now: datetime,
    dry_run: bool,
) -> dict[str, Any]:
    """Apply one expired decision. Legal hold always blocks purge.

    Every branch records a PurgeReceipt@v1 — including the dry-run
    "would-delete" path, which records intent without deleting.
    """
    event_id = decision_row["event_id"]
    action = decision_row["action"]
    retention_class = decision_row.get("retention_class") or "unknown"
    legal_hold = bool(decision_row.get("legal_hold", False))
    decided_by = decision_row.get("decided_by") or DECIDED_BY_DEFAULT
    policy_version = decision_row.get("policy_version") or POLICY_VERSION
    decided_at = decision_row.get("decided_at")
    content_hashes = _content_hashes_from_receipt(decision_row.get("receipt"))
    decision_id = decision_row.get("decision_id")

    result: dict[str, Any] = {
        "decision_id": decision_id,
        "event_id": event_id,
        "action": action,
        "legal_hold": legal_hold,
        "dry_run": dry_run,
        "executed": False,
        "blocked": False,
        "reason": None,
    }

    if legal_hold or action == HOLD:
        result["blocked"] = True
        result["reason"] = "legal_hold_blocks_delete"
        record_purge_receipt(
            decision_id=decision_id,
            action=HOLD,
            retention_class=retention_class,
            event_ids=[event_id],
            content_hashes=content_hashes,
            tombstone=False,
            decided_by=decided_by,
            policy_version=policy_version,
            decided_at=decided_at,
            dry_run=dry_run,
            note="legal_hold_blocks_delete",
        )
        return result

    if action == KEEP:
        result["blocked"] = True
        result["reason"] = "keep_not_executable"
        record_purge_receipt(
            decision_id=decision_id,
            action=KEEP,
            retention_class=retention_class,
            event_ids=[event_id],
            content_hashes=content_hashes,
            tombstone=False,
            decided_by=decided_by,
            policy_version=policy_version,
            decided_at=decided_at,
            dry_run=dry_run,
            note="keep_not_executable",
        )
        return result

    if action not in _PURGE_ACTIONS:
        result["blocked"] = True
        result["reason"] = f"action_not_executable:{action}"
        record_purge_receipt(
            decision_id=decision_id,
            action=action,
            retention_class=retention_class,
            event_ids=[event_id],
            content_hashes=content_hashes,
            tombstone=False,
            decided_by=decided_by,
            policy_version=policy_version,
            decided_at=decided_at,
            dry_run=dry_run,
            note=f"action_not_executable:{action}",
        )
        return result

    if dry_run:
        result["reason"] = "dry_run"
        record_purge_receipt(
            decision_id=decision_id,
            action=action,
            retention_class=retention_class,
            event_ids=[event_id],
            content_hashes=content_hashes,
            tombstone=False,
            decided_by=decided_by,
            policy_version=policy_version,
            decided_at=decided_at,
            dry_run=True,
            note="would-delete (dry-run)",
        )
        return result

    note = f"expiry_pass action={action} at {now.isoformat()}"
    _write_tombstone_memory(
        event_id=event_id,
        action=action,
        content_hash=(decision_row.get("receipt") or {}).get("content_hash")
        if isinstance(decision_row.get("receipt"), dict)
        else None,
        decided_by=decision_row.get("decided_by") or DECIDED_BY_DEFAULT,
        note=note,
        purged_at=now,
    )

    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO communication_tombstones (
                        event_id, purged_at, action, content_hash, decided_by, note
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO UPDATE SET
                        purged_at = EXCLUDED.purged_at,
                        action = EXCLUDED.action,
                        content_hash = EXCLUDED.content_hash,
                        decided_by = EXCLUDED.decided_by,
                        note = EXCLUDED.note
                    """,
                    (
                        event_id,
                        now,
                        action,
                        None,
                        decision_row.get("decided_by") or DECIDED_BY_DEFAULT,
                        note,
                    ),
                )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    result["executed"] = True
    result["reason"] = "tombstone_written"
    record_purge_receipt(
        decision_id=decision_id,
        action=action,
        retention_class=retention_class,
        event_ids=[event_id],
        content_hashes=content_hashes,
        tombstone=True,
        decided_by=decided_by,
        policy_version=policy_version,
        decided_at=decided_at,
        dry_run=False,
        note=note,
    )
    return result


def execute_expiry_pass(*, now: datetime | None = None, dry_run: bool = True) -> dict[str, Any]:
    """Find expired non-hold retention rows and optionally execute purge actions.

    ``dry_run`` defaults to True — no tombstones / deletes unless explicitly False.
    Legal hold always blocks delete regardless of dry_run.
    """
    when = now or _now()
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    candidates: list[dict[str, Any]] = []
    with _lock:
        for row in _DECISIONS.values():
            expires_at = row.get("expires_at")
            if expires_at is None:
                continue
            if isinstance(expires_at, str):
                try:
                    expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                except ValueError:
                    continue
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at > when:
                continue
            if bool(row.get("legal_hold", False)):
                continue
            if row.get("action") == HOLD:
                continue
            candidates.append(copy.deepcopy(row))

    results = [
        _execute_one(row, now=when, dry_run=dry_run) for row in candidates
    ]
    executed = sum(1 for r in results if r.get("executed"))
    blocked = sum(1 for r in results if r.get("blocked"))
    would_execute = sum(
        1
        for r in results
        if not r.get("blocked") and not r.get("executed") and r.get("reason") == "dry_run"
    )
    return {
        "dry_run": dry_run,
        "now": when.isoformat(),
        "examined": len(candidates),
        "executed": executed,
        "blocked": blocked,
        "would_execute": would_execute,
        "results": results,
    }


def propose_knowledge_candidate(
    event_id: str,
    assertion_text: str,
    *,
    owner: str,
    evidence_refs: list[Any] | None = None,
    review_path: str | None = None,
) -> dict[str, Any]:
    """Create a knowledge CANDIDATE only.

    Refuses when owner or provenance (evidence_refs) is missing.
    Never auto-promotes to ACCEPTED.
    """
    eid = (event_id or "").strip()
    if not eid:
        raise ValueError("event_id required for knowledge candidate")
    text = (assertion_text or "").strip()
    if not text:
        raise ValueError("assertion_text required")
    own = (owner or "").strip()
    if not own:
        raise ValueError("owner required — knowledge promotion is not automatic")
    refs = evidence_refs if evidence_refs is not None else []
    if not refs:
        raise ValueError("evidence_refs (provenance) required — refuse without provenance")

    candidate_id = f"kc_{new_event_id()}"
    created_at = _now()
    row = {
        "candidate_id": candidate_id,
        "event_id": eid,
        "status": CANDIDATE,
        "assertion_text": text,
        "evidence_refs": list(refs),
        "owner": own,
        "review_path": review_path,
        "created_at": created_at,
        "decided_at": None,
        "persisted": "memory",
    }

    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO communication_knowledge_candidates (
                        candidate_id, event_id, status, assertion_text,
                        evidence_refs, owner, review_path, created_at, decided_at
                    ) VALUES (
                        %s, %s, %s, %s, %s::jsonb, %s, %s, %s, NULL
                    )
                    """,
                    (
                        candidate_id,
                        eid,
                        CANDIDATE,
                        text,
                        json.dumps(list(refs), default=str),
                        own,
                        review_path,
                        created_at,
                    ),
                )
            conn.commit()
            row["persisted"] = "db"
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    with _lock:
        _CANDIDATES[candidate_id] = copy.deepcopy(row)
    return copy.deepcopy(row)


def decide_knowledge_candidate(
    candidate_id: str,
    status: str,
    *,
    reviewer: str,
) -> dict[str, Any]:
    """Explicit review decision for a knowledge candidate.

    Allowed statuses: ACCEPTED, REJECTED, DISPUTED, SUPERSEDED, RETRACTED.
    Does not auto-accept; requires reviewer identity.
    """
    cid = (candidate_id or "").strip()
    if not cid:
        raise ValueError("candidate_id required")
    rev = (reviewer or "").strip()
    if not rev:
        raise ValueError("reviewer required")
    st = (status or "").strip().upper()
    if st not in _DECIDABLE_STATUSES:
        raise ValueError(
            f"status_invalid:{status}; propose creates CANDIDATE; "
            f"decide requires one of {sorted(_DECIDABLE_STATUSES)}"
        )

    with _lock:
        row = _CANDIDATES.get(cid)
        if row is None:
            raise KeyError(f"unknown candidate_id:{cid}")
        if row.get("status") != CANDIDATE:
            raise ValueError(
                f"candidate not decidable from status={row.get('status')!r}; "
                "only CANDIDATE may be decided"
            )
        updated = copy.deepcopy(row)
        updated["status"] = st
        updated["decided_at"] = _now()
        updated["reviewer"] = rev
        _CANDIDATES[cid] = updated

    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE communication_knowledge_candidates
                       SET status = %s, decided_at = %s
                     WHERE candidate_id = %s
                    """,
                    (st, updated["decided_at"], cid),
                )
            conn.commit()
            updated["persisted"] = "db"
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    return copy.deepcopy(updated)


def get_knowledge_candidate(candidate_id: str) -> dict[str, Any] | None:
    with _lock:
        row = _CANDIDATES.get(candidate_id)
        return copy.deepcopy(row) if row else None


def get_tombstone(event_id: str) -> dict[str, Any] | None:
    with _lock:
        row = _TOMBSTONES.get(event_id)
        return copy.deepcopy(row) if row else None


def memory_librarian_snapshot() -> dict[str, Any]:
    """Test helper: copy of in-memory librarian state."""
    with _lock:
        return {
            "decisions": {k: copy.deepcopy(v) for k, v in _DECISIONS.items()},
            "tombstones": {k: copy.deepcopy(v) for k, v in _TOMBSTONES.items()},
            "candidates": {k: copy.deepcopy(v) for k, v in _CANDIDATES.items()},
            "purge_receipts": {k: copy.deepcopy(v) for k, v in _PURGE_RECEIPTS.items()},
        }


def reset_librarian_memory() -> None:
    """Test helper: clear in-process librarian stores."""
    with _lock:
        _DECISIONS.clear()
        _DECISIONS_BY_EVENT.clear()
        _TOMBSTONES.clear()
        _CANDIDATES.clear()
        _PURGE_RECEIPTS.clear()

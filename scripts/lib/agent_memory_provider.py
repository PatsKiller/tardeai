"""agent_memory_provider.py — MemoryProvider protocol + safe providers (Phase 4).

READ_ONLY_ADVISORY. Memory is NON_AUTHORITATIVE_CONTEXT: it can never mutate
broker/order/stop/2FA/risk-policy state and can never outrank canonical financial
truth. This module defines the narrow memory-provider contract that the rest of
the Agent Intelligence Foundation programs against, plus two concrete providers:

  * NullMemoryProvider       — always NOT_CONFIGURED; a safe no-op default.
  * LocalTestMemoryProvider  — deterministic, in-memory store used by tests and
    as the shadow-pilot reference implementation.

No network, no secrets, no live side effects. Deterministic only.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

from scripts.lib.agent_context_envelope import (
    RETRIEVAL_EMPTY,
    RETRIEVAL_NOT_CONFIGURED,
    RETRIEVAL_OK,
    canonical_json,
    sha256_hex,
)
from scripts.lib.agent_memory_governance import (
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    STATUS_DISPUTED,
    STATUS_EXPIRED,
    STATUS_RETRACTED,
    STATUS_SUPERSEDED,
    admit_status,
    is_forbidden_authoritative,
)

PROVIDER_STATUS_OK = "OK"
PROVIDER_STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"

DEFAULT_TOP_K = 8
DEFAULT_BUDGET_TOKENS = 1500

# Memory is always context, never truth.
MEMORY_AUTHORITY = "NON_AUTHORITATIVE_CONTEXT"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: Any) -> float:
    """Parse an ISO-8601 timestamp to epoch seconds; 0.0 on failure/absence."""
    if value is None or value == "":
        return 0.0
    try:
        s = str(value)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _estimate_tokens(record: dict[str, Any]) -> int:
    """Cheap, deterministic token estimate (chars // 4), used only for bounding."""
    try:
        return max(1, len(json.dumps(record, sort_keys=True, default=str)) // 4)
    except (TypeError, ValueError):
        return 1


def _bound(records: list[dict[str, Any]], top_k: int, budget_tokens: int) -> list[dict[str, Any]]:
    """Bound a ranked list by count (top_k) and an approximate token budget."""
    out: list[dict[str, Any]] = []
    used = 0
    for r in records[:top_k]:
        t = _estimate_tokens(r)
        if budget_tokens and used + t > budget_tokens and out:
            break
        out.append(r)
        used += t
    return out


def _content_digest(subject: Any, content: Any) -> str:
    return sha256_hex(canonical_json({"subject": subject, "content": content}), 32)


# ── Provider protocol ──────────────────────────────────────────────────────


@runtime_checkable
class MemoryProvider(Protocol):
    """Duck-typed contract every memory provider must satisfy.

    All methods fail soft: they return empty/None/False rather than raise, so a
    missing or broken provider never breaks a wake.
    """

    name: str

    def search(
        self,
        query: Any = None,
        scope: Any = None,
        symbols: Optional[list[str]] = None,
        plan_id: Optional[str] = None,
        top_k: int = DEFAULT_TOP_K,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    ) -> dict[str, Any]:
        ...

    def add_candidate(self, record: dict[str, Any]) -> Optional[str]:
        ...

    def get(self, memory_id: str) -> Optional[dict[str, Any]]:
        ...

    def dispute(self, memory_id: str, reason: str) -> bool:
        ...

    def expire(self, memory_id: str) -> bool:
        ...

    def health(self) -> dict[str, Any]:
        ...


# ── NullMemoryProvider — safe no-op default ───────────────────────────────


class NullMemoryProvider:
    """Always NOT_CONFIGURED. Never raises. Never stores anything."""

    name = "NullMemoryProvider"

    def health(self) -> dict[str, Any]:
        return {"status": PROVIDER_STATUS_NOT_CONFIGURED, "provider": self.name}

    def search(
        self,
        query: Any = None,
        scope: Any = None,
        symbols: Optional[list[str]] = None,
        plan_id: Optional[str] = None,
        top_k: int = DEFAULT_TOP_K,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    ) -> dict[str, Any]:
        return {
            "query": query,
            "scope": scope,
            "symbols": list(symbols or []),
            "plan_id": plan_id,
            "records": [],
            "supporting": [],
            "counter_memory": [],
            "conflicts": [],
            "memory_ids": [],
            "retrieval_status": RETRIEVAL_NOT_CONFIGURED,
            "provider": self.name,
        }

    def add_candidate(self, record: dict[str, Any]) -> Optional[str]:
        return None

    def get(self, memory_id: str) -> Optional[dict[str, Any]]:
        return None

    def dispute(self, memory_id: str, reason: str) -> bool:
        return False

    def expire(self, memory_id: str) -> bool:
        return False


# ── LocalTestMemoryProvider — deterministic in-memory store ───────────────


def _is_live(record: dict[str, Any]) -> bool:
    if record.get("status") in ("EXPIRED", "RETRACTED", "SUPERSEDED"):
        return False
    exp = record.get("expires_at")
    if exp:
        ts = _parse_ts(exp)
        if ts > 0 and ts < time.time():
            return False
    return True


# Lifecycle downgrades (DISPUTED/EXPIRED/RETRACTED/SUPERSEDED) are non-active and
# may only be reached through governed transitions (dispute/expire/supersedes).
_LIFECYCLE_STATUSES = frozenset(
    {STATUS_DISPUTED, STATUS_EXPIRED, STATUS_RETRACTED, STATUS_SUPERSEDED}
)


def _forced_status(caller_status: Any, canonical_status: str) -> str:
    """Return the status a record may be stored under.

    Admission status comes from ``admit_status()`` (canonical), not from the
    caller:

      * lifecycle downgrades (DISPUTED/EXPIRED/RETRACTED/SUPERSEDED) are
        preserved — they are non-active and are only reached via governed
        transitions (``dispute``/``expire``/``supersedes``) or by loading a
        historical record that already carries them, never as an escalation;
      * everything else is normalized to the canonical result. A caller can
        never elevate above ``admit_status()`` (an inferred preference supplied
        as ACTIVE becomes CANDIDATE), and unknown/garbage/lowercase/whitespace
        statuses (e.g. "BOGUS", "active", " active ", "REJECT") are NOT
        persisted — they are replaced by the canonical status.
    """
    if caller_status in _LIFECYCLE_STATUSES:
        return caller_status
    return canonical_status


def _retrievable(record: dict[str, Any]) -> bool:
    """Defense-in-depth: a malformed/historical record must never surface as
    supporting context, even if it somehow reached storage."""
    authority = record.get("authority_class")
    if authority is not None and authority != MEMORY_AUTHORITY:
        return False
    if not (record.get("source_event_ids") or record.get("source_refs")):
        return False
    if is_forbidden_authoritative(record.get("subject")):
        return False
    return True


def _scope_matches(record: dict[str, Any], requested: Any) -> bool:
    """True when a record is visible under the requested scope.

    ``None``/empty means "no restriction". A record whose ``scope`` carries
    ``shared_scope=True`` is visible across operators. Otherwise every requested
    constraint key must either match the record's value or be unconstrained by
    the record (missing key == shared on that dimension). This enforces
    cross-operator/cross-agent isolation so a specialist or account cannot read
    another scope's memory.
    """
    if requested is None:
        return True
    rec_scope = record.get("scope") or {}
    if isinstance(rec_scope, str):
        rec_scope = {"operator_id": rec_scope}
    if not isinstance(rec_scope, dict):
        rec_scope = {}
    if isinstance(requested, str):
        requested = {"operator_id": requested}
    if not isinstance(requested, dict) or not requested:
        return True
    if rec_scope.get("shared_scope") is True:
        return True
    for key, want in requested.items():
        got = rec_scope.get(key)
        if got is None:
            continue  # record does not constrain this dimension -> shared
        if got != want:
            return False
    return True


def _plan_matches(record: dict[str, Any], plan_id: str) -> bool:
    """True when a record is relevant to the requested plan.

    A record with an empty ``plan_ids`` is unconstrained (general context) and
    matches any plan; otherwise the requested ``plan_id`` must be present.
    """
    plan_ids = record.get("plan_ids") or []
    if not plan_ids:
        return True
    return plan_id in plan_ids


def _score(record: dict[str, Any], query: Any, symbols: Optional[list[str]]) -> float:
    """Simple relevance: substring hits (weight 2 each) + confidence (0..1)."""
    hay = " ".join(
        [str(record.get("subject") or ""), str(record.get("content") or "")]
        + [str(s) for s in (record.get("symbols") or [])]
    ).lower()
    score = 0.0
    terms: list[str] = []
    if query is not None:
        if isinstance(query, dict):
            qv = query.get("query") or query.get("text") or ""
            terms += [t for t in str(qv).lower().split() if len(t) >= 2]
        else:
            terms += [t for t in str(query).lower().split() if len(t) >= 2]
    for s in symbols or []:
        terms.append(str(s).lower())
    for t in terms:
        if t and t in hay:
            score += 2.0
    try:
        score += float(record.get("confidence") or 0.0)
    except (TypeError, ValueError):
        pass
    return score


def _recency(record: dict[str, Any]) -> float:
    return max(_parse_ts(record.get("valid_from")), _parse_ts(record.get("created_at")))


class LocalTestMemoryProvider:
    """Deterministic in-memory provider.

    Relevance is a fixed formula (substring hits + confidence), ties broken by
    recency then memory_id, so search output is reproducible. Returns both
    supporting records and counter-memory (records with a non-empty
    ``contradicts`` list or ``DISPUTED`` status).
    """

    name = "LocalTestMemoryProvider"

    def __init__(self, records: Optional[list[dict[str, Any]]] = None) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._by_digest: dict[str, str] = {}
        for r in records or []:
            self.add_candidate(r)

    def health(self) -> dict[str, Any]:
        return {
            "status": PROVIDER_STATUS_OK,
            "provider": self.name,
            "configured": True,
            "memory_count": len(self._store),
        }

    def add_candidate(self, record: dict[str, Any]) -> Optional[str]:
        if not isinstance(record, dict):
            return None
        # Governed admission: no retrievable memory without provenance, and no
        # memory about forbidden-authoritative subjects. This is NOT a bypass
        # around MemoryRecord/admission validation — the canonical governance
        # predicates are reused here so there is exactly ONE admission policy.
        if not (record.get("source_event_ids") or record.get("source_refs")):
            return None
        if is_forbidden_authoritative(record.get("subject")):
            return None
        rec = dict(record)
        digest = rec.get("content_digest")
        if not digest:
            digest = _content_digest(rec.get("subject"), rec.get("content"))
            rec["content_digest"] = digest
        memory_id = rec.get("memory_id")
        if not memory_id:
            memory_id = "mem_" + digest
            rec["memory_id"] = memory_id
        rec.setdefault("memory_version", "1.0")
        # Governed admission: privilege fields are FORCED, never merely defaulted.
        # Caller input cannot elevate authority or status beyond the canonical
        # admission rule (the ONE admission policy lives in agent_memory_governance).
        canonical_status = admit_status(
            rec.get("memory_type"),
            subject=rec.get("subject"),
            provenance_ok=True,
        )
        rec["status"] = _forced_status(rec.get("status"), canonical_status)
        rec["authority_class"] = MEMORY_AUTHORITY
        rec.setdefault("confidence", 0.5)
        rec.setdefault("created_at", _now_iso())
        if digest in self._by_digest:
            # Coalesce duplicates: same content digest -> same memory id.
            existing_id = self._by_digest[digest]
            existing = self._store[existing_id]
            existing["last_confirmed_at"] = (
                rec.get("valid_from") or rec.get("created_at") or _now_iso()
            )
            return existing_id
        self._store[memory_id] = rec
        self._by_digest[digest] = memory_id
        for sid in rec.get("supersedes") or []:
            if sid in self._store and sid != memory_id:
                self._store[sid]["status"] = "SUPERSEDED"
        return memory_id

    def get(self, memory_id: str) -> Optional[dict[str, Any]]:
        rec = self._store.get(memory_id)
        return dict(rec) if rec is not None else None

    def dispute(self, memory_id: str, reason: str) -> bool:
        rec = self._store.get(memory_id)
        if rec is None:
            return False
        rec["status"] = "DISPUTED"
        rec["dispute_reason"] = reason
        return True

    def expire(self, memory_id: str) -> bool:
        rec = self._store.get(memory_id)
        if rec is None:
            return False
        rec["status"] = "EXPIRED"
        rec.setdefault("expires_at", _now_iso())
        return True

    def search(
        self,
        query: Any = None,
        scope: Any = None,
        symbols: Optional[list[str]] = None,
        plan_id: Optional[str] = None,
        top_k: int = DEFAULT_TOP_K,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    ) -> dict[str, Any]:
        top_k = int(top_k or DEFAULT_TOP_K)
        live = [r for r in self._store.values() if _is_live(r) and _retrievable(r)]
        if scope is not None:
            live = [r for r in live if _scope_matches(r, scope)]
        if plan_id is not None:
            live = [r for r in live if _plan_matches(r, plan_id)]
        ranked = sorted(
            live,
            key=lambda r: (-_score(r, query, symbols), -_recency(r), str(r.get("memory_id", ""))),
        )
        supporting: list[dict[str, Any]] = []
        counter: list[dict[str, Any]] = []
        for r in ranked:
            if r.get("contradicts") or r.get("status") == "DISPUTED":
                counter.append(r)
            else:
                supporting.append(r)
        supporting = _bound(supporting, top_k, budget_tokens)
        counter = _bound(counter, top_k, budget_tokens)
        combined = supporting + counter
        conflicts = [
            {"memory_id": r.get("memory_id"), "reason": r.get("dispute_reason")}
            for r in counter
            if r.get("status") == "DISPUTED"
        ]
        return {
            "query": query,
            "scope": scope,
            "symbols": list(symbols or []),
            "records": supporting,
            "supporting": supporting,
            "counter_memory": counter,
            "conflicts": conflicts,
            "memory_ids": [r.get("memory_id") for r in combined],
            "retrieval_status": RETRIEVAL_OK if combined else RETRIEVAL_EMPTY,
            "provider": self.name,
        }

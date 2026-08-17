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
        top_k: int = DEFAULT_TOP_K,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    ) -> dict[str, Any]:
        return {
            "query": query,
            "scope": scope,
            "symbols": list(symbols or []),
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
        rec.setdefault("status", "CANDIDATE")
        rec.setdefault("authority_class", MEMORY_AUTHORITY)
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
        top_k: int = DEFAULT_TOP_K,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    ) -> dict[str, Any]:
        top_k = int(top_k or DEFAULT_TOP_K)
        live = [r for r in self._store.values() if _is_live(r)]
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

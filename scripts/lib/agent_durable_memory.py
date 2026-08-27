"""Durable JSONL MemoryProvider — local, shared, CURRENT-flip safe.

Backend selection (Program 3):
  A. Postgres 17 is live but pgvector is NOT installed — no new DB product.
  B. Mem0 package is NOT installed and must not be forced.
  C. Reuse Trade AI shared JSONL persistence under data/cio (same root as
     reflection / lessons / promotions). data/cio is a CURRENT symlink to
     the shared runtime tree, so records survive release flips.

READ_ONLY_ADVISORY. Memory is NON_AUTHORITATIVE_CONTEXT. Fail-soft on search;
fail-closed on admission.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.agent_context_envelope import RETRIEVAL_EMPTY, RETRIEVAL_OK
from scripts.lib.agent_memory_governance import (
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    STATUS_DISPUTED,
    STATUS_EXPIRED,
    STATUS_RETRACTED,
    STATUS_SUPERSEDED,
    _contains_secret,
    admit_status,
    is_forbidden_authoritative,
)
from scripts.lib.agent_memory_provider import (
    DEFAULT_BUDGET_TOKENS,
    DEFAULT_TOP_K,
    MEMORY_AUTHORITY,
    PROVIDER_STATUS_OK,
    LocalTestMemoryProvider,
    _bound,
    _content_digest,
    _forced_status,
    _is_live,
    _now_iso,
    _plan_matches,
    _recency,
    _retrievable,
    _scope_matches,
    _score,
)

STATUS_ADMITTED = "ADMITTED"

TTL_DAYS = {
    "OPERATOR_EXPLICIT_PREFERENCE": 365,
    "OPERATOR_INFERRED_PREFERENCE": 180,
    "AGENT_COMMITMENT": 180,
    "CASE_SUMMARY": 365,
    "RESEARCH_REFERENCE": 90,
    "EPISODIC": 30,
    "PROCEDURAL_HINT": 14,
    "operator preference": 365,
    "research observation": 90,
    "lesson context": 180,
    "case outcome": 365,
    "temporary hypothesis": 14,
    "agent observation": 30,
}

DISPLAY_STATUS = {
    STATUS_ACTIVE: STATUS_ADMITTED,
    STATUS_ADMITTED: STATUS_ADMITTED,
    STATUS_CANDIDATE: STATUS_CANDIDATE,
    STATUS_DISPUTED: STATUS_DISPUTED,
    STATUS_SUPERSEDED: STATUS_SUPERSEDED,
    STATUS_EXPIRED: STATUS_EXPIRED,
    STATUS_RETRACTED: STATUS_RETRACTED,
}


def default_store_path(root: Path | str | None = None) -> Path:
    """Resolve the durable memory JSONL.

    Precedence (most explicit wins):
      1. explicit root argument
      2. TRADEAI_CIO_DIR
      3. TRADEAI_ROOT / MATURITY_CONTROL_ROOT  (test isolation)
      4. cwd data/cio if present (live worker from rebuild tree)
      5. resolve_root / module tree
    """
    if root:
        return Path(root) / "data" / "cio" / "aif_memory.jsonl"
    cio_env = os.environ.get("TRADEAI_CIO_DIR")
    if cio_env:
        return Path(cio_env) / "aif_memory.jsonl"
    env = os.environ.get("TRADEAI_ROOT") or os.environ.get("MATURITY_CONTROL_ROOT")
    if env:
        return Path(env) / "data" / "cio" / "aif_memory.jsonl"
    cwd_cio = Path("data/cio")
    if cwd_cio.exists():
        return (cwd_cio / "aif_memory.jsonl").resolve()
    try:
        from scripts.lib.maturity_control.store import resolve_root
        base = resolve_root()
    except Exception:
        base = Path(__file__).resolve().parents[2]
    return base / "data" / "cio" / "aif_memory.jsonl"


def default_ttl(memory_type: str | None) -> datetime:
    days = TTL_DAYS.get(str(memory_type or ""), 90)
    return datetime.now(timezone.utc) + timedelta(days=days)


def display_status(status: str | None) -> str:
    return DISPLAY_STATUS.get(str(status or ""), STATUS_CANDIDATE)


def _resolve_subject_guids(symbols: Any) -> tuple[list[str], list[str]]:
    """Resolve a memory's symbols against the durable entity registry.

    Cognitive memory was anchored on ticker STRINGS: 441 live records carried
    `symbols`, none carried a `subject_guid`, while a registry of 5,000+ entities
    sat beside them. A ticker is an alias -- it is reassigned after a delisting,
    so two companies can collide on one memory key years apart, and a memory
    written before a symbol change becomes unfindable after it.

    Returns (guids, unresolved_symbols). Both are recorded: a symbol the registry
    does not know is named rather than dropped, so the gap stays measurable
    instead of looking like an entity with no memories.

    Read-only against the registry, and never mints an identity -- memory is not
    an identity authority. An unregistered symbol simply has no GUID yet.
    """
    guids: list[str] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    try:
        from scripts.lib.identity_registry import load_cached, lookup_symbol
        registry = load_cached()
    except Exception:
        return [], []          # registry unavailable: record nothing, claim nothing
    for raw in (symbols or []):
        sym = str(raw or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        try:
            entity = lookup_symbol(registry, sym)
        except Exception:
            entity = None
        guid = (entity or {}).get("subject_guid")
        if guid:
            guids.append(str(guid))
        else:
            unresolved.append(sym)
    return guids, unresolved


class DurableJsonlMemoryProvider(LocalTestMemoryProvider):
    """File-backed MemoryProvider with flock + atomic snapshot.

    Inherits ranking / scope / contradiction search from LocalTestMemoryProvider.
    Persistence lives on the shared data/cio root, never in a branch checkout.
    """

    name = "DurableJsonlMemoryProvider"

    def __init__(self, path: Path | str | None = None, records: Optional[list[dict[str, Any]]] = None) -> None:
        self.path = Path(path) if path else default_store_path()
        self.receipts_path = self.path.with_name("aif_memory_admissions.jsonl")
        self.retrievals_path = self.path.with_name("aif_memory_retrievals.jsonl")
        self.snapshot_path = self.path.with_name("aif_memory.json")
        super().__init__(records=None)
        self._load()
        for r in records or []:
            self.add_candidate(r)

    def _lock_path(self) -> Path:
        p = self.path.with_suffix(self.path.suffix + ".lock")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch(exist_ok=True)
        return p

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict) or not rec.get("memory_id"):
                continue
            mid = rec["memory_id"]
            self._store[mid] = rec
            digest = rec.get("content_digest")
            if digest:
                self._by_digest[digest] = mid

    def _persist_record(self, rec: dict[str, Any]) -> None:
        if _contains_secret(rec.get("subject")) or _contains_secret(rec.get("content")):
            rec["status"] = STATUS_RETRACTED
            rec["retraction_reason"] = "persistence_secret_scan"
            # Do not write secret-shaped subject/content to durable storage.
            rec = dict(rec)
            rec["subject"] = "[REDACTED]"
            rec["content"] = "[REDACTED]"
        rec.setdefault("schema_version", rec.get("memory_version") or "1.0")
        rec.setdefault("content_hash", rec.get("content_digest"))
        rec.setdefault("as_of", rec.get("valid_from") or rec.get("created_at"))
        rec.setdefault("authority_class", MEMORY_AUTHORITY)

        # Anchor the memory on the durable spine. Every durable write passes
        # through here, so resolution happens once rather than in each producer.
        # `subject_guid` is set only when the memory is about exactly ONE entity;
        # a portfolio-wide observation has no single subject, and inventing one
        # would manufacture a false join.
        if not rec.get("subject_guid") and not rec.get("subject_guids"):
            guids, unresolved = _resolve_subject_guids(rec.get("symbols"))
            if guids:
                rec["subject_guids"] = guids
                if len(guids) == 1 and not unresolved:
                    rec["subject_guid"] = guids[0]
            if unresolved:
                rec["unresolved_symbols"] = unresolved
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(rec, sort_keys=True, default=str) + "\n"
        with self._lock_path().open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
            snap = {
                "at": _now_iso(),
                "provider": self.name,
                "count": len(self._store),
                "records": list(self._store.values()),
            }
            tmp = self.snapshot_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, self.snapshot_path)
            fcntl.flock(lock, fcntl.LOCK_UN)

    def _append_receipt(self, path: Path, rec: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")

    def health(self) -> dict[str, Any]:
        return {
            "status": PROVIDER_STATUS_OK,
            "provider": self.name,
            "backend": "jsonl+flock",
            "path": str(self.path),
            "configured": True,
            "durable": True,
            "local_controlled": True,
            "memory_count": len(self._store),
            "vector_backend": "none (lexical + confidence + recency)",
            "embedding_backend": "none",
        }

    def add_candidate(self, record: dict[str, Any]) -> Optional[str]:
        mid = super().add_candidate(record)
        if mid:
            stored = self._store.get(mid)
            if stored and not stored.get("expires_at"):
                stored["expires_at"] = default_ttl(stored.get("memory_type")).replace(microsecond=0).isoformat()
            if stored:
                self._persist_record(dict(stored))
            for sid in (stored or {}).get("supersedes") or []:
                old = self._store.get(sid)
                if old:
                    old["status"] = STATUS_SUPERSEDED
                    old["superseded_by"] = mid
                    self._persist_record(dict(old))
        return mid

    def dispute(self, memory_id: str, reason: str) -> bool:
        ok = super().dispute(memory_id, reason)
        if ok:
            self._persist_record(dict(self._store[memory_id]))
        return ok

    def expire(self, memory_id: str) -> bool:
        ok = super().expire(memory_id)
        if ok:
            self._persist_record(dict(self._store[memory_id]))
        return ok

    def retract(self, memory_id: str, reason: str = "operator") -> bool:
        rec = self._store.get(memory_id)
        if rec is None:
            return False
        rec["status"] = STATUS_RETRACTED
        rec["retraction_reason"] = reason
        self._persist_record(dict(rec))
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
        # Expire due records in-memory without destroying audit JSONL.
        now = time.time()
        for rec in self._store.values():
            exp = rec.get("expires_at")
            if rec.get("status") not in (STATUS_EXPIRED, STATUS_RETRACTED, STATUS_SUPERSEDED) and exp:
                from scripts.lib.agent_memory_provider import _parse_ts
                ts = _parse_ts(exp)
                if ts > 0 and ts < now:
                    rec["status"] = STATUS_EXPIRED
        result = super().search(
            query=query, scope=scope, symbols=symbols, plan_id=plan_id,
            top_k=top_k, budget_tokens=budget_tokens,
        )
        disputed = [r for r in self._store.values() if r.get("status") == STATUS_DISPUTED]
        superseded = [r for r in self._store.values() if r.get("status") == STATUS_SUPERSEDED]
        result["disputed"] = disputed[: int(top_k or DEFAULT_TOP_K)]
        result["superseded_context"] = superseded[: int(top_k or DEFAULT_TOP_K)]
        result["counter"] = result.get("counter_memory") or []
        result["authority_class"] = MEMORY_AUTHORITY
        self._append_receipt(self.retrievals_path, {
            "at": _now_iso(),
            "query": query,
            "symbols": list(symbols or []),
            "memory_ids": result.get("memory_ids") or [],
            "retrieval_status": result.get("retrieval_status"),
            "behavior_mode": os.environ.get("GOVERNED_MEMORY_ADVISORY_INFLUENCE", "OFF"),
            "memory_behavior_influence": os.environ.get("MEMORY_BEHAVIOR_INFLUENCE", "0"),
        })
        return result

    def counts(self) -> dict[str, int]:
        out = {k: 0 for k in (
            "CANDIDATE", "ADMITTED", "DISPUTED", "SUPERSEDED", "EXPIRED", "RETRACTED",
        )}
        for rec in self._store.values():
            key = display_status(rec.get("status"))
            out[key] = out.get(key, 0) + 1
        return out

    def tail_jsonl(self, path: Path, n: int = 20) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        try:
            lines = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in lines[-n:]:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
        return out


def get_durable_provider(root: Path | str | None = None) -> DurableJsonlMemoryProvider:
    return DurableJsonlMemoryProvider(path=default_store_path(root))

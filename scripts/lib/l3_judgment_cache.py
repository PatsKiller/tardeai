"""L3 judgment cache — subject-scoped, evidence-sensitive, provenance-preserving.

Cache key includes: subject, material question, normalized evidence IDs/revisions,
memory policy version, prompt version, model registry version.

Stale or changed evidence invalidates. Cache hits remain distinguishable from
fresh calls. No cross-subject reuse.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from scripts.lib.model_policy import L3ModelPolicy, cache_versions, default_l3_policy


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _norm_ids(ids: list[Any] | None) -> list[str]:
    return sorted({str(x) for x in (ids or []) if str(x).strip()})


def evidence_revision_token(grounded: Mapping[str, Any], memory_fact_ids: list[str]) -> str:
    """Digest of selected fact digests + research object ids (order-independent)."""
    wanted = set(memory_fact_ids)
    parts: list[str] = []
    for fact in grounded.get("memory_facts") or []:
        if not isinstance(fact, Mapping):
            continue
        mid = str(fact.get("memory_fact_id") or "")
        if mid not in wanted:
            continue
        parts.append(
            f"{mid}:{fact.get('fact_digest') or ''}:{fact.get('decay_weight')}:"
            f"{(fact.get('contradiction') or {}).get('state') if isinstance(fact.get('contradiction'), Mapping) else ''}"
        )
    research = grounded.get("research") or {}
    rids = _norm_ids(list(research.get("research_object_ids") or []))
    parts.append("research:" + ",".join(rids))
    blob = "|".join(sorted(parts))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_cache_key(
    *,
    subject_guid: str,
    material_question: str,
    grounded: Mapping[str, Any],
    memory_fact_ids: list[str],
    policy: L3ModelPolicy | None = None,
) -> str:
    policy = policy or default_l3_policy()
    vers = cache_versions(policy)
    payload = {
        "subject_guid": str(subject_guid),
        "material_question": str(material_question).strip(),
        "evidence_revision": evidence_revision_token(grounded, memory_fact_ids),
        "memory_fact_ids": _norm_ids(memory_fact_ids),
        **vers,
        "author_model": policy.author_model_id,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    # Embed subject prefix to make accidental cross-subject reuse obvious in audits.
    return f"l3cache:{subject_guid}:{digest}"


@dataclass
class CacheEntry:
    cache_key: str
    subject_guid: str
    created_at: str
    evidence_revision: str
    author_judgment: dict[str, Any]
    provider: str
    requested_model: str
    returned_model: str
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_key": self.cache_key,
            "subject_guid": self.subject_guid,
            "created_at": self.created_at,
            "evidence_revision": self.evidence_revision,
            "author_judgment": dict(self.author_judgment),
            "provider": self.provider,
            "requested_model": self.requested_model,
            "returned_model": self.returned_model,
            "provenance": dict(self.provenance),
        }


class JudgmentCache:
    """In-memory + optional JSONL durable cache. Subject-isolated."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, CacheEntry] = {}
        self._path = Path(path) if path else None
        if self._path and self._path.is_file():
            self._load()

    def _load(self) -> None:
        assert self._path is not None
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or not row.get("cache_key"):
                continue
            entry = CacheEntry(
                cache_key=str(row["cache_key"]),
                subject_guid=str(row.get("subject_guid") or ""),
                created_at=str(row.get("created_at") or ""),
                evidence_revision=str(row.get("evidence_revision") or ""),
                author_judgment=dict(row.get("author_judgment") or {}),
                provider=str(row.get("provider") or ""),
                requested_model=str(row.get("requested_model") or ""),
                returned_model=str(row.get("returned_model") or ""),
                provenance=dict(row.get("provenance") or {}),
            )
            self._entries[entry.cache_key] = entry

    def _append(self, entry: CacheEntry) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.to_dict(), sort_keys=True, default=str) + "\n")

    def get(
        self,
        cache_key: str,
        *,
        subject_guid: str,
        evidence_revision: str,
    ) -> CacheEntry | None:
        with self._lock:
            entry = self._entries.get(cache_key)
            if entry is None:
                return None
            # Cross-subject isolation — never return another subject's entry.
            if entry.subject_guid != subject_guid:
                return None
            if entry.evidence_revision != evidence_revision:
                # Stale / changed evidence → invalidate.
                self._entries.pop(cache_key, None)
                return None
            return entry

    def put(self, entry: CacheEntry) -> None:
        with self._lock:
            # Refuse cross-key subject spoofing.
            if not entry.subject_guid or f":{entry.subject_guid}:" not in f":{entry.cache_key}:":
                # cache_key format l3cache:{subject}:{digest}
                if not entry.cache_key.startswith(f"l3cache:{entry.subject_guid}:"):
                    raise ValueError("cross_subject_cache_refuse")
            self._entries[entry.cache_key] = entry
            self._append(entry)

    def invalidate_subject(self, subject_guid: str) -> int:
        with self._lock:
            keys = [k for k, e in self._entries.items() if e.subject_guid == subject_guid]
            for k in keys:
                self._entries.pop(k, None)
            return len(keys)

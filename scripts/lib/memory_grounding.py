"""Subject-grounded memory selection → GroundedJudgmentInput@v1 (L2 → L3).

Canonical read contract + selection without a 168h deletion cliff. Wrong-subject
facts have zero eligibility. Missing subject never falls back to global recall.
Stale-but-usable facts carry decay weights; contradictions stay visible.

This module is the Lane B library. Wiring into persistent_agent_wake.MemoryLoader
is Lane A via SFR — do not edit the central caller from this lane.

Authority: cognition only. Never writes portfolio/behavior fields.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from scripts.lib.memory_decay import (
    DecayPolicy,
    annotate_age,
    decay_weight,
    load_decay_policy,
    meets_min_influence,
)
from scripts.lib.memory_subject_resolver import (
    ResolverFailure,
    normalize_memory_id,
    normalize_subject_fields,
    row_subject_disposition,
    symbols_of,
)

SCHEMA_VERSION = "CanonicalMemoryFact@v1"
GROUNDED_INPUT_SCHEMA = "GroundedJudgmentInput@v1"
RESOLVER_VERSION = "memory_subject_resolver@v1"

# Non-age expiry / quarantine statuses from the durable store.
EXPIRED_STATUSES = frozenset({"EXPIRED", "RETRACTED"})
QUARANTINE_STATUSES = frozenset({"QUARANTINED", "DISPUTED"})

# Portfolio / behavior field names that must never be writable by this lane.
FORBIDDEN_WRITE_FIELDS = frozenset(
    {
        "quantity",
        "qty",
        "shares",
        "position",
        "target_weight",
        "weight",
        "order",
        "order_id",
        "stop",
        "limit",
        "broker",
        "portfolio",
        "notional",
        "allocation",
        "behavior_action",
    }
)


class GroundingContractError(ValueError):
    """Caller-facing contract violation (mutation-test target)."""


@dataclass
class CanonicalMemoryFact:
    """Versioned canonical read contract (Deliverable B1)."""

    memory_id: str
    subject_guid: str
    source_subject_or_symbol: str | None
    fact_digest: str
    observed_at: str  # RFC3339 Z
    age_seconds: float
    freshness_class: str
    decay_weight: float
    source_type: str | None
    source_id: str | None
    source_sha: str | None
    confidence: float | None
    contradiction_state: str
    schema_version: str = SCHEMA_VERSION
    # Extras kept for L3 mapping / audit (not sensitive content by default)
    counterpart_fact_ids: list[str] = field(default_factory=list)
    fact_text: str | None = None  # only populated when explicitly requested
    recorded_at: str | None = None
    decay_model: str | None = None
    disposition: str = "stale_but_usable"

    def to_public_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        d = {
            "memory_id": self.memory_id,
            "subject_guid": self.subject_guid,
            "source_subject_or_symbol": self.source_subject_or_symbol,
            "fact_digest": self.fact_digest,
            "observed_at": self.observed_at,
            "age_seconds": self.age_seconds,
            "freshness_class": self.freshness_class,
            "decay_weight": self.decay_weight,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_sha": self.source_sha,
            "confidence": self.confidence,
            "contradiction_state": self.contradiction_state,
            "schema_version": self.schema_version,
            "counterpart_fact_ids": list(self.counterpart_fact_ids),
            "recorded_at": self.recorded_at,
            "decay_model": self.decay_model,
            "disposition": self.disposition,
        }
        if include_text:
            d["fact_text"] = self.fact_text
        return d


@dataclass
class RejectionCounts:
    malformed_row: int = 0
    unresolved_subject: int = 0
    wrong_subject: int = 0
    expired_by_policy: int = 0
    contradiction_quarantine: int = 0  # counted but may still be visible
    conflicting_ids: int = 0
    conflicting_subjects: int = 0
    duplicate_id: int = 0
    duplicate_content: int = 0
    ambiguous_subject: int = 0
    below_min_influence: int = 0
    future_timestamp: int = 0
    malformed_timestamp: int = 0
    mixed_schema: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)

    @property
    def total(self) -> int:
        return sum(self.as_dict().values())


@dataclass
class SelectionResult:
    subject_guid: str
    selected: list[CanonicalMemoryFact]
    rejected: RejectionCounts
    candidates_considered: int
    grounded: bool
    empty_store: bool
    cliff_applied: bool
    policy: DecayPolicy
    cache_key: str
    snapshot_digest: str
    resolver_failure: str | None = None
    latency_ms: int = 0
    # Visible contradictions (not silently discarded)
    contradiction_visible: list[CanonicalMemoryFact] = field(default_factory=list)

    @property
    def recall_numerator(self) -> int:
        return len(self.selected)

    @property
    def recall_denominator(self) -> int:
        # Subject-relevant rows that were parse-valid (selected + below_floor + expired + visible contradictions)
        return (
            len(self.selected)
            + self.rejected.below_min_influence
            + self.rejected.expired_by_policy
            + len(self.contradiction_visible)
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def fact_digest_of(content: Any) -> str:
    payload = json.dumps(content, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _content_text(row: Mapping[str, Any]) -> str:
    content = row.get("content")
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return json.dumps(content, sort_keys=True, default=str)


def _contradiction_state(row: Mapping[str, Any]) -> tuple[str, list[str]]:
    status = str(row.get("status") or "").upper()
    counterparts: list[str] = []
    for key in ("contradicts", "contradiction_refs", "supersedes"):
        raw = row.get(key)
        if isinstance(raw, list):
            counterparts.extend(str(x) for x in raw if x)
        elif raw:
            counterparts.append(str(raw))
    if status == "QUARANTINED":
        return "unresolved", counterparts
    if status == "SUPERSEDED" or row.get("superseded_by"):
        return "superseded_by", counterparts
    if counterparts and key_has_contradicts(row):
        return "contradicted_by", counterparts
    if row.get("supersedes"):
        return "supersedes", counterparts
    return "none", counterparts


def key_has_contradicts(row: Mapping[str, Any]) -> bool:
    raw = row.get("contradicts")
    if isinstance(raw, list):
        return len(raw) > 0
    return bool(raw)


def cache_key_for(
    *,
    subject_guid: str,
    policy: DecayPolicy,
    source_revision: str,
    cutoff: str | None,
) -> str:
    raw = "|".join(
        [
            SCHEMA_VERSION,
            GROUNDED_INPUT_SCHEMA,
            policy.cache_token(),
            str(subject_guid),
            str(source_revision),
            str(cutoff or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def snapshot_digest_of(selected: list[CanonicalMemoryFact], *, subject_guid: str) -> str:
    """Replayable selection digest — IDs + weights + ages, no fact text."""
    payload = {
        "subject_guid": subject_guid,
        "facts": [
            {
                "memory_id": f.memory_id,
                "fact_digest": f.fact_digest,
                "decay_weight": round(f.decay_weight, 12),
                "age_seconds": round(f.age_seconds, 6),
                "contradiction_state": f.contradiction_state,
            }
            for f in selected
        ],
    }
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _stable_sort_key(fact: CanonicalMemoryFact) -> tuple:
    # Higher weight first; then newer (smaller age); then memory_id for tie-break.
    return (-fact.decay_weight, fact.age_seconds, fact.memory_id)


class SubjectGroundedMemorySelector:
    """Select subject-isolated memory with continuous decay (no age cliff)."""

    def __init__(
        self,
        backend: Any = None,
        *,
        policy: DecayPolicy | None = None,
        lookup: Callable[[str], dict[str, Any]] | None = None,
        source_revision: str | None = None,
        include_fact_text: bool = False,
        max_facts: int = 32,
    ) -> None:
        self.backend = backend
        self.policy = policy or load_decay_policy()
        self.lookup = lookup
        self.source_revision = source_revision or os.environ.get("BUILD_SHA") or "unknown"
        self.include_fact_text = include_fact_text
        self.max_facts = max_facts
        self._cache: dict[str, SelectionResult] = {}

    def _fetch_rows(self) -> list[dict]:
        if self.backend is None:
            return []
        if callable(self.backend):
            # Backend may be subject-filtered OR full-store; we always re-check isolation.
            return list(self.backend() or [])
        path = Path(self.backend)
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        if text.startswith("MALFORMED:"):
            raise ValueError(text[len("MALFORMED:") :].strip() or "malformed memory")
        rows: list[dict] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            rows.append(json.loads(line))
        return rows

    def select(
        self,
        subject_guid: str,
        *,
        now: datetime | None = None,
        cutoff: str | None = None,
        use_cache: bool = True,
    ) -> SelectionResult:
        if not subject_guid or not str(subject_guid).strip():
            raise GroundingContractError("subject_guid required")
        subject_guid = str(subject_guid).strip()
        now = now or _now()
        key = cache_key_for(
            subject_guid=subject_guid,
            policy=self.policy,
            source_revision=self.source_revision,
            cutoff=cutoff,
        )
        if use_cache and key in self._cache:
            return self._cache[key]

        t0 = time.monotonic()
        rejected = RejectionCounts()
        selected: list[CanonicalMemoryFact] = []
        contradictions: list[CanonicalMemoryFact] = []
        empty_store = False
        resolver_failure: str | None = None

        try:
            rows = self._fetch_rows()
        except Exception as exc:
            result = SelectionResult(
                subject_guid=subject_guid,
                selected=[],
                rejected=rejected,
                candidates_considered=0,
                grounded=False,
                empty_store=False,
                cliff_applied=False,
                policy=self.policy,
                cache_key=key,
                snapshot_digest=snapshot_digest_of([], subject_guid=subject_guid),
                resolver_failure=f"store_error:{type(exc).__name__}",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
            return result

        if not rows:
            empty_store = True

        seen_ids: set[str] = set()
        seen_digests: set[str] = set()
        candidates = 0

        for row in rows:
            if not isinstance(row, dict):
                rejected.malformed_row += 1
                continue
            candidates += 1

            # Mixed schema versions: accept known, count unknown but do not call parse-valid rows malformed
            # solely for legacy field names (handled by normalize_*).
            schema_ver = row.get("schema_version")
            if schema_ver is not None and str(schema_ver) not in {"1.0", "1", SCHEMA_VERSION, "MemoryFact@v2"}:
                rejected.mixed_schema += 1
                # Still attempt normalization; mixed schema is tracked, not an auto-drop of parse-valid rows.

            id_res = normalize_memory_id(row)
            if id_res.error == "conflicting_ids":
                rejected.conflicting_ids += 1
                continue
            if id_res.error == "missing_id" or not id_res.memory_id:
                rejected.malformed_row += 1
                continue
            mid = id_res.memory_id
            if mid in seen_ids:
                rejected.duplicate_id += 1
                continue

            sub_fields = normalize_subject_fields(row)
            if sub_fields.error == "conflicting_subjects":
                rejected.conflicting_subjects += 1
                continue

            try:
                disposition = row_subject_disposition(row, subject_guid, lookup=self.lookup)
            except (ResolverFailure, Exception) as exc:
                # Hard negative: never publish a zero as if the store were empty.
                resolver_failure = str(exc) if isinstance(exc, ResolverFailure) else f"{type(exc).__name__}: {exc}"
                result = SelectionResult(
                    subject_guid=subject_guid,
                    selected=[],
                    rejected=rejected,
                    candidates_considered=candidates,
                    grounded=False,
                    empty_store=False,
                    cliff_applied=False,
                    policy=self.policy,
                    cache_key=key,
                    snapshot_digest=snapshot_digest_of([], subject_guid=subject_guid),
                    resolver_failure=resolver_failure,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                )
                return result

            if disposition == "cross":
                rejected.wrong_subject += 1
                continue
            if disposition == "unmatched":
                rejected.unresolved_subject += 1
                continue
            if disposition == "ambiguous":
                rejected.ambiguous_subject += 1
                continue
            if disposition == "conflicting_subjects":
                rejected.conflicting_subjects += 1
                continue
            # match / match_resolved continue

            status = str(row.get("status") or "").upper()
            if status in EXPIRED_STATUSES:
                rejected.expired_by_policy += 1
                continue

            observed_raw = row.get("observed_at") or row.get("as_of") or row.get("produced_at") or row.get("created_at")
            observed = _parse_ts(observed_raw)
            if observed is None:
                rejected.malformed_timestamp += 1
                continue
            if observed > now:
                rejected.future_timestamp += 1
                continue

            recorded = _parse_ts(row.get("created_at") or row.get("recorded_at") or row.get("as_of"))
            conf_raw = row.get("confidence")
            try:
                confidence = float(conf_raw) if conf_raw is not None else 1.0
            except (TypeError, ValueError):
                confidence = 1.0

            age_ann = annotate_age(observed, now=now, policy=self.policy, confidence=confidence)
            digest = row.get("content_digest") or row.get("content_hash")
            if isinstance(digest, str) and digest and not digest.startswith("sha256:"):
                digest = (
                    "sha256:" + digest
                    if re.fullmatch(r"[0-9a-fA-F]{64}", digest)
                    else fact_digest_of(row.get("content"))
                )
            if not digest:
                digest = fact_digest_of(row.get("content"))

            if digest in seen_digests:
                rejected.duplicate_content += 1
                continue

            c_state, counterparts = _contradiction_state(row)
            source_refs = row.get("source_refs") or row.get("source_event_ids") or []
            source_id = None
            if isinstance(source_refs, list) and source_refs:
                source_id = str(source_refs[0])
            elif row.get("source_id"):
                source_id = str(row.get("source_id"))

            fact = CanonicalMemoryFact(
                memory_id=mid,
                subject_guid=subject_guid,
                source_subject_or_symbol=sub_fields.source_subject_or_symbol
                or (symbols_of(row)[0] if symbols_of(row) else None),
                fact_digest=str(digest),
                observed_at=_iso(observed),
                age_seconds=float(age_ann["age_seconds"]),
                freshness_class=str(age_ann["freshness_class"]),
                decay_weight=float(age_ann["decay_weight"]),
                source_type=(
                    str(row.get("source_kind") or row.get("memory_type") or row.get("source_type") or "") or None
                ),
                source_id=source_id,
                source_sha=(str(row.get("source_sha")) if row.get("source_sha") else None),
                confidence=confidence,
                contradiction_state=c_state,
                counterpart_fact_ids=counterparts,
                fact_text=_content_text(row) if self.include_fact_text else None,
                recorded_at=_iso(recorded) if recorded else None,
                decay_model=str(age_ann["decay_model"]),
                disposition=str(age_ann["freshness_class"]),
            )

            seen_ids.add(mid)
            seen_digests.add(str(digest))

            if status in QUARANTINE_STATUSES or c_state in {"contradicted_by", "unresolved"}:
                # Visible as contradiction/quarantine — not silently discarded.
                contradictions.append(fact)
                rejected.contradiction_quarantine += 1
                # Still eligible for selection if above floor (judgment can see state).
                # Quarantined rows do NOT enter selected influence set.
                if status in QUARANTINE_STATUSES:
                    continue

            if not meets_min_influence(fact.decay_weight, self.policy):
                rejected.below_min_influence += 1
                continue

            selected.append(fact)

        selected.sort(key=_stable_sort_key)
        if len(selected) > self.max_facts:
            # Surplus counted as below floor for metrics transparency.
            overflow = selected[self.max_facts :]
            rejected.below_min_influence += len(overflow)
            selected = selected[: self.max_facts]

        # Deterministic ordering already applied.
        grounded = len(selected) > 0
        result = SelectionResult(
            subject_guid=subject_guid,
            selected=selected,
            rejected=rejected,
            candidates_considered=candidates,
            grounded=grounded,
            empty_store=empty_store,
            cliff_applied=False,
            policy=self.policy,
            cache_key=key,
            snapshot_digest=snapshot_digest_of(selected, subject_guid=subject_guid),
            resolver_failure=None,
            latency_ms=int((time.monotonic() - t0) * 1000),
            contradiction_visible=contradictions,
        )
        if use_cache:
            self._cache[key] = result
        return result

    def invalidate_cache(self) -> None:
        self._cache.clear()


def build_grounded_judgment_input(
    selection: SelectionResult,
    *,
    subject_kind: str = "security",
    symbol: str | None = None,
    resolution_confidence: float = 1.0,
    research_object_ids: list[str] | None = None,
    free_first_exhausted: bool = True,
    effect_kind: str = "none",
    material_residual_question: dict[str, Any] | None = None,
    source_sha: str,
    epoch_id: str,
    schedule_slot: str,
    trigger: str = "scheduled",
    correlation_id: str,
    as_of_utc: str | None = None,
    include_fact_text: bool = False,
) -> dict[str, Any]:
    """Produce GroundedJudgmentInput@v1 for Lane C. cliff_applied MUST be false."""
    if selection.cliff_applied:
        raise GroundingContractError("cliff_applied must be false for L2 acceptance")
    if selection.resolver_failure:
        raise GroundingContractError(f"resolver_failure prevents grounded input: {selection.resolver_failure}")

    weights = [f.decay_weight for f in selection.selected]
    ages_h = [f.age_seconds / 3600.0 for f in selection.selected]

    def _median(xs: list[float]) -> float:
        if not xs:
            return 0.0
        ys = sorted(xs)
        mid = len(ys) // 2
        if len(ys) % 2:
            return ys[mid]
        return (ys[mid - 1] + ys[mid]) / 2.0

    facts_out = []
    for f in selection.selected:
        entry = {
            "memory_fact_id": f.memory_id,
            "fact_text": (f.fact_text if include_fact_text else ""),
            "fact_digest": f.fact_digest,
            "observed_at_utc": f.observed_at,
            "recorded_at_utc": f.recorded_at or f.observed_at,
            "age_hours": f.age_seconds / 3600.0,
            "decay_weight": f.decay_weight,
            "decay_model": f.decay_model or selection.policy.decay_model,
            "provenance": {
                "source_kind": f.source_type or "durable_memory",
                "source_id": f.source_id or f.memory_id,
                "source_sha": f.source_sha or source_sha,
                "epoch_id": epoch_id,
            },
            "contradiction": {
                "state": f.contradiction_state,
                "counterpart_fact_ids": list(f.counterpart_fact_ids),
            },
            "subject_guid": f.subject_guid,
        }
        facts_out.append(entry)

    mrq = material_residual_question or {
        "present": bool(selection.grounded),
        "question_text": None,
        "why_unresolved_by_research": None,
        "materiality_basis": None,
    }

    out = {
        "schema": GROUNDED_INPUT_SCHEMA,
        "subject": {
            "subject_guid": selection.subject_guid,
            "subject_kind": subject_kind,
            "symbol": symbol,
            "resolved_by": RESOLVER_VERSION,
            "resolution_confidence": float(resolution_confidence),
        },
        "memory_facts": facts_out,
        "retrieval": {
            "candidates_considered": selection.candidates_considered,
            "returned": len(selection.selected),
            "filtered_wrong_subject": selection.rejected.wrong_subject,
            "filtered_below_floor": selection.rejected.below_min_influence,
            "decay_weight_min": min(weights) if weights else 0.0,
            "decay_weight_max": max(weights) if weights else 0.0,
            "decay_weight_median": _median(weights),
            "oldest_returned_age_hours": max(ages_h) if ages_h else 0.0,
            "retrieval_latency_ms": selection.latency_ms,
            "cliff_applied": False,
            # Lane B extensions (additive; Lane C may ignore)
            "rejected_by_reason": selection.rejected.as_dict(),
            "recall_numerator": selection.recall_numerator,
            "recall_denominator": selection.recall_denominator,
            "snapshot_digest": selection.snapshot_digest,
            "cache_key": selection.cache_key,
            "empty_store": selection.empty_store,
            "influence_source_ids": [f.memory_id for f in selection.selected],
            "policy_version": selection.policy.schema_version,
            "contradiction_visible_count": len(selection.contradiction_visible),
        },
        "research": {
            "research_object_ids": list(research_object_ids or []),
            "free_first_exhausted": bool(free_first_exhausted),
            "effect_kind": effect_kind,
        },
        "grounded": bool(selection.grounded),
        "material_residual_question": mrq,
        "source_sha": source_sha,
        "epoch_id": epoch_id,
        "schedule_slot": schedule_slot,
        "trigger": trigger,
        "correlation_id": correlation_id,
        "as_of_utc": as_of_utc or _iso(_now()),
    }
    assert_no_behavior_writes(out)
    return out


def assert_no_behavior_writes(payload: Mapping[str, Any]) -> None:
    """Guard: L2 result must not carry writable portfolio/behavior fields."""
    flat_keys: set[str] = set()

    def walk(obj: Any, prefix: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                flat_keys.add(str(k))
                walk(v, key)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{prefix}[{i}]")

    walk(payload)
    banned = flat_keys & FORBIDDEN_WRITE_FIELDS
    if banned:
        raise GroundingContractError(f"behavior/portfolio fields present: {sorted(banned)}")


def next_question_from_facts(
    facts: list[CanonicalMemoryFact],
    *,
    baseline_question: str | None = None,
) -> dict[str, Any]:
    """Deterministic cognition-field derivation for with/without comparison.

    Uses digests + freshness only — never requires printing sensitive content.
    """
    if not facts:
        return {
            "next_question": baseline_question,
            "changed": False,
            "reason": "no_memory_selected",
        }
    top = facts[0]
    # Named field: next_question. Content is a digest-anchored probe string, not store text.
    derived = (
        f"revisit subject memory {top.memory_id[:8]} "
        f"age_h={top.age_seconds / 3600.0:.1f} decay={top.decay_weight:.4f} "
        f"class={top.freshness_class}"
    )
    if baseline_question and baseline_question == derived:
        return {"next_question": derived, "changed": False, "reason": "identical_to_baseline"}
    if baseline_question is None:
        return {"next_question": derived, "changed": True, "reason": "memory_derived"}
    return {
        "next_question": derived,
        "changed": True,
        "reason": "memory_overrode_baseline",
        "before": baseline_question,
        "after": derived,
    }


def compare_with_without_memory(
    selection: SelectionResult,
    *,
    baseline_question: str = "what changed since last wake?",
) -> dict[str, Any]:
    """Prove whether a named cognition field changes with vs without selected memory.

    Retrieval that returns rows but changes nothing is not proven grounding.
    """
    without = next_question_from_facts([], baseline_question=baseline_question)
    # Force without to keep baseline
    without = {
        "next_question": baseline_question,
        "changed": False,
        "reason": "memory_suppressed",
    }
    with_mem = next_question_from_facts(selection.selected, baseline_question=baseline_question)
    field_changed = with_mem.get("next_question") != without.get("next_question")
    return {
        "field": "next_question",
        "without_memory": without,
        "with_memory": with_mem,
        "field_changed": field_changed,
        "selected_memory_fact_ids": [f.memory_id for f in selection.selected],
        "no_change_reason": None if field_changed else with_mem.get("reason", "no_change"),
        "snapshot_digest": selection.snapshot_digest,
        "proven_grounding": bool(field_changed and selection.selected),
    }


def influence_metrics(selection: SelectionResult) -> dict[str, Any]:
    """B3 metrics bundle for persistence / handoff (IDs and aggregates only)."""
    return {
        "selected_memory_fact_ids": [f.memory_id for f in selection.selected],
        "rejected_counts_by_reason": selection.rejected.as_dict(),
        "recall_rate": {
            "numerator": selection.recall_numerator,
            "denominator": selection.recall_denominator,
        },
        "selected_age_and_decay": [
            {
                "memory_id": f.memory_id,
                "age_seconds": f.age_seconds,
                "age_hours": f.age_seconds / 3600.0,
                "decay_weight": f.decay_weight,
                "freshness_class": f.freshness_class,
            }
            for f in selection.selected
        ],
        "influence_source_ids": [f.memory_id for f in selection.selected],
        "snapshot_digest": selection.snapshot_digest,
        "cache_key": selection.cache_key,
        "cliff_applied": False,
        "grounded": selection.grounded,
        "empty_store": selection.empty_store,
        "resolver_failure": selection.resolver_failure,
        "policy_version": selection.policy.schema_version,
        "schema_version": SCHEMA_VERSION,
    }

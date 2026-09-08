"""wake_subject_selector.py — choose subjects for a scheduled persistent wake.

This module is the first real *consumer* of MaterialChange@v1.

``scripts/material_change_detector.py`` documents that MaterialChange@v1 is
written and nothing reads it yet — thresholds were meant to be judged before
any model spend. This selector is that first reader: a recent material change
qualifies a subject for an unattended wake, without inventing work when the
universe is quiet.

Priority (soak-aligned):
  1. subjects with unconsumed research (ResearchObject lacking a non-none
     AgentConsumptionReceipt@v2 for this agent)
  2. subjects with a recent MaterialChange@v1

Deterministic: same inputs ⇒ same order. Ties broken by subject_guid.
Bounded by ``limit`` (default 3). Empty list is an honest answer.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

# Align with material_change_detector.NEW_HOURS default; overridable via arg.
DEFAULT_RECENT_HOURS = 24
DEFAULT_LIMIT = 3
# MaterialChange@v1 is versioned by change_guid. A non-none receipt for that
# exact version suppresses reselection until either (a) a newer change_guid
# appears for the subject, or (b) MATERIAL_CHANGE_REEVAL_HOURS elapses since
# the consumption receipt timestamp. Same version is therefore not permanently
# consumed; it is held for a documented reevaluation interval.
MATERIAL_CHANGE_REEVAL_HOURS = 24

SOURCE_UNCONSUMED_RESEARCH = "unconsumed_research"
SOURCE_MATERIAL_CHANGE = "material_change"


@dataclass(frozen=True)
class SubjectCandidate:
    subject_guid: str
    source: str
    source_id: str
    observed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_jsonl(path: Path | str | None) -> list[dict]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict] = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        import json
        rows.append(json.loads(line))
    return rows


def research_is_consumed(
    *,
    agent_id: str,
    research_object_id: str,
    receipts: Iterable[dict],
) -> bool:
    """True iff this agent has a non-none effect receipt for the research object.

    INTERFACE_CONTRACTS.md §6: effect_kind='none' is legal and is NOT evidence of
    consumption maturity. Only effect_kind != 'none' counts.
    """
    for r in receipts:
        if str(r.get("agent_id")) != str(agent_id):
            continue
        if str(r.get("source_kind")) != "research_object":
            continue
        if str(r.get("source_id")) != str(research_object_id):
            continue
        if str(r.get("effect_kind") or "none") != "none":
            return True
    return False


def _receipt_effect_ts(receipt: dict) -> datetime | None:
    return _parse_ts(
        receipt.get("acknowledged_at")
        or receipt.get("retrieved_at")
        or receipt.get("produced_at")
        or receipt.get("created_at")
    )


def material_change_is_suppressed(
    *,
    agent_id: str,
    change_guid: str,
    receipts: Iterable[dict],
    now: datetime | None = None,
    reeval_hours: float = MATERIAL_CHANGE_REEVAL_HOURS,
) -> bool:
    """True iff this exact MaterialChange version should not be reselected yet.

    Policy (source-version + reevaluation interval):
      * A non-none receipt for ``(agent, material_change, change_guid)`` suppresses
        that version.
      * Suppression lifts after ``reeval_hours`` from the receipt timestamp so the
        same version is not permanently consumed while still material.
      * A *different* ``change_guid`` (new materiality revision) is never
        suppressed by a receipt for another version — callers select the newest
        change per subject separately.
      * ``effect_kind='none'`` never suppresses (§6).
    """
    now = now or _now()
    latest_consume: datetime | None = None
    for r in receipts:
        if str(r.get("agent_id")) != str(agent_id):
            continue
        if str(r.get("source_kind")) != "material_change":
            continue
        if str(r.get("source_id")) != str(change_guid):
            continue
        if str(r.get("effect_kind") or "none") == "none":
            continue
        ts = _receipt_effect_ts(r) or datetime.min.replace(tzinfo=timezone.utc)
        if latest_consume is None or ts > latest_consume:
            latest_consume = ts
    if latest_consume is None:
        return False
    # Permanent only within the reevaluation window.
    return (now - latest_consume) < timedelta(hours=float(reeval_hours))


def select_subjects(
    agent_id: str,
    *,
    limit: int = DEFAULT_LIMIT,
    now: datetime | None = None,
    research_objects: Iterable[dict] | None = None,
    receipts: Iterable[dict] | None = None,
    material_changes: Iterable[dict] | None = None,
    recent_hours: float = DEFAULT_RECENT_HOURS,
    material_change_reeval_hours: float = MATERIAL_CHANGE_REEVAL_HOURS,
) -> list[SubjectCandidate]:
    """Return up to ``limit`` subject candidates for ``agent_id``.

    Callers inject iterables for hermetic tests. Production loaders may pass
    JSONL-backed lists via ``load_selection_inputs``.
    """
    if limit <= 0:
        return []
    now = now or _now()
    research_objects = list(research_objects or [])
    receipts = list(receipts or [])
    material_changes = list(material_changes or [])

    # --- priority a: unconsumed research ---
    research_candidates: list[SubjectCandidate] = []
    seen_research_subjects: set[str] = set()
    # Sort research objects for determinism before filtering
    def _ro_key(ro: dict) -> tuple:
        return (
            str(ro.get("subject_guid") or ""),
            str(ro.get("research_object_id") or ro.get("id") or ""),
        )

    for ro in sorted(research_objects, key=_ro_key):
        sg = str(ro.get("subject_guid") or "")
        rid = str(ro.get("research_object_id") or ro.get("id") or "")
        if not sg or not rid:
            continue
        if research_is_consumed(agent_id=agent_id, research_object_id=rid, receipts=receipts):
            continue
        if sg in seen_research_subjects:
            # One research-driven candidate per subject is enough for this slot.
            continue
        seen_research_subjects.add(sg)
        research_candidates.append(
            SubjectCandidate(
                subject_guid=sg,
                source=SOURCE_UNCONSUMED_RESEARCH,
                source_id=rid,
                observed_at=str(ro.get("published_at") or ro.get("produced_at") or "") or None,
            )
        )

    research_candidates.sort(key=lambda c: (c.subject_guid, c.source_id))

    # --- priority b: recent MaterialChange@v1 ---
    cutoff = now - timedelta(hours=float(recent_hours))
    mc_by_subject: dict[str, SubjectCandidate] = {}
    for mc in material_changes:
        # Accept schema_version MaterialChange@v1; ignore unknown/malformed quietly.
        schema = str(mc.get("schema_version") or mc.get("schema") or "")
        if schema and schema != "MaterialChange@v1":
            continue
        sg = str(mc.get("subject_guid") or "")
        if not sg:
            continue
        observed = _parse_ts(mc.get("observed_at") or mc.get("produced_at"))
        if observed is None or observed < cutoff:
            continue
        cid = str(mc.get("change_guid") or mc.get("id") or "")
        if not cid:
            continue
        if material_change_is_suppressed(
            agent_id=agent_id,
            change_guid=cid,
            receipts=receipts,
            now=now,
            reeval_hours=material_change_reeval_hours,
        ):
            continue
        # Keep the most recent change per subject (deterministic on equal timestamps
        # by change_guid).
        prev = mc_by_subject.get(sg)
        if prev is None:
            mc_by_subject[sg] = SubjectCandidate(
                subject_guid=sg,
                source=SOURCE_MATERIAL_CHANGE,
                source_id=cid,
                observed_at=observed.isoformat().replace("+00:00", "Z"),
            )
            continue
        prev_ts = _parse_ts(prev.observed_at) or datetime.min.replace(tzinfo=timezone.utc)
        if observed > prev_ts or (observed == prev_ts and cid < prev.source_id):
            mc_by_subject[sg] = SubjectCandidate(
                subject_guid=sg,
                source=SOURCE_MATERIAL_CHANGE,
                source_id=cid,
                observed_at=observed.isoformat().replace("+00:00", "Z"),
            )

    material_candidates = sorted(
        (c for sg, c in mc_by_subject.items() if sg not in seen_research_subjects),
        key=lambda c: (c.subject_guid, c.source_id),
    )

    ordered = research_candidates + material_candidates
    return ordered[:limit]


def load_selection_inputs(env: dict | None = None) -> dict[str, list[dict]]:
    """Optional file-backed inputs for production/cron without a live DB write path.

    Env keys (all optional; missing ⇒ empty):
      TRADEAI_WAKE_RESEARCH_OBJECTS_PATH
      TRADEAI_WAKE_RECEIPTS_PATH
      TRADEAI_WAKE_MATERIAL_CHANGES_PATH
    """
    e = env if env is not None else {}
    return {
        "research_objects": _load_jsonl(e.get("TRADEAI_WAKE_RESEARCH_OBJECTS_PATH")),
        "receipts": _load_jsonl(e.get("TRADEAI_WAKE_RECEIPTS_PATH")),
        "material_changes": _load_jsonl(e.get("TRADEAI_WAKE_MATERIAL_CHANGES_PATH")),
    }


__all__ = [
    "SubjectCandidate",
    "DEFAULT_LIMIT",
    "DEFAULT_RECENT_HOURS",
    "MATERIAL_CHANGE_REEVAL_HOURS",
    "SOURCE_UNCONSUMED_RESEARCH",
    "SOURCE_MATERIAL_CHANGE",
    "research_is_consumed",
    "material_change_is_suppressed",
    "select_subjects",
    "load_selection_inputs",
]

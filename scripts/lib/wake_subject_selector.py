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
  2. InstrumentRecord subjects that are cadence-due (HELD/WATCH/EXIT) — closes
     the M2 gap where L3 wakes never overlapped InstrumentRecords
  3. subjects with a recent MaterialChange@v1

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
SOURCE_INSTRUMENT_RECORD = "instrument_record_due"
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


def instrument_record_candidates(
    records: Iterable[dict],
    *,
    now: datetime | None = None,
    guid_for_symbol: Callable[[str], str | None] | None = None,
) -> list[SubjectCandidate]:
    """Cadence-due HELD/WATCH/EXIT InstrumentRecords as wake subjects.

    ``source_id`` is the subject_key so critique writeback can target the record
    without a second registry round-trip.
    """
    now = now or _now()
    resolve = guid_for_symbol
    if resolve is None:
        def resolve(sym: str) -> str | None:  # type: ignore[misc]
            try:
                from scripts.lib import identity_registry as ir

                doc = ir.load()
                hit = ir.lookup_symbol(doc, sym)
                if not hit:
                    return None
                return str(hit.get("subject_guid") or "") or None
            except Exception:
                return None

    out: list[SubjectCandidate] = []
    seen: set[str] = set()
    for rec in records:
        if not isinstance(rec, dict):
            continue
        sk = str(rec.get("subject_key") or "").strip()
        if ":" not in sk:
            continue
        kind, sym = sk.split(":", 1)
        if kind.upper() not in ("HELD", "WATCH", "EXIT") or not sym:
            continue
        nxt = _parse_ts(rec.get("next_eligible_at"))
        if nxt is not None and nxt > now:
            continue
        guid = resolve(sym)
        if not guid or guid in seen:
            continue
        seen.add(guid)
        out.append(
            SubjectCandidate(
                subject_guid=guid,
                source=SOURCE_INSTRUMENT_RECORD,
                source_id=sk,
                observed_at=(nxt.isoformat().replace("+00:00", "Z") if nxt else None),
            )
        )
    out.sort(key=lambda c: (c.subject_guid, c.source_id))
    return out


def select_subjects(
    agent_id: str,
    *,
    limit: int = DEFAULT_LIMIT,
    now: datetime | None = None,
    research_objects: Iterable[dict] | None = None,
    receipts: Iterable[dict] | None = None,
    material_changes: Iterable[dict] | None = None,
    instrument_records: Iterable[dict] | None = None,
    guid_for_symbol: Callable[[str], str | None] | None = None,
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
    instrument_records = list(instrument_records or [])

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

    # --- priority b: cadence-due InstrumentRecords (M2 bridge) ---
    ir_candidates = [
        c
        for c in instrument_record_candidates(
            instrument_records, now=now, guid_for_symbol=guid_for_symbol
        )
        if c.subject_guid not in seen_research_subjects
    ]
    seen_ir = {c.subject_guid for c in ir_candidates}

    # --- priority c: recent MaterialChange@v1 ---
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

    blocked = seen_research_subjects | seen_ir
    material_candidates = sorted(
        (c for sg, c in mc_by_subject.items() if sg not in blocked),
        key=lambda c: (c.subject_guid, c.source_id),
    )

    ordered = research_candidates + ir_candidates + material_candidates
    # R1 (agentic-memory tranche 1, 2026-09-24): with research first and
    # limit=3, the last 200 hourly wakes were 200/200 unconsumed_research and
    # 0 instrument_record_due while 37 of 52 HELD/WATCH/EXIT records were due.
    # When research alone would fill every slot and a record is due, one slot
    # is reserved for the first due record so the cadence path is never
    # starved. Ordering inside each source is unchanged (deterministic).
    if ir_candidates and len(research_candidates) >= limit and limit > 1:
        ordered = (
            research_candidates[: limit - 1]
            + ir_candidates[:1]
            + research_candidates[limit - 1:]
            + ir_candidates[1:]
            + material_candidates
        )
    return ordered[:limit]


def load_selection_inputs(env: dict | None = None) -> dict[str, list[dict]]:
    """Optional file-backed inputs for production/cron without a live DB write path.

    Env keys (all optional; missing ⇒ empty):
      TRADEAI_WAKE_RESEARCH_OBJECTS_PATH
      TRADEAI_WAKE_RECEIPTS_PATH
      TRADEAI_WAKE_MATERIAL_CHANGES_PATH
      TRADEAI_WAKE_INSTRUMENT_RECORDS_PATH
    """
    e = env if env is not None else {}
    ir_path = e.get("TRADEAI_WAKE_INSTRUMENT_RECORDS_PATH")
    if not ir_path:
        shared = (
            Path.home()
            / "trade-ai-releases"
            / "persistent-state"
            / "data"
            / "cio"
            / "cio_instrument_records.jsonl"
        )
        ir_path = str(shared) if shared.is_file() else None
    return {
        "research_objects": _load_jsonl(e.get("TRADEAI_WAKE_RESEARCH_OBJECTS_PATH")),
        "receipts": _load_jsonl(e.get("TRADEAI_WAKE_RECEIPTS_PATH")),
        "material_changes": _load_jsonl(e.get("TRADEAI_WAKE_MATERIAL_CHANGES_PATH")),
        "instrument_records": _load_jsonl(ir_path),
    }


__all__ = [
    "SubjectCandidate",
    "DEFAULT_LIMIT",
    "DEFAULT_RECENT_HOURS",
    "MATERIAL_CHANGE_REEVAL_HOURS",
    "SOURCE_UNCONSUMED_RESEARCH",
    "SOURCE_INSTRUMENT_RECORD",
    "SOURCE_MATERIAL_CHANGE",
    "research_is_consumed",
    "material_change_is_suppressed",
    "instrument_record_candidates",
    "select_subjects",
    "load_selection_inputs",
]

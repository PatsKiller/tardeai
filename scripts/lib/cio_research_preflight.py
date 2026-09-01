"""P1 / M5 — load InstrumentRecord before ResearchNeedDecision.decide().

The loader (`load_instrument_record_for_wake`) and the wake-queue consult
(`cio_wake_subject.decide`) already exist. This module is the research-gate
half: after identity + materiality, load by subject_key, honour a days-old
defer when hashes are unchanged, and **do not call** `decide()` on a skip.

MBI_BEHAVIOR = 0. Observational; never sizes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from scripts.lib.cio_instrument_record import (
    hash_changed,
    load_instrument_record_for_wake,
)
from scripts.lib.cio_rehydrate import gate_input_from_record

SCHEMA = "ResearchPreflight@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0

# Acceptance A: a disposition recorded more than two days ago must still bind.
DEFER_MIN_AGE = timedelta(hours=48)


def _utc(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def hashes_unchanged(record: dict[str, Any], observed: Optional[dict[str, Any]]) -> bool:
    """True when no named observable has moved (UNSET is not a move)."""
    if not observed:
        return True
    for name, value in observed.items():
        if hash_changed(record, name, value):
            return False
    return True


def days_old_defer_exists(record: dict[str, Any], *, now: datetime) -> bool:
    """True when an operator defer disposition on the record is ≥ 48h old."""
    for turn in record.get("operator_turns") or []:
        if str(turn.get("intent") or "").lower() != "defer":
            continue
        ts = _utc(turn.get("ts") or turn.get("as_of"))
        if ts and (now - ts) >= DEFER_MIN_AGE:
            return True
    return False


def should_skip_cadence(
    record: dict[str, Any],
    *,
    observed: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> tuple[bool, str]:
    """next_eligible future AND hashes unchanged AND days-old defer → skip."""
    now = now or datetime.now(timezone.utc)
    nxt = _utc(record.get("next_eligible_at"))
    if not nxt or nxt <= now:
        return False, "eligible_or_no_stamp"
    if not days_old_defer_exists(record, now=now):
        return False, "defer_not_days_old"
    if not hashes_unchanged(record, observed):
        return False, "hash_moved"
    return True, "cadence_not_due"


def decide_after_load(
    subject_key: str,
    *,
    plan: Optional[dict[str, Any]] = None,
    observed: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
    root: Any = None,
    decide_fn: Optional[Callable[..., dict[str, Any]]] = None,
    gate_extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Identity/materiality already done by the caller. Load, then maybe decide.

    Order (durable steps):
      1. refuse when not material
      2. load InstrumentRecord by subject_key
      3. if cadence skip → return skip WITHOUT calling decide_fn
      4. else ResearchNeedDecision.decide(gate_input_from_record(...))
    """
    now = now or datetime.now(timezone.utc)
    plan = dict(plan or {})
    extra = {k: v for k, v in (gate_extra or {}).items() if v is not None}
    base: dict[str, Any] = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI_BEHAVIOR,
        "as_of": now.replace(microsecond=0).isoformat(),
        "subject_key": subject_key,
        "decide_called": False,
        "record_loaded": False,
        "record_status": None,
    }

    if not bool(plan.get("material", True)):
        return {
            **base,
            "decision": "skip",
            "reason": "not_material",
        }

    wake = load_instrument_record_for_wake(
        subject_key_hint=subject_key, root=root,
    )
    base["record_status"] = wake.get("status")
    base["subject_key"] = wake.get("subject_key") or subject_key

    if wake.get("status") != "LOADED" or not wake.get("record"):
        # No memory to honour — still call decide so the gate can skip on its
        # own terms. The load was attempted; that is the durable step.
        base["record_loaded"] = False
        decide_fn = decide_fn or _default_decide
        inp = gate_input_from_record(
            None, plan={**plan, "symbols": [subject_key.split(":")[-1]]},
            observed=observed,
        )
        inp.update(extra)
        out = dict(decide_fn(inp, now=now))
        out.update(base)
        out["decide_called"] = True
        return out

    rec = dict(wake["record"])
    base["record_loaded"] = True

    skip, why = should_skip_cadence(rec, observed=observed, now=now)
    if skip:
        return {
            **base,
            "decision": "skip",
            "reason": why,
            "next_eligible_at": rec.get("next_eligible_at"),
            "decide_called": False,
        }

    decide_fn = decide_fn or _default_decide
    inp = gate_input_from_record(rec, plan=plan, observed=observed)
    inp.update(extra)
    out = dict(decide_fn(inp, now=now))
    out.update(base)
    out["decide_called"] = True
    return out

def _default_decide(inp: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    from scripts.lib.cio_research_gate import decide as _decide
    return _decide(inp, now=now)

#!/usr/bin/env python3
"""cio_wake_subject.py — give a wake a subject, then load its record before acting.

Proof M5: a scheduled wake loads the record before it acts, and a disposition
made days earlier is still honoured today with nobody replaying it.

`InstrumentRecordStore.load(subject_key)` is built, correct and tested, and no
scheduled wake calls it. The reason is one level deeper than "nobody wired it",
and worth stating because it changes what wiring means:

    measured 2026-08-30, live release
      wakes in the store                          1,513
      wakes carrying a subject_key                    0
      wakes mentioning a record subject at all        1

**The wake queue has no subject field.** 1,395 of 1,513 are GOAL_DUE, keyed on
`goal_id`/`owner_agent` — agent goals, not instruments. The single wake that
references a record subject is an OPERATOR_MESSAGE whose subject sits in free
text: *"What should I watch on SCHD this week?"*. So there was nothing to load
BY, and a loader with no key is not a loader anybody forgot to call.

This module supplies the missing join, and is deliberately honest about its
limits: most wakes are goal-scoped and resolve to no subject at all. That is
reported, not papered over — `subject_resolved=False` is the common case and is
not a failure.

MBI_BEHAVIOR = 0. This decides whether to look, never what to do.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA = "WakeSubjectDecision@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

# Verdicts this module can return for a wake.
PROCEED = "proceed"
# Honours a future next_eligible_at already on the record. The ordinary writer
# of that field on a normal (non-reject, non-defer) completion is
# cio_rehydrate.apply_after_cycle → ROUTINE_LOOK_DAYS (#732). This module does
# not stamp; it consults. A stamp that exists only after rejection/defer would
# make this skip a failure-path artefact, not cadence.
SKIP_CADENCE = "skip/cadence_not_due"
NO_SUBJECT = "proceed/no_subject"
NO_RECORD = "proceed/no_record"


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


_SUBJECT_TOKEN = re.compile(r"\b(HELD|EXIT|WATCH|SLEEVE|CASH):[A-Za-z0-9_.\-]+")


def resolve_subject_key(wake: dict[str, Any],
                        known_keys: Optional[set[str]] = None) -> tuple[Optional[str], str]:
    """Best available subject for this wake, and how it was found.

    Order is most-explicit first. A free-text match is last and only against
    subjects that actually have a record, because matching an arbitrary
    three-letter token out of prose would invent subjects that do not exist.
    """
    ctx = wake.get("context") if isinstance(wake.get("context"), dict) else {}

    for source, holder in (("wake.subject_key", wake), ("context.subject_key", ctx)):
        v = holder.get("subject_key")
        if v:
            return str(v), source

    # A bare symbol, if the wake carries one.
    for source, holder in (("wake.symbol", wake), ("context.symbol", ctx)):
        v = holder.get("symbol")
        if v and known_keys:
            sym = str(v).upper()
            for k in known_keys:
                if k.split(":", 1)[-1].upper() == sym:
                    return k, source
    # A subject_key token anywhere in the wake.
    blob = json.dumps(wake, default=str)
    m = _SUBJECT_TOKEN.search(blob)
    if m:
        return m.group(0), "wake.token"

    # Operator prose. Only against subjects that have a record.
    text = str(ctx.get("text") or "")
    if text and known_keys:
        for k in sorted(known_keys, key=len, reverse=True):
            name = k.split(":", 1)[-1]
            if len(name) >= 2 and re.search(rf"\b{re.escape(name)}\b", text):
                return k, "context.text"

    return None, "unresolved"


def decide(wake: dict[str, Any], *, store: Any = None,
           now: Optional[datetime] = None,
           known_keys: Optional[set[str]] = None) -> dict[str, Any]:
    """Consult the record BEFORE the wake is claimed.

    Returns a decision dict carrying both halves of the proof: what the wake
    would do without the record (`without_record`) and what it does with it
    (`verdict`). If those two never differ, the record is not being used, and a
    monitor can see that without reading any code.

    Never raises. A store that cannot be read yields PROCEED with the reason
    recorded — refusing to act because memory is unavailable would be a worse
    failure than acting without it, and the reason is visible either way.
    """
    now = now or datetime.now(timezone.utc)
    out: dict[str, Any] = {
        "schema": SCHEMA, "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
        "wake_job_id": wake.get("wake_job_id"),
        "trigger_type": wake.get("trigger_type"),
        # Without the record every wake proceeds. That is the baseline the
        # proof is measured against.
        "without_record": PROCEED,
        "subject_key": None, "subject_source": None, "subject_resolved": False,
        "record_found": False, "next_eligible_at": None,
        "verdict": PROCEED, "reason": None, "record_used": False,
    }

    if store is None:
        try:
            from scripts.lib.cio_instrument_record import InstrumentRecordStore
        except Exception:
            try:
                from cio_instrument_record import InstrumentRecordStore  # type: ignore
            except Exception as e:
                out["reason"] = f"record store unavailable: {type(e).__name__}: {e}"
                return out
        try:
            store = InstrumentRecordStore()
        except Exception as e:
            out["reason"] = f"record store unavailable: {type(e).__name__}: {e}"
            return out

    if known_keys is None:
        try:
            known_keys = {str(r.get("subject_key")) for r in store.all()
                          if r.get("subject_key")}
        except Exception as e:
            out["reason"] = f"record store unreadable: {type(e).__name__}: {e}"
            return out

    key, source = resolve_subject_key(wake, known_keys)
    out["subject_key"], out["subject_source"] = key, source
    out["subject_resolved"] = key is not None
    if key is None:
        # The common case: goal-scoped wakes have no instrument subject. Not a
        # failure, and not something to invent a subject for.
        out["verdict"] = NO_SUBJECT
        out["reason"] = "wake carries no resolvable subject"
        return out

    try:
        rec = store.load(key)                      # <-- load-by-subject
    except Exception as e:
        out["reason"] = f"record load failed: {type(e).__name__}: {e}"
        return out

    if rec is None:
        out["verdict"] = NO_RECORD
        out["reason"] = f"no record for {key}"
        return out

    out["record_found"] = True
    out["record_used"] = True
    nxt = _utc(rec.get("next_eligible_at"))
    out["next_eligible_at"] = rec.get("next_eligible_at")
    out["next_research_question"] = rec.get("next_research_question")

    if nxt and nxt > now:
        out["verdict"] = SKIP_CADENCE
        out["reason"] = (
            f"{key}: the record defers research until {nxt.isoformat()} "
            f"({round((nxt - now).total_seconds() / 3600.0, 1)}h away). "
            "The disposition was recorded earlier and nobody replayed it.")
        return out

    out["verdict"] = PROCEED
    out["reason"] = f"{key}: record loaded, nothing defers this wake"
    return out


# Verdicts that actually stop a wake. `proceed/no_subject` and
# `proceed/no_record` are labels on a wake that still proceeds; counting them as
# "changed by the record" made the first run of this report claim 1,515 changed
# decisions when the true number was 1. A metric that overstates its own effect
# is worse than no metric.
BLOCKING = (SKIP_CADENCE,)


def summarise(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """What the record actually changed this cycle — behaviour, not labels."""
    changed = [d for d in decisions if d.get("verdict") in BLOCKING]
    return {
        "wakes_considered": len(decisions),
        "subject_resolved": sum(1 for d in decisions if d.get("subject_resolved")),
        "record_found": sum(1 for d in decisions if d.get("record_found")),
        # Only wakes whose OUTCOME the record changed.
        "decisions_changed_by_record": len(changed),
        "skipped_cadence_not_due": sum(1 for d in decisions
                                       if d.get("verdict") == SKIP_CADENCE),
        # The common case, reported so its size is visible rather than implied.
        "no_subject": sum(1 for d in decisions if d.get("verdict") == NO_SUBJECT),
        "no_record": sum(1 for d in decisions if d.get("verdict") == NO_RECORD),
        "changed": [{"wake_job_id": d.get("wake_job_id"),
                     "subject_key": d.get("subject_key"),
                     "without_record": d.get("without_record"),
                     "with_record": d.get("verdict"),
                     "reason": d.get("reason")} for d in changed],
    }

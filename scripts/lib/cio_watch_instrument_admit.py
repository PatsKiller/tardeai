"""Admit WATCH InstrumentRecord@v1 rows — cognition only.

The migrate path seeded HELD / EXIT / SLEEVE but never WATCH, so the research
budget's reentry_or_watch slot and CIO home watch narratives had nothing to
load (LITMUS_COVERAGE / CC_WATCH_INTELLIGENCE_WIRING). This module fills that
gap from the operator watchlist.

Uses the existing `new_record` + `apply_cognition` + `InstrumentRecordStore.upsert`
path. Cap 20. notify_priority stays ``none`` (cognition only — no Telegram).
Does not fire S7 plans. Does not call Maria / watch-review workers.

READ_ONLY_ADVISORY. MBI_BEHAVIOR=0.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_instrument_record import (
    InstrumentRecordStore,
    apply_cognition,
    cc_narrative,
    is_mintable,
    new_record,
    subject_key,
)

SCHEMA = "WatchInstrumentAdmit@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
ADMIT_CAP = 20
WATCHLIST_REL = ("data", "portfolios", "state", "watchlist.json")


def _now(now: Optional[datetime] = None) -> datetime:
    dt = now or datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _project_root(root: Path | str | None = None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[2]


def load_watchlist(root: Path | str | None = None) -> dict[str, Any]:
    """Operator watchlist.json — symbol-keyed dict. Empty on miss."""
    path = _project_root(root).joinpath(*WATCHLIST_REL)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return raw if isinstance(raw, dict) else {}


def candidate_watch_symbols(
    root: Path | str | None = None,
    *,
    store: Optional[InstrumentRecordStore] = None,
    watchlist: Optional[dict[str, Any]] = None,
    cap: int = ADMIT_CAP,
) -> list[str]:
    """Ordered mintable watch symbols not already carrying WATCH or HELD.

    Cap applies to the candidate list (admission will not exceed it).
    """
    wl = watchlist if watchlist is not None else load_watchlist(root)
    store = store or InstrumentRecordStore()
    existing = {str(r.get("subject_key") or "") for r in store.all()}
    out: list[str] = []
    for sym in wl.keys():
        s = str(sym or "").strip().upper()
        if not s:
            continue
        ok, _why = is_mintable("WATCH", s)
        if not ok:
            continue
        if subject_key("WATCH", s) in existing:
            continue
        if subject_key("HELD", s) in existing:
            # Already on the book as a held record — do not dual-admit as WATCH.
            continue
        out.append(s)
        if len(out) >= int(cap):
            break
    return out


def _seed_cognition(sym: str, entry: Optional[dict[str, Any]], *, now: datetime):
    """Deterministic cognition for a freshly admitted WATCH record."""
    entry = entry if isinstance(entry, dict) else {}
    thesis = str(entry.get("thesis") or entry.get("notes") or "").strip()
    what = (
        f"WATCH:{sym} — {thesis}" if thesis
        else f"WATCH:{sym} — on the operator watchlist; thesis pending."
    )
    narrative = cc_narrative(
        what=what[:600],
        thesis_fit=str(entry.get("target_intent") or "watch")[:400],
        recommendation_option_id=None,
        risks=[],
        evidence_refs=[],
        writer="cognition:watch_admit",
    )
    return apply_cognition(
        new_record("WATCH", sym, symbols=[sym]),
        next_research_question=f"What would change the watch thesis for {sym}?",
        notify_priority="none",
        narrative=narrative,
        hashes={"price": None, "weight": None, "earnings": None, "analyst": None},
        strict=True,
    )


def admit_watch_records(
    *,
    root: Path | str | None = None,
    store: Optional[InstrumentRecordStore] = None,
    watchlist: Optional[dict[str, Any]] = None,
    cap: int = ADMIT_CAP,
    apply: bool = False,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Admit up to ``cap`` WATCH records. Dry-run unless ``apply=True``.

    Returns a receipt. Never creates S7 plans. Never calls Maria workers.
    """
    now = _now(now)
    root_p = _project_root(root)
    store = store or InstrumentRecordStore()
    wl = watchlist if watchlist is not None else load_watchlist(root_p)
    candidates = candidate_watch_symbols(
        root_p, store=store, watchlist=wl, cap=cap)

    admitted: list[str] = []
    skipped: dict[str, int] = {}
    changed_fields: dict[str, list[str]] = {}

    for sym in candidates:
        entry = wl.get(sym) or wl.get(sym.lower()) or {}
        try:
            rec, changed = _seed_cognition(sym, entry if isinstance(entry, dict) else {}, now=now)
        except Exception as exc:  # noqa: BLE001
            skipped[f"cognition_error:{type(exc).__name__}"] = (
                skipped.get(f"cognition_error:{type(exc).__name__}", 0) + 1)
            continue
        # Hard pins: cognition only.
        if rec.get("notify_priority") not in (None, "none"):
            skipped["notify_not_none"] = skipped.get("notify_not_none", 0) + 1
            continue
        if apply:
            store.upsert(rec)
        admitted.append(rec["subject_key"])
        changed_fields[rec["subject_key"]] = list(changed)

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
        "financial_action": False,
        "notify": False,
        "s7_fired": False,
        "maria_invoked": False,
        "cap": int(cap),
        "candidates": len(candidates),
        "admitted": admitted,
        "admitted_n": len(admitted),
        "skipped": skipped,
        "changed_fields": changed_fields,
        "apply": bool(apply),
        "as_of": now.replace(microsecond=0).isoformat(),
        "watchlist_path": str(root_p.joinpath(*WATCHLIST_REL)),
    }

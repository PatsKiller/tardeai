"""P1 / M5 — load InstrumentRecord before ResearchNeedDecision.decide().

Acceptance A:
  record with defer older than 48h + unchanged hashes → decide() never called
  Mutation: next_eligible_at in the past → not skip (decide may be called)

Acceptance B (dry-run): covered by entrypoint --dry-run + mutation below.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.lib.cio_instrument_record import content_hash
from scripts.lib.cio_research_preflight import (
    DEFER_MIN_AGE,
    decide_after_load,
    should_skip_cadence,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _rec_with_old_defer(*, next_eligible_at: str, weight_hash=None):
    defer_ts = (NOW - timedelta(hours=72)).isoformat()  # > 48h
    rec = {
        "subject_key": "HELD:SCHD",
        "next_eligible_at": next_eligible_at,
        "operator_turns": [
            {"intent": "defer", "ts": defer_ts, "note": "wait for earnings"},
        ],
        "hashes": {},
    }
    if weight_hash is not None:
        rec["hashes"]["weight"] = weight_hash
    return rec


def test_old_defer_unchanged_hashes_skips_without_calling_decide():
    """Acceptance A — decide() never called."""
    future = (NOW + timedelta(days=5)).isoformat()
    rec = _rec_with_old_defer(
        next_eligible_at=future,
        weight_hash=content_hash(18.0),
    )
    calls: list[dict] = []

    def _spy(inp, *, now=None):
        calls.append(inp)
        return {"decision": "flash", "reason": "should_not_run"}

    # Inject via load stub: use a tiny fake store through monkeypatch of load
    from scripts.lib import cio_research_preflight as pf

    def _fake_load(**kw):
        return {
            "ok": True,
            "status": "LOADED",
            "subject_key": "HELD:SCHD",
            "record": rec,
        }

    orig = pf.load_instrument_record_for_wake
    pf.load_instrument_record_for_wake = lambda **kw: _fake_load(**kw)  # type: ignore
    try:
        out = decide_after_load(
            "HELD:SCHD",
            plan={"material": True, "symbols": ["SCHD"]},
            observed={"weight": 18.0},
            now=NOW,
            decide_fn=_spy,
        )
    finally:
        pf.load_instrument_record_for_wake = orig

    assert out["decide_called"] is False
    assert out["decision"] == "skip"
    assert out["reason"] == "cadence_not_due"
    assert out["record_loaded"] is True
    assert calls == [], "ResearchNeedDecision.decide must not be called"


def test_mutation_past_next_eligible_does_not_skip():
    """Acceptance A mutation — next_eligible_at in the past → not skip."""
    past = (NOW - timedelta(hours=1)).isoformat()
    rec = _rec_with_old_defer(
        next_eligible_at=past,
        weight_hash=content_hash(18.0),
    )
    skip, why = should_skip_cadence(rec, observed={"weight": 18.0}, now=NOW)
    assert skip is False
    assert why == "eligible_or_no_stamp"

    calls: list[dict] = []

    def _spy(inp, *, now=None):
        calls.append(inp)
        return {"decision": "flash", "reason": "ok"}

    from scripts.lib import cio_research_preflight as pf
    orig = pf.load_instrument_record_for_wake
    pf.load_instrument_record_for_wake = lambda **kw: {  # type: ignore
        "ok": True, "status": "LOADED", "subject_key": "HELD:SCHD", "record": rec,
    }
    try:
        out = decide_after_load(
            "HELD:SCHD",
            plan={"material": True, "symbols": ["SCHD"]},
            observed={"weight": 18.0},
            now=NOW,
            decide_fn=_spy,
        )
    finally:
        pf.load_instrument_record_for_wake = orig

    assert out["decide_called"] is True
    assert len(calls) == 1
    assert out["decision"] == "flash"


def test_hash_move_overrides_days_old_defer():
    future = (NOW + timedelta(days=5)).isoformat()
    rec = _rec_with_old_defer(
        next_eligible_at=future,
        weight_hash=content_hash(18.0),
    )
    skip, why = should_skip_cadence(rec, observed={"weight": 24.0}, now=NOW)
    assert skip is False
    assert why == "hash_moved"


def test_fresh_defer_under_48h_does_not_skip_via_preflight_rule():
    """Days-old means ≥48h. A brand-new defer is not yet the M5 shape."""
    future = (NOW + timedelta(days=5)).isoformat()
    rec = {
        "subject_key": "HELD:SCHD",
        "next_eligible_at": future,
        "operator_turns": [
            {"intent": "defer", "ts": (NOW - timedelta(hours=12)).isoformat()},
        ],
        "hashes": {"weight": content_hash(18.0)},
    }
    skip, why = should_skip_cadence(rec, observed={"weight": 18.0}, now=NOW)
    assert skip is False
    assert why == "defer_not_days_old"
    assert DEFER_MIN_AGE == timedelta(hours=48)


def test_not_material_never_loads_decide():
    calls: list = []

    def _spy(inp, *, now=None):
        calls.append(inp)
        return {"decision": "flash", "reason": "x"}

    out = decide_after_load(
        "HELD:SCHD",
        plan={"material": False},
        now=NOW,
        decide_fn=_spy,
    )
    assert out["decision"] == "skip"
    assert out["reason"] == "not_material"
    assert out["decide_called"] is False
    assert calls == []


def test_entrypoint_exposes_dry_run_flag():
    src = (
        Path(__file__).resolve().parent.parent
        / "scripts" / "cio_wake_dispatch_entrypoint.py"
    ).read_text(encoding="utf-8")
    assert "--dry-run" in src
    assert "dry_run_record_consult" in src
    assert "decide_after_load" in src


def test_dispatcher_still_consults_before_claim():
    """Existing #723 ordering — plan mint still blocked by wake consult."""
    src = (
        Path(__file__).resolve().parent.parent
        / "scripts" / "lib" / "cio_wake_dispatcher.py"
    ).read_text(encoding="utf-8")
    assert src.index("M5: load the record before acting") < src.index(
        "# ── Claim with lease"
    )

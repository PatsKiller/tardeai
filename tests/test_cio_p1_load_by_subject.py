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


ENTRYPOINT = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "cio_wake_dispatch_entrypoint.py"
)


def _main_live_body():
    """Statements in `main()` that run when --dry-run is NOT passed.

    The dry-run branch is an early return, so everything after it is the path
    the installed timer takes. Returned as AST so a caller can ask what is
    CALLED there -- a substring search cannot tell which branch a name sits in,
    which is exactly how this shipped: `decide_after_load` appeared in the file
    while only `--dry-run` could reach it.
    """
    import ast
    src = ENTRYPOINT.read_bytes()
    compile(src, str(ENTRYPOINT), "exec")   # compile(), never bare ast.parse
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "main")
    cut = 0
    for i, stmt in enumerate(fn.body):
        if isinstance(stmt, ast.If) and "dry_run" in ast.dump(stmt.test):
            cut = i + 1
    assert cut, "main() no longer has a --dry-run early-return branch"
    return fn.body[cut:]


def _called_names(nodes):
    import ast
    out = set()
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                f = sub.func
                if isinstance(f, ast.Name):
                    out.add(f.id)
                elif isinstance(f, ast.Attribute):
                    out.add(f.attr)
    return out


def test_entrypoint_exposes_dry_run_flag():
    src = ENTRYPOINT.read_text(encoding="utf-8")
    assert "--dry-run" in src
    assert "dry_run_record_consult" in src
    assert "decide_after_load" in src


def test_scheduled_path_calls_decide_after_load_without_dry_run():
    """The installed timer runs `cio_wake_dispatch_entrypoint.py` with NO flag.

    So the #810 function must be reachable from main() AFTER the dry-run early
    return. Asserting the name is somewhere in the file is not enough -- that
    passed for the whole period the live path never called it.
    """
    called = _called_names(_main_live_body())
    assert "decide_after_load" in called, (
        "the scheduled (non --dry-run) path must call decide_after_load; "
        f"live path calls: {sorted(called)}"
    )


def test_scheduled_path_writes_cognition_back_and_persists():
    """Load-then-decide without a write-back is still a read-only system."""
    called = _called_names(_main_live_body())
    assert "apply_cycle_and_persist" in called, (
        "the scheduled path must apply the cycle as cognition and persist it"
    )


def test_persist_goes_through_the_rail_and_the_existing_store():
    """No second store, and no route around apply_cognition.

    apply_after_cycle delegates to apply_cognition, which is what raises
    BehaviorWriteRefused. A persist that called InstrumentRecordStore.upsert
    with a hand-built record would bypass that rail while still looking like a
    persist.
    """
    import ast
    src = ENTRYPOINT.read_bytes()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "apply_cycle_and_persist")
    called = _called_names(fn.body)
    assert "apply_after_cycle" in called, "cognition must go through apply_after_cycle"
    assert "upsert" in called, "the record must be persisted through the store"
    assert "load" in called, "the record must be loaded before it is written"


def test_dispatcher_still_consults_before_claim():
    """Existing #723 ordering — plan mint still blocked by wake consult."""
    src = (
        Path(__file__).resolve().parent.parent
        / "scripts" / "lib" / "cio_wake_dispatcher.py"
    ).read_text(encoding="utf-8")
    assert src.index("M5: load the record before acting") < src.index(
        "# ── Claim with lease"
    )

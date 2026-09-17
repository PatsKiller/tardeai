"""Controls for the goal-loop DRIVERS — the gap between armed and working.

Measured 2026-09-17, one day after the goal machinery shipped and three crons
were armed:

  * the pilot had written 14 receipts carrying ``ok: true`` and NO verdict — its
    runner probed for an API that did not exist and wrote ``library_loaded``;
  * ``cio_goal_laps.jsonl`` did not exist, so no generation token had ever been
    minted;
  * ``GOAL_PREDICATE_SET`` was 0 against 34,912 wakes, so no goal could close;
  * the gate bridge measured hourly and discarded the result.

Every one of those looked healthy from outside. These controls exist so that
"the schedule fired" can never again be mistaken for "the work happened", and
each must go RED if its guarantee is removed.

Offline by construction: no database, no network, no provider.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import goal_budget as gb  # noqa: E402
from scripts.lib.goal_pilot_material_change import (  # noqa: E402
    OUTCOME_BOUNDED_IGNORANCE,
    pilot_cost,
    run_pilot,
    run_shadow,
)


#: A change whose symbol has no independently-written second source — the
#: canonical bounded-ignorance case, and the one that exercises every
#: `unobtainable` branch in assemble_facts.
CHANGE_NO_SOURCE = {
    "change_guid": "c-guid-2",
    "subject_guid": "s-guid-2",
    "symbol": "ZZZZ",
    "change_pct": -5.0,
}


def _baseline():
    """Load the baseline module by path — it is a script, not a package member."""
    spec = importlib.util.spec_from_file_location(
        "_baseline", ROOT / "scripts" / "report_goal_loop_baseline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── D1: the driver exists, and the runner can find it ────────────────────────

def test_the_runner_probe_finds_a_real_driver():
    """run_goal_pilot_material_change.py branches on hasattr(pilot, 'run_shadow').

    Without this the armed hourly cron writes `library_loaded` and evaluates
    nothing — a scheduled job proving invocation rather than work.
    """
    from scripts.lib import goal_pilot_material_change as pilot
    assert hasattr(pilot, "run_shadow")
    assert callable(pilot.run_shadow)


def test_no_database_is_unavailable_not_an_empty_pass():
    """`laps: 0, status: ok` would be indistinguishable from 'no changes today'."""
    class _Boom:
        def cursor(self):  # pragma: no cover - never reached
            raise AssertionError("must not open a cursor")

    def _explode():
        raise OSError("no .env here")

    import scripts.material_change_detector as mcd
    real = mcd._db
    mcd._db = _explode
    try:
        out = run_shadow()
    finally:
        mcd._db = real
    assert out["status"] == "unavailable"
    assert "no database" in out["why"]
    assert out["laps"] == 0
    assert out["cost"]["paid_calls"] == 0


class _FakeCur:
    """Two changes; one symbol has an independent value, the other does not."""

    def __init__(self):
        self._stage = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._stage = 1 if "material_changes" in sql else 2

    def fetchall(self):
        if self._stage == 1:
            return [
                ("c-guid-1", "s-guid-1", "NOC", -2.44, 100.0, 97.56, "2026-09-17T00:00:00Z"),
                ("c-guid-2", "s-guid-2", "ZZZZ", -5.00, 100.0, 95.00, "2026-09-17T00:00:00Z"),
            ]
        return [("NOC", 2.40)]  # corroborate(): only NOC has a second source


class _FakeConn:
    def cursor(self):
        return _FakeCur()

    def close(self):
        pass


def test_a_change_with_no_independent_source_is_bounded_ignorance():
    """THE headline property: unknowable, not false. Never `achieved`."""
    out = run_shadow(conn=_FakeConn())
    assert out["status"] == "ok"
    assert out["laps"] == 2
    assert out["achieved"] == 0
    by = {r["change_guid"]: r for r in out["rows"]}
    assert by["c-guid-2"]["outcome"] == OUTCOME_BOUNDED_IGNORANCE
    assert "independent_value_present" in by["c-guid-2"]["unobtainable"]


def test_the_driver_spends_nothing():
    out = run_shadow(conn=_FakeConn())
    assert out["cost"]["paid_calls"] == 0
    assert out["cost"]["cost_usd"] == 0.0


def test_tier1_and_lap_terms_stay_unsupplied_rather_than_false():
    """Defaulting them to False would assert a check ran and failed."""
    out = run_shadow(conn=_FakeConn())
    row = out["rows"][0]
    assert "tier0_deterministic_pass" not in row["facts"]
    assert "second_lap_distinct_dedup_key" in row["unobtainable"]


# ── D0: the baseline can tell "ran" from "did work" ──────────────────────────

def test_the_baseline_counts_invocation_only_pilot_rows(tmp_path, monkeypatch):
    """14 rows / 0 verdicts must be visible, not read as 14 laps."""
    b = _baseline()
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    rows = [
        {"ok": True, "result": {"status": "library_loaded"}},          # invocation only
        {"ok": True, "result": {"status": "ok", "laps": 3}},           # real work
    ]
    (cio / "goal_pilot_material_change.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(b, "_state_root", lambda: tmp_path)
    monkeypatch.setattr(b, "PROJECT_ROOT", tmp_path)
    d = b.drivers()
    assert d["pilot"]["rows"] == 2
    assert d["pilot"]["rows_with_verdict"] == 1
    assert d["pilot"]["invocation_only"] == 1


def test_an_absent_lap_ledger_is_unavailable_never_zero(tmp_path, monkeypatch):
    """A zero would claim the driver ran and minted nothing."""
    b = _baseline()
    monkeypatch.setattr(b, "_state_root", lambda: tmp_path)
    monkeypatch.setattr(b, "PROJECT_ROOT", tmp_path)
    d = b.drivers()
    assert d["laps_minted"]["status"] == "unavailable"
    assert "no generation has ever been minted" in d["laps_minted"]["why"]


def test_the_unavailable_reason_names_the_production_path(tmp_path, monkeypatch):
    """_cio() falls back to PROJECT_ROOT; the message must not name the fallback."""
    b = _baseline()
    monkeypatch.setattr(b, "_state_root", lambda: tmp_path)
    monkeypatch.setattr(b, "PROJECT_ROOT", Path("/nowhere/checkout"))
    d = b.drivers()
    assert str(tmp_path) in d["laps_minted"]["why"]
    assert "/nowhere/checkout" not in d["laps_minted"]["why"]


def test_goal_predicate_set_is_reported(tmp_path, monkeypatch):
    """It gates the control number: no predicate, no possible close."""
    b = _baseline()
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    (cio / "cio_goals.jsonl").write_text(
        json.dumps({"event_type": "GOAL_CREATED", "goal_id": "g1",
                    "occurred_at": "2026-09-17T00:00:00Z"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(b, "_state_root", lambda: tmp_path)
    monkeypatch.setattr(b, "PROJECT_ROOT", tmp_path)
    g = b.goals()
    assert g["goal_predicate_set"] == 0
    assert g["goal_status_changed"] == 0


# ── D4: what the budget actually does, measured not assumed ──────────────────

def test_a_corrupt_ledger_denies(tmp_path):
    p = gb.budget_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{", encoding="utf-8")
    assert gb.check("g", "v0", root=tmp_path)["allowed"] is False
    assert gb.try_consume_lap("g", "v0", root=tmp_path)["allowed"] is False


def test_an_absent_ledger_permits_laps_but_never_paid_calls(tmp_path):
    """Corrected 2026-09-17: absent is NOT deny — it means nothing spent yet.

    The safety comes from the DEFAULT ceilings, not from absence. Asserting the
    wrong mechanism would leave the real one untested.
    """
    assert gb.check("g", "v0", root=tmp_path)["allowed"] is True
    lim = gb.limits()
    assert lim["max_paid_calls"] == 0
    assert lim["max_cost_usd"] == 0.0


# ── D2: a wrong API must raise, not degrade into a false measurement ─────────

def test_the_unobtainable_set_is_enforced_not_merely_declared():
    """Removing the guard must break something, or the guard is decoration.

    Added 2026-09-17 after a mutation run: deleting the enforcement left all 13
    controls green, so `UNOBTAINABLE_CAPABLE` was enforced-but-unverified — one
    step better than the zero-reader constant it replaced, and still not a
    control. `subject_linked` is read straight off the change row and can never
    be unknowable; claiming it is means the driver lost its own input and must
    fail loudly rather than report ignorance.
    """
    from scripts.lib import goal_pilot_material_change as p

    real = p._agrees

    def _rogue(observed, independent):
        raise AssertionError("must not be reached")

    # Drive a rogue entry in through the one seam that writes `unobtainable`:
    # monkeypatch the capable set to exclude a term the code does mark.
    original = p.UNOBTAINABLE_CAPABLE
    p.UNOBTAINABLE_CAPABLE = frozenset()  # nothing may be unobtainable now
    try:
        with pytest.raises(ValueError, match="UNOBTAINABLE_CAPABLE"):
            p.assemble_facts(CHANGE_NO_SOURCE, independent=None,
                             agrees_fn=lambda o, i: (False, "no_independent_source"))
    finally:
        p.UNOBTAINABLE_CAPABLE = original
        p._agrees = real


def test_set_goal_predicate_refuses_to_guess_an_accessor():
    src = (ROOT / "scripts" / "set_goal_predicate.py").read_text(encoding="utf-8")
    assert "list_open_goals" in src
    assert "list_goals()" not in src


def test_set_goal_predicate_defaults_to_dry_run():
    src = (ROOT / "scripts" / "set_goal_predicate.py").read_text(encoding="utf-8")
    assert '"--apply", action="store_true"' in src
    assert "DRY RUN" in src

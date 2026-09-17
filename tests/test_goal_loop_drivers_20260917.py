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
    # Assert the DEFAULT, not the EFFECTIVE limit. `limits()` with no root reads
    # the operator's live goal_budget_policy.json, so this coupled a unit test to
    # host state: it broke the moment the operator funded Tier 2 on 2026-09-17
    # (max_paid_calls 0 -> 2). A test that fails when the host is correctly
    # configured invites someone to "fix" it by loosening the assertion, which
    # would silently delete the real guarantee.
    assert gb.DEFAULT_LIMITS["max_paid_calls"] == 0
    assert gb.DEFAULT_LIMITS["max_cost_usd"] == 0.0
    # And with an isolated root (no policy file), the effective limits ARE the
    # defaults — which is the claim that actually matters here.
    iso = gb.limits(root=tmp_path)
    assert iso["max_paid_calls"] == 0
    assert iso["max_cost_usd"] == 0.0


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


def test_set_goal_predicate_reads_the_predicate_off_the_goal_projection():
    """`set_predicate` returns the GOAL, not the predicate payload.

    Found 2026-09-17 by reading real output, not by a control: --apply printed
    predicate_version/hash/identity as null while the event landed correctly,
    because the script read those keys off the top level of
    `dict(self._goals[goal_id])` where they live under ["predicate"]. A receipt
    reporting that nothing happened when something did is this programme's own
    defect class, inverted — and it would have made the one write that moves
    GOAL_PREDICATE_SET off zero look like a no-op.
    """
    src = (ROOT / "scripts" / "set_goal_predicate.py").read_text(encoding="utf-8")
    assert 'payload or {}).get("predicate")' in src, \
        "must read the predicate off the goal projection, not the top level"
    assert 'report["predicate_identity"] = applied.get("predicate_identity")' in src
    # And it must refuse to claim success it cannot name.
    assert "is unverified" in src


# ── S1-S4: the four defects adversarial review found in the first draft ──────
# All four had live production evidence and no control. Each of these goes RED
# when its fix is removed.

class _KindCur:
    """Two changes: one price_excursion (comparable), one news_burst (not)."""

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
                ("g1", "s1", "NOC", "price_excursion", -2.44, 100.0, 97.56, "2026-09-17T00:00:00Z"),
                ("g2", "s2", "LULU", "news_burst", 90.00, 0.0, 19.0, "2026-09-17T00:00:00Z"),
            ]
        return [("NOC", 2.40), ("LULU", 0.78)]


class _KindConn:
    def cursor(self):
        return _KindCur()

    def close(self):
        pass


def test_a_wrong_unit_kind_is_unobtainable_not_disagreeing():
    """S1. A news_burst `magnitude` is a burst score, not a percent move.

    Measured against production 2026-09-17: comparing burst 90.00 against price
    0.78 produced `disagree_90.00_vs_0.78` -> supplied-and-false -> UNSATISFIED
    -> ask_operator. Six of eight live rows became false operator escalations
    from two quantities never in the same units. 81% of 30 days of rows.
    """
    from scripts.lib.goal_pilot_material_change import run_shadow as rs
    out = rs(conn=_KindConn())
    by = {r["change_guid"]: r for r in out["rows"]}
    burst = by["g2"]
    assert burst["outcome"] == OUTCOME_BOUNDED_IGNORANCE
    assert burst["unobtainable"]["agrees_corroborated"].startswith("kind_not_price_comparable")
    assert "agrees_corroborated" not in burst["facts"], "must not record a comparison"
    assert out["not_price_comparable"] == 1
    # The comparable one still gets a real corroboration attempt.
    assert "agrees_corroborated" in by["g1"]["facts"]


def test_only_price_comparable_kinds_are_corroborated():
    """S1, the other half: the non-price symbol must not even be looked up."""
    from scripts.lib import goal_pilot_material_change as p
    assert p.PRICE_COMPARABLE_KINDS == frozenset({"price_excursion"})
    out = p.run_shadow(conn=_KindConn())
    assert out["independent_found"] == 1, "only the price_excursion row counts"


class _BadCur:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        raise RuntimeError('column "magnitude" does not exist')

    def fetchall(self):  # pragma: no cover
        return []


class _BadConn:
    def cursor(self):
        return _BadCur()

    def close(self):
        pass


def test_a_query_failure_is_unavailable_and_never_raises():
    """S2. Raising let the runner write an envelope with a hardcoded ok: true.

    That is the "14 receipts, no verdict" defect this driver exists to end,
    recurring on the first schema drift or statement timeout.
    """
    from scripts.lib.goal_pilot_material_change import run_shadow as rs
    out = rs(conn=_BadConn())          # must not raise
    assert out["status"] == "unavailable"
    assert "query failed" in out["why"]
    assert out["laps"] == 0
    # Schema parity with the ok payload, so a consumer cannot KeyError.
    for k in ("changes_read", "not_price_comparable", "outcomes", "achieved", "rows"):
        assert k in out


def test_a_checkout_lap_ledger_is_never_reported_as_production(tmp_path, monkeypatch):
    """S3. `_cio()` falls back to PROJECT_ROOT; drivers() must not follow it.

    Adversarial review proved the baseline reporting `rows: 2` from a temp
    checkout while production had no ledger at all — the control measurement
    sourced from a throwaway tree.
    """
    b = _baseline()
    prod = tmp_path / "prod"
    checkout = tmp_path / "checkout"
    (checkout / "data" / "cio").mkdir(parents=True)
    (checkout / "data" / "cio" / "cio_goal_laps.jsonl").write_text(
        json.dumps({"lap": 1}) + "\n", encoding="utf-8")
    (prod / "data" / "cio").mkdir(parents=True)
    monkeypatch.setattr(b, "_state_root", lambda: prod)
    monkeypatch.setattr(b, "PROJECT_ROOT", checkout)
    d = b.drivers()
    assert d["laps_minted"]["status"] == "unavailable", \
        "reported a checkout file as a production measurement"
    assert str(prod) in d["laps_minted"]["why"]


def test_zero_laps_is_work_not_invocation_only(tmp_path, monkeypatch):
    """S4. `laps: 0` is a real measurement on a quiet day — 0 is falsy."""
    b = _baseline()
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    rows = [
        {"ok": True, "result": {"status": "ok", "laps": 0, "outcomes": {}}},   # quiet day: WORK
        {"ok": True, "result": {"status": "unavailable", "why": "no db"}},     # measured nothing
        {"ok": True, "result": {"status": "library_loaded"}},                  # invocation only
    ]
    (cio / "goal_pilot_material_change.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(b, "_state_root", lambda: tmp_path)
    monkeypatch.setattr(b, "PROJECT_ROOT", tmp_path)
    d = b.drivers()
    assert d["pilot"]["rows_with_verdict"] == 1, "a quiet-day run is work"
    assert d["pilot"]["invocation_only"] == 2


def test_the_gate_bridge_must_not_write_a_git_tracked_file_on_a_schedule():
    """Regression guard for a landmine I armed and then defused, 2026-09-17.

    `--update-catalog` writes `config/agent_maturity_catalog.json`, which is
    git-TRACKED and not ignored. Adding that flag to the hourly :35 cron made the
    dev tree permanently dirty, and cio_phase2_exact_main_deploy.sh dies on
    `ROOT working tree dirty` — so every future deploy would have refused,
    silently, from the next fire onward. Closing one gap by creating a worse one.

    The flag is fine by hand; it must not be on a schedule until the bridge
    writes to the production state root like every other hourly receipt.
    """
    import subprocess
    out = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    offenders = [ln for ln in out.splitlines()
                 if ln.strip() and not ln.lstrip().startswith("#")
                 and "cio_gate_measurement_bridge" in ln and "--update-catalog" in ln]
    assert not offenders, (
        "a scheduled --update-catalog writes a git-tracked file hourly and will "
        f"block every deploy: {offenders}")


def _load_sgp(name: str):
    import importlib.util as iu
    spec = iu.spec_from_file_location(name, ROOT / "scripts" / "set_goal_predicate.py")
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _isolated_store(tmp_path):
    """An open goal in a throwaway store, so no test touches production."""
    from scripts.lib.cio_goals import CIOGoalStore
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True, exist_ok=True)
    log = cio / "cio_goals.jsonl"
    store = CIOGoalStore(event_path=log,
                         projection_path=cio / "cio_goals_projection.json",
                         cursor_path=cio / "cio_goals_cursor.json")
    # `owner_agent`, keyword-only, and it must be a member of VALID_OWNERS
    # (cio_goals.py:40) — an arbitrary string raises. Guessed the keyword once
    # and the value once; the signature is at :438 and the set at :40.
    store.create_goal(owner_agent="sentinel", title="dry-run probe")
    return store, log


def test_the_dry_run_appends_no_event_behaviourally(tmp_path, monkeypatch, capsys):
    """RUN it and assert the event log is byte-identical — not a source grep.

    Adversarial review 2026-09-17 mutated this script so the write fired
    unconditionally WITHOUT --apply, left the asserted strings ("DRY RUN",
    "--apply") intact, and the old grep-based control stayed GREEN. A control
    that asserts comments exist is decoration, which is the exact defect this
    programme removes.
    """
    sgp = _load_sgp("_sgp_dry")
    store, log = _isolated_store(tmp_path)
    monkeypatch.setattr(sgp, "_store", lambda: store)
    monkeypatch.setattr(sys, "argv", ["set_goal_predicate.py", "--json"])

    before = log.read_bytes()
    rc = sgp.main()
    capsys.readouterr()
    assert rc == 0
    assert log.read_bytes() == before, "dry run appended to the event log"


def test_the_apply_path_actually_appends(tmp_path, monkeypatch, capsys):
    """The other half: --apply must write, or the dry-run control proves nothing."""
    sgp = _load_sgp("_sgp_apply")
    store, log = _isolated_store(tmp_path)
    monkeypatch.setattr(sgp, "_store", lambda: store)
    monkeypatch.setattr(sys, "argv", ["set_goal_predicate.py", "--apply", "--json"])

    before = log.read_bytes()
    rc = sgp.main()
    capsys.readouterr()
    assert rc == 0
    after = log.read_bytes()
    assert after != before
    assert after.startswith(before), "must be append-only"
    assert b"GOAL_PREDICATE_SET" in after

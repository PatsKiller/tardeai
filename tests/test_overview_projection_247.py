"""INC-OVW / OP-042: the overview lane runs 24/7 and its last-good window is DERIVED from that schedule.

This module is the acceptance test the operator's amendment asks for. It does not mock the calendar: it loads
``config/lane_registry.json`` and ``config/n8n_run_allowlist.json``, enumerates every admitted slot of five
reference weeks with ``cron_schedule.fires_between`` (the dispatcher's own DST-safe calendar), walks every
minute of each week, and runs the real admission predicates over the result.

What it pins:

* exactly one scheduler owns the lane, and ``scheduler.cadence`` / ``cadence_slots`` / ``dispatch.cron`` are the
  same set of expressions (a drift between those three homes is what produced INC-OVW);
* ``active_days`` is all seven days (a missing weekday makes ``heartbeat_watch.classify`` answer SILENT_OK);
* the measured largest real gap is the fall-back fold (65 min), the only gap over its period's cadence in any of
  the five weeks, and no local hour of any week is without a fire;
* ``expected_cadence_hours`` is that measured gap, not the in-hours cadence;
* ``LAST_GOOD_MAX_S > max_gap + retry span + dispatch delay`` and every term comes from the files, not literals;
* ``compute_due`` admits the lane at every minute around the period boundaries and both DST nights;
* no admission gate reads a clock except ``offpeak_verdict`` (asserted from the signatures), and this lane
  declares no off-peak gate, no market gate and no hold;
* the producer's document separates ``built_at`` (assembly) from the body's source clocks, and a weekend rebuild
  keeps Friday's source clocks byte-identical;
* the reader never computes and answers a named UNKNOWN with null numbers, never zero;
* nothing else writes the projection (no cron line, systemd unit or second registry row).

Offline: synthetic fixtures, isolated clocks, no DB, no network, no live state root.
"""
from __future__ import annotations

import inspect
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts.lib import lane_dispatch as D
from scripts.lib import lane_registry as L
from scripts.lib import n8n_due
from scripts.lib import n8n_retry_policy
from scripts.lib import overview_lane_contract as C
from scripts import n8n_run_executor as E

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("America/New_York")
UTC = timezone.utc

#: The stored-only reader's changes travel as a PATCH: ``scripts/lib/overview_projection.py`` is held by the R8
#: fold (claim ``20261114T195327Z-claude-740dc4a7``, which reverts that reader), so this deliverable never edits
#: it. R8's tree has no window and no stored-only ``read()`` at all - nothing to patch and nothing to assert there.
#: These markers therefore key on the presence of the HUNKS in the file on disk (a code fact), never on whether an
#: assertion would pass: a mutant that lowers the shipped window must still FAIL these tests, not skip them.
PATCH = ROOT / "docs/ops/packets/inc-ovw-20261114/overview_projection.patch"
_PROJECTION_SRC = (ROOT / "scripts/lib/overview_projection.py").read_text(encoding="utf-8")
STORED_ONLY_READER = "LAST_GOOD_MAX_S" in _PROJECTION_SRC
PRODUCER_WRITES_CLOCKS = "def _source_clocks(" in _PROJECTION_SRC
READER_CARRIES_CLOCKS = "projection_block" in _PROJECTION_SRC
requires_stored_only = pytest.mark.skipif(
    not STORED_ONLY_READER,
    reason="R8 reverted the stored-only reader: there is no window and read() never answers from disk")
requires_producer_patch = pytest.mark.skipif(
    not PRODUCER_WRITES_CLOCKS,
    reason="the producer half of docs/ops/packets/inc-ovw-20261114/overview_projection.patch is not applied to "
           "scripts/lib/overview_projection.py (held by the R8 fold)")
requires_reader_patch = pytest.mark.skipif(
    not READER_CARRIES_CLOCKS,
    reason="the reader half of docs/ops/packets/inc-ovw-20261114/overview_projection.patch is not applied to "
           "scripts/lib/overview_projection.py (held by the R8 fold)")


def shipped_patch_window() -> float:
    """The last-good window the delivered patch installs, read out of the patch itself."""
    window = C.patched_window(ROOT)
    assert window is not None, (
        f"{C.PATCH_REL} is missing or no longer sets LAST_GOOD_MAX_S: the stored-only reader keeps the incident's "
        f"window")
    return window


# ── fixtures: the real config, read once ────────────────────────────────────────────────────────────────────────
def _registry() -> list[dict]:
    return json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]


def _allowlist() -> list[dict]:
    return json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]


@pytest.fixture(scope="module")
def row() -> dict:
    return C.overview_row(ROOT, _registry())


@pytest.fixture(scope="module")
def entry() -> dict:
    return C.allowlist_entry(ROOT, _allowlist())


@pytest.fixture(scope="module")
def contract() -> dict:
    return C.contract(ROOT)


# ── 1. one owner, and the three schedule homes agree ────────────────────────────────────────────────────────────
def test_exactly_one_registry_row_owns_the_lane():
    rows = [r for r in _registry() if r.get("lane_id") == C.LANE_ID]
    assert len(rows) == 1, f"{len(rows)} rows for {C.LANE_ID}: a second row is a second scheduler"
    assert rows[0]["state"] == "ACTIVE"


def test_cadence_cadence_slots_and_dispatch_cron_are_the_same_set(row):
    sched = row["scheduler"]
    dispatch = row["dispatch"]
    assert isinstance(sched.get("cadence_slots"), list) and len(sched["cadence_slots"]) == 3
    assert set(sched["cadence_slots"]) == set(dispatch["cron"])
    assert set(sched.get("due_schedules") or []) == set(dispatch["cron"])
    joined = [p.strip() for p in sched["cadence"].split(" + ")]
    assert set(joined) == set(dispatch["cron"])
    assert C.declared_schedules(row) == tuple(sorted(dispatch["cron"]))


def test_active_days_is_every_day_of_the_week(row):
    assert sorted(row["active_days"]) == [0, 1, 2, 3, 4, 5, 6], (
        "heartbeat_watch.classify marks a weekday outside active_days SILENT_OK; a missing day blinds the watcher")


def test_expected_cadence_hours_is_the_measured_max_gap_not_the_in_hours_cadence(row, contract):
    assert row["expected_cadence_hours"] * 3600 == pytest.approx(contract["max_gap_s"], abs=0.5)
    assert row["expected_cadence_hours"] > 0.5, "the lane no longer claims a 1-minute 24/7 cadence it does not run"


# ── 2. the calendar: every minute of five weeks ────────────────────────────────────────────────────────────────
WEEK_NAMES = [name for name, _a, _b in C.REFERENCE_WEEKS]


@pytest.mark.parametrize("name", WEEK_NAMES)
def test_week_has_no_schedule_hole_and_covers_every_existing_local_hour(contract, name):
    week = contract["weeks"][name]
    assert week["fires"] > 5000, f"{name}: only {week['fires']} admissions in a week"
    assert week["hours_without_a_fire"] == [], f"{name}: hours with no admission {week['hours_without_a_fire']}"
    holes = [g for g in week["gaps_over_interval"] if not g["fold"]]
    assert holes == [], f"{name}: gaps longer than the period cadence that are not a DST fold: {holes}"
    for gap in week["gaps_over_interval"]:
        assert gap["gap_s"] <= 3600 + gap["expected_s"], f"{name}: a fold gap larger than one hour: {gap}"


def test_the_only_gap_over_cadence_in_five_weeks_is_the_fall_back_fold(contract):
    over = {name: contract["weeks"][name]["gaps_over_interval"] for name in WEEK_NAMES}
    assert over["plain"] == over["thanksgiving"] == over["christmas"] == over["spring_forward"] == []
    folds = over["fall_back"]
    assert len(folds) == 1, folds
    assert folds[0]["fold"] is True
    assert folds[0]["gap_s"] == 3900.0
    assert "2026-11-01T01:55" in folds[0]["from_local"]
    assert contract["max_gap_s"] == 3900.0 and contract["max_gap_week"] == "fall_back"


def test_spring_forward_missing_hour_is_not_reported_as_a_hole(contract):
    week = contract["weeks"]["spring_forward"]
    assert "2027-03-14T02" not in week["hours_without_a_fire"]
    assert week["max_gap_s"] <= 300.0, "the coalesced 02:xx hour must cost no more than one 5-minute step"


# ── 3. admission: the real predicates, every slot, plus a minute-by-minute compute_due pass ────────────────────
def test_no_admission_gate_reads_a_clock_except_the_offpeak_gate():
    """The per-slot assertions below call each time-invariant gate ONCE and the clock-dependent one per slot.

    That split is only honest if it is true, so it is asserted: a future gate that starts reading ``now`` would
    have to take it as a parameter, and this test turns red before the suite starts asserting the wrong thing.
    """
    for fn in (D.dispatch_eligible, D.parse_dispatch_block, E.validate_entry):
        params = set(inspect.signature(fn).parameters)
        assert not (params & {"now", "at", "instant", "when"}), f"{fn.__name__} takes a clock: {params}"
    params = set(inspect.signature(E.offpeak_verdict).parameters)
    assert "now" in params and "env" in params


def test_every_slot_is_admitted_by_the_real_gates(row, entry):
    block = D.parse_dispatch_block(row)          # raises DispatchBlockError when malformed
    assert block is not None and block.mode == "live"
    assert D.validate_dispatch_block(row) == []
    assert L.validate_row(row) == []
    eligible, reason = D.dispatch_eligible(row)
    assert eligible is True, reason
    assert E.validate_entry(entry) is None
    assert entry["market_gate"] is False, "a market-hours gate would refuse every off-hours slot"
    assert entry.get("offpeak_gate") is None, "an off-peak gate would refuse live runs outside its window"
    policy = C.retry_policy(row, ROOT)
    assert policy["max_attempts"] >= 1 and policy["catchup_min"] >= 1


def test_offpeak_gate_never_refuses_this_lane_over_any_slot(entry, contract):
    for name in WEEK_NAMES:
        week = contract["weeks"][name]
        start = datetime.fromisoformat(week["start"])
        stop = datetime.fromisoformat(week["end"])
        for at in C.fires(contract["schedules"], start, stop)[::37]:   # every 37th slot: ~170 samples/week
            if at.minute == 0:
                continue  # the top of the hour is covered by the next test
            verdict = E.offpeak_verdict(entry, "live", env={}, now=at)
            assert verdict is None, f"{name} {at.isoformat()}: off-peak gate refuses a live run: {verdict}"


def _run_store():
    """An empty run store: compute_due treats every slot as never attempted, which is the worst case for a
    "was it refused?" question. None is the documented empty store."""
    return None


@pytest.mark.parametrize("day, hours", [
    ("2026-11-10", [3, 4, 20, 21]),      # a plain Tuesday: the 03:xx/04:00 and 20:59/21:00 period seams
    ("2026-11-14", [0, 1, 12, 23]),      # a Saturday: no weekday expression covers it at all
    ("2026-11-01", [0, 1, 2, 3]),        # the fall-back night
    ("2027-03-14", [1, 2, 3]),           # the spring-forward night
])
def test_compute_due_admits_the_lane_every_minute_across_the_seams(row, entry, day, hours, monkeypatch):
    # The relay lane list is a DEPLOYMENT env, not a clock: unset, compute_due refuses to downgrade a live lane
    # (code relay_live_lanes_missing) rather than silently running it as dry-run. Named in the READY as a gate
    # outside the calendar, discharged in production by the relay's own environment.
    monkeypatch.setenv("TRADEAI_N8N_RELAY_LIVE_LANES", row["lane_id"])
    allow = {row["lane_id"]: entry}
    policies = n8n_retry_policy.load_policies()
    seen_slots: set[str] = set()
    for hour in hours:
        for minute in range(60):
            now = datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00").replace(tzinfo=TZ)
            response = n8n_due.compute_due([row], allow, policies, _run_store(), now)
            assert response["errors"] == [], f"{now.isoformat()}: {response['errors']}"
            lane_errors = [e for e in response["errors"] if e.get("lane_id") == row["lane_id"]]
            assert lane_errors == [], f"{now.isoformat()}: admission error {lane_errors}"
            mine = [i for i in response["items"] if i["lane_id"] == row["lane_id"]]
            held = [h for h in response["held"] if h["lane_id"] == row["lane_id"]]
            assert mine or held, f"{now.isoformat()}: the lane is neither due nor held - a silent hole"
            for item in mine:
                seen_slots.add(item["slot_local"])
                assert item["mode"] == "live"
    # across those hours the dispatcher must have named many distinct slots, not one stuck catch-up slot
    assert len(seen_slots) >= len(hours) * 4, f"only {len(seen_slots)} distinct slots admitted: {sorted(seen_slots)[:5]}"


# ── 4. the contract inequality ─────────────────────────────────────────────────────────────────────────────────
def test_last_good_window_covers_gap_plus_retries_plus_dispatch_delay(contract):
    """The window this deliverable ships, judged by the floor this tree derives.

    The constant lives in a file this deliverable does not own, so it travels as a patch. Judging the TREE's
    constant here would make the test a property of the fold order; judging the patch's constant makes it a
    property of the fix, on R7 and on R8 alike.
    """
    window = shipped_patch_window()
    assert contract["floor_s"] == (
        contract["max_gap_s"] + contract["retry"]["retry_span_s"] + contract["dispatch_delay_s"])
    assert window > contract["floor_s"], f"the shipped window {window:.0f} s <= the derived floor"
    assert window == 5400.0, "90 minutes: the next whole minute above the 5040 s floor"
    assert window - contract["floor_s"] >= 300.0, "less than one 5-minute slot of margin"
    # the reviewer's narrower retry reading (scheduled backoffs only, attempts assumed instantaneous) must pass too
    assert window > contract["floor_minimal_s"]
    if STORED_ONLY_READER:
        # this tree carries the constant: the contract must describe its state truthfully either way
        assert contract["last_good_max_s"] in (window, 1800.0)
        assert contract["ok"] is (contract["last_good_max_s"] > contract["floor_s"])


def test_the_applied_patch_and_the_constant_agree(contract):
    """Once the patch is on the module, the window the release RUNS is the window the contract requires.

    Keyed on a different hunk of the same patch (the producer's clock copy), so a mutant that lowers only the
    constant cannot make this skip: it runs and fails. On a tree without the patch there is nothing applied yet.
    """
    if not (STORED_ONLY_READER and PRODUCER_WRITES_CLOCKS):
        pytest.skip("the patch is not applied to this tree's scripts/lib/overview_projection.py")
    assert contract["last_good_max_s"] == shipped_patch_window()
    assert contract["ok"] is True


def test_the_shipped_patch_quotes_the_derived_terms(contract):
    """The patch's comment must show its arithmetic with THIS registry's numbers, not remembered ones."""
    text = PATCH.read_text(encoding="utf-8")
    for term in (contract["max_gap_s"], contract["retry"]["retry_span_s"], contract["dispatch_delay_s"],
                 contract["floor_s"]):
        assert f"{term:.0f}" in text, f"{term:.0f} s is not quoted in the patch that derives the window from it"


def test_contract_terms_come_from_their_files_not_literals(contract, row, entry):
    assert contract["retry"]["policy"] == row["dispatch"]["retry_policy"]
    assert contract["retry"]["timeout_s"] == entry["timeout_s"]
    assert contract["dispatch_delay_s"] == 90.0  # n8n_coordination_gateway.DUE_MAX_SKEW_S
    from scripts.lib.n8n_coordination_gateway import DUE_MAX_SKEW_S
    assert contract["dispatch_delay_s"] == float(DUE_MAX_SKEW_S)
    pol = json.loads((ROOT / "config/n8n_retry_policies.json").read_text())["policies"][row["dispatch"]["retry_policy"]]
    assert contract["retry"]["max_attempts"] == pol["max_attempts"]
    assert contract["retry"]["retry_backoff_s"] == sum(pol["backoff_s"])


# ── 5. the health watcher tells the truth on a weekend ────────────────────────────────────────────────────────
def _observed(minutes_ago: float, now: datetime) -> dict:
    at = now - timedelta(minutes=minutes_ago)
    return {"last_output_at": at.isoformat(), "readable": True, "detail": "test"}


def test_heartbeat_classify_does_not_call_a_weekend_lane_silent_or_stale(row):
    from scripts import heartbeat_watch as HW

    sat = datetime.fromisoformat("2026-11-14T13:00:00").replace(tzinfo=TZ)
    verdict = HW.classify(row, _observed(5, sat), sat)
    assert verdict["verdict"] == "FRESH", verdict
    assert verdict["basis"].startswith("cadence:"), verdict["basis"]  # the kind-n8n fallback, sized by the real gap

    thu = datetime.fromisoformat("2026-11-12T11:00:00").replace(tzinfo=TZ)
    assert HW.classify(row, _observed(5, thu), thu)["verdict"] == "FRESH"

    missing = HW.classify(row, {"last_output_at": None, "readable": True, "detail": ""}, thu)
    assert missing["verdict"] == "STALE", missing

    old = HW.classify(row, _observed(24 * 60, sat), sat)
    assert old["verdict"] == "STALE", "a body a day old is not fresh on any day"


# ── 6. source clocks apart from built_at ──────────────────────────────────────────────────────────────────────
def _friday_body() -> dict:
    """A synthetic body shaped like the REAL one (read off a 2026-11-14 build: flat, not the wire envelope).

    Data clocks, session identity and the re-derived assembly stamps, in the places the producer actually writes
    them. If a source-clock path is invented rather than observed, ``test_every_declared_source_path_exists_in_a_
    real_shaped_body`` fails - that is the guard that stops this module guessing again.
    """
    return {
        "as_of": "2026-11-13T16:00:00-05:00",
        "data_as_of": "2026-11-13",
        "lookthrough_as_of": "2026-11-13",
        "last_repriced": "2026-11-13 16:00:00 ET",
        "truth": {"as_of": "2026-11-13T16:00:00-05:00"},
        "pricing": {"holdings_as_of": "2026-11-13T16:00:00-05:00", "last_repriced": "2026-11-13T16:00:00-05:00"},
        "clock_provenance": {
            "positions": {"as_of": "2026-11-13T15:59:00Z", "oldest_known_as_of": "2026-11-13T15:59:00Z",
                          "newest_known_as_of": "2026-11-13T16:00:00Z"},
            "position_list": {"as_of": "2026-11-12T15:24:00Z"},
            "quote": {"as_of": "2026-11-13T16:00:00-05:00"},
            "day_pnl": {"as_of": None},
            "valuation": {"as_of": "2026-11-13T21:30:00Z"},   # re-generated per read: LIVE, never source
        },
        "portfolio_aggregate": {"position_observation_oldest": "2026-11-13T15:59:00Z",
                                "position_observation_newest": "2026-11-13T16:00:00Z"},
        "trade_ai": {"vix_observation_time": "2026-11-13T16:15:00-05:00"},
        "journal": {"last_ingested_at": "2026-11-13T16:15:00-05:00", "last_close_date": "2026-11-10"},
        "market_session": {"latest_open_at": "2026-11-13T14:30:00Z", "latest_open_session": "2026-11-13",
                           "as_of": "2026-11-13T21:30:00Z"},       # resolved per build: LIVE
        "observation": {"snapshot_computed_at": "2026-11-13T21:30:00Z"},
        "measures": {"generated_at": "2026-11-13T21:30:00Z"},
        "paper": {"as_of": "2026-11-13T21:30:00Z", "age_hours": 0.0},
    }


def test_every_declared_source_path_exists_in_a_real_shaped_body():
    """No invented paths: the first draft of this module named ``data.portfolio.as_of``, which the body never had,
    and recorded all 21 clocks as absent - a gate would then have refused a healthy release."""
    body = _friday_body()
    clocks = C.source_clocks(body)
    unresolved = [p for p in C.SOURCE_CLOCK_PATHS
                  if p not in clocks["clocks"] and p not in clocks["null"]]
    assert unresolved == [], f"declared source clocks that are neither carried nor null: {unresolved}"
    assert len(clocks["clocks"]) >= 15, clocks["absent"]
    live = [p for p in C.LIVE_CLOCK_PATHS if p not in clocks["live_excluded"]]
    assert live == [], f"declared live clocks that are not in a real-shaped body: {live}"


def test_source_clocks_are_the_data_clocks_and_the_assembly_clock_is_excluded():
    clocks = C.source_clocks(_friday_body())
    assert clocks["clocks"]["as_of"] == "2026-11-13T16:00:00-05:00"
    assert clocks["clocks"]["data_as_of"] == "2026-11-13"
    assert clocks["clocks"]["journal.last_close_date"] == "2026-11-10"
    for assembly in ("market_session.as_of", "observation.snapshot_computed_at", "measures.generated_at",
                     "paper.as_of", "clock_provenance.valuation.as_of"):
        assert assembly not in clocks["clocks"], f"{assembly} is re-derived per build and must not read as source"
        assert assembly in clocks["live_excluded"]
    # a declared path the read did not carry is recorded as absent, never invented
    bare = _friday_body()
    del bare["lookthrough_as_of"]
    assert "lookthrough_as_of" in C.source_clocks(bare)["absent"]
    # and a field that EXISTS but is null is a declared gap, not the same fact as a missing field
    assert "clock_provenance.day_pnl.as_of" in C.source_clocks(_friday_body())["null"]


@requires_producer_patch
def test_a_weekend_rebuild_keeps_fridays_source_clocks_and_advances_only_built_at(tmp_path):
    from scripts.lib import overview_projection as OP

    path = tmp_path / "overview_projection.json"
    body = _friday_body()
    fri = datetime.fromisoformat("2026-11-13T21:30:00Z").timestamp()      # Friday 16:30 ET
    sat = datetime.fromisoformat("2026-11-14T18:00:00Z").timestamp()      # Saturday 13:00 ET
    first = OP.build(lambda: body, path=path, identity="sha:test", clock=lambda: fri, state_dir=None)
    assert first["status"] == "ok", first
    friday_doc = json.loads(path.read_text())
    second = OP.build(lambda: body, path=path, identity="sha:test", clock=lambda: sat, state_dir=None)
    assert second["status"] == "ok", second
    saturday_doc = json.loads(path.read_text())

    assert saturday_doc["built_at"] != friday_doc["built_at"]
    assert saturday_doc["built_at_epoch"] > friday_doc["built_at_epoch"]
    assert saturday_doc["source_clocks"] == friday_doc["source_clocks"], (
        "a Saturday rebuild re-stamped a source clock: the page would claim Friday's data is Saturday's")
    assert saturday_doc["source_clocks"]["clocks"], "no source clock recorded at all"


@requires_producer_patch
def test_a_no_change_build_keeps_every_source_clock(tmp_path):
    from scripts.lib import overview_projection as OP

    path = tmp_path / "overview_projection.json"
    body = _friday_body()
    t0 = datetime.fromisoformat("2026-11-13T21:31:00Z").timestamp()
    OP.build(lambda: body, path=path, identity="sha:test", clock=lambda: t0, state_dir=None)
    first = json.loads(path.read_text())["source_clocks"]
    t1 = t0 + 300
    OP.build(lambda: body, path=path, identity="sha:test", clock=lambda: t1, state_dir=None)
    second = json.loads(path.read_text())["source_clocks"]
    assert second == first


@requires_producer_patch
def test_a_changed_data_clock_is_carried_not_hidden(tmp_path):
    """The other direction: when the store DOES advance, the document says so. (Teeth for the pair above.)"""
    from scripts.lib import overview_projection as OP

    path = tmp_path / "overview_projection.json"
    body = _friday_body()
    t0 = datetime.fromisoformat("2026-11-13T21:31:00Z").timestamp()
    OP.build(lambda: body, path=path, identity="sha:test", clock=lambda: t0, state_dir=None)
    moved = _friday_body()
    moved["as_of"] = "2026-11-16T16:00:00-05:00"
    OP.build(lambda: moved, path=path, identity="sha:test", clock=lambda: t0 + 300, state_dir=None)
    doc = json.loads(path.read_text())
    assert doc["source_clocks"]["clocks"]["as_of"] == "2026-11-16T16:00:00-05:00"


# ── 7. the reader never computes; missing is UNKNOWN with null numbers ────────────────────────────────────────
def _write_projection(path: Path, *, built_at: float, identity: str = "sha:test", status: str = "ok") -> None:
    doc = {"schema": "OverviewProjection@v1", "status": status, "started_at_epoch": built_at - 1.0,
           "built_at_epoch": built_at, "built_at": datetime.fromtimestamp(built_at, tz=UTC).isoformat(),
           "started_at": datetime.fromtimestamp(built_at - 1.0, tz=UTC).isoformat(), "build_ms": 1000,
           "code_identity": identity, "inputs": {}, "source_clocks": C.source_clocks(_friday_body()), "body": _friday_body()}
    path.write_text(json.dumps(doc))


@requires_reader_patch
def test_reader_serves_a_fresh_body_with_its_source_clocks(tmp_path, contract):
    from scripts.lib import overview_projection as OP

    path = tmp_path / "overview_projection.json"
    now = datetime.fromisoformat("2026-11-13T21:30:00Z").timestamp()
    _write_projection(path, built_at=now - 10)
    body, meta = OP.read(path, identity="sha:test", invalidated_at=None, now=now)
    assert body is not None and meta["stale"] is False and meta["reason"] is None
    assert body["_projection"]["built_at"]
    assert body["_projection"]["source_clocks"]["clocks"]["as_of"] == "2026-11-13T16:00:00-05:00"


@requires_stored_only
@pytest.mark.parametrize("case", ["missing", "corrupt", "not_ok", "expired", "future"])
def test_reader_names_every_unknown_state_and_never_returns_a_number(tmp_path, contract, case):
    from scripts.lib import overview_projection as OP

    path = tmp_path / "overview_projection.json"
    now = datetime.fromisoformat("2026-11-12T18:00:00Z").timestamp()
    if case == "missing":
        pass
    elif case == "corrupt":
        path.write_text("{not json")
    elif case == "not_ok":
        _write_projection(path, built_at=now - 5, status="failed")
    elif case == "expired":
        _write_projection(path, built_at=now - (contract["last_good_max_s"] + 1))
    elif case == "future":
        _write_projection(path, built_at=now + 60)
    body, meta = OP.read(path, identity="sha:test", invalidated_at=None, now=now)
    assert body is None, f"{case}: a body was served"
    assert meta["source"] == "none"
    assert meta["reason"] in {"missing", "corrupt", "not_ok", "expired", "clock_skew"}, meta


@requires_stored_only
def test_serve_never_computes(tmp_path, monkeypatch):
    from scripts.lib import overview_projection as OP

    path = tmp_path / "overview_projection.json"
    monkeypatch.setenv(OP.PATH_ENV, str(path))
    path.write_text("{}")  # present but not a projection: the worst case for "does it fall back?"
    calls: list[int] = []

    def compute():  # pragma: no cover - it must never run
        calls.append(1)
        return {"ok": True, "data": {}}

    body = OP.serve(compute, path=path, identity="sha:test", invalidated_at_fn=lambda: None, now=1.0)
    assert calls == [], "serve() called the compute callable: the reader is not stored-only"
    assert body["status"] == "UNKNOWN" or body.get("ok") is not True
    assert body["gap"]["reason"] == "corrupt" and body["gap"]["next_action"]


# ── 8. nothing else writes the projection ────────────────────────────────────────────────────────────────────
def test_the_only_writer_is_the_dispatcher_row():
    """Every file in the repo that names the producer, pinned as a set: a new cron line, systemd unit or agent
    loop that names it turns this red. (Re-run of the 14:46 ET writer inventory, read-only.)"""
    needle = "build_overview_projection.py"
    hits: set[str] = set()
    for base in ("config", "scripts", "systemd", "ops"):
        root = ROOT / base
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix in {".pyc", ".log"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if needle in text:
                hits.add(str(path.relative_to(ROOT)))
    allowed = {
        "config/lane_registry.json",
        "config/n8n_run_allowlist.json",
        "config/n8n_health_contracts.json",
        "scripts/build_overview_projection.py",
        "scripts/lib/overview_projection.py",
        "scripts/lib/overview_lane_contract.py",
        "scripts/desk_truth_monitor.py",
        "scripts/ops/ccv3_audit_remeasure.py",
        "scripts/check_overview_cutover.py",
    }
    unexpected = sorted(hits - allowed)
    assert unexpected == [], f"new writers/references of the producer: {unexpected}"
    # and no crontab/systemd unit anywhere in the tree schedules it
    for path in list((ROOT / "config").rglob("*cron*")) + list((ROOT / "systemd").rglob("*")) \
            if (ROOT / "config").exists() else []:
        if path.is_file() and needle in path.read_text(encoding="utf-8", errors="ignore"):
            raise AssertionError(f"{path} schedules {needle}: a second scheduler")

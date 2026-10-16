"""Process consolidation cohort 2 (operator 2026-10-16): Hermes learning consumers fire on VERIFIED learning.

discovery_yield_builder and tag_lift_discovery read Hermes outcome learning, which runs 10:50-11:35 ET since
2026-08-21, from an overnight clock (03:45 / 03:50, since 2026-10-11 the 02:20 hermes_overnight night stage), so
every consumption read ~15-17 h old learning. Cohort 2:

1. Event trigger: registry row hermes-discovery-yield-on-learning (shadow, dry_run) carries run_done on
   hermes-learning-outcome-learning with require_verdict produced/empty_allowed (cohort-1 path). The tag-lift event
   lane is PROPOSED only: it reaches broker code transitively through db_adapter and the capability baseline is
   frozen to the operator's DD01 ruling, so it needs an operator ruling first (config event_lane_blocked).
2. Watermark guard: scripts/lib/learning_watermark.py — each consumer records the learning watermark it consumed and
   refuses to consume it twice, whichever trigger fired.
3. Clock fallback: the night-stage step (no flag = clock) no-ops with a recorded reason on an already-consumed
   watermark and runs on a newer (stale-consumed) one or past the staleness ceiling.
4. Report: scripts/report_learning_watermark.py measures input age at consumption from step receipts.

Hermetic: tmp project root, state root and ledger (env monkeypatched), frozen clocks; the consumers' compute paths
are monkeypatched, so no DB, no provider, no send, no live ledger.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import report_learning_watermark as REP  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import learning_watermark as LW  # noqa: E402
from scripts.lib import n8n_due as D  # noqa: E402
from scripts.lib import n8n_retry_policy as RP  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402

POLICIES = RP.load_policies(ROOT / "config" / "n8n_retry_policies.json")
REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ALLOW = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((ROOT / "config" / "pipelines" / "hermes_overnight.json").read_text(encoding="utf-8"))
CFG = LW.load_config()
UP = "hermes-learning-outcome-learning"
EVENT_LANES = {"hermes-discovery-yield-on-learning": "hermes-discovery-yield-builder"}
BLOCKED_EVENT_LANE = "hermes-tag-lift-on-learning"
NIGHT_STEP = {"hermes-discovery-yield-builder": "discovery_yield_builder",
              "hermes-tag-lift-discovery": "tag_lift_discovery"}
# Wednesday 2026-10-14 10:56 ET (EDT) = 14:56 UTC: the learn stage finished at 10:54 ET.
NOW = datetime(2026, 10, 14, 14, 56, tzinfo=timezone.utc)
LEARN_AT = datetime(2026, 10, 14, 14, 54, 22, tzinfo=timezone.utc)


@pytest.fixture(autouse=True, scope="module")
def _no_lib_import_leak():
    """The consumer scripts (run by path in production) import a few modules as bare ``lib.X``; this module imports
    ``scripts.lib.X``. Drop the bare twins this module added so later tests' single-identity check
    (scripts.lib.assert_single_import_identity) sees the session as it was."""
    before = {k for k in sys.modules if k.startswith("lib.") or k == "lib"}
    yield
    for k in [k for k in sys.modules if (k.startswith("lib.") or k == "lib") and k not in before]:
        del sys.modules[k]


def _reg(lane):
    return next(r for r in REGISTRY["lanes"] if r["lane_id"] == lane)


def _allow(lane):
    return next(e for e in ALLOW["lanes"] if e["lane_id"] == lane)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """tmp project root (logs/, state/hermes/), state root and ledger; the lib's ROOT points at the project root."""
    proj = tmp_path / "proj"
    (proj / "logs" / "pipelines" / "hermes_learning").mkdir(parents=True)
    (proj / "state" / "hermes" / "outcome_bus_history").mkdir(parents=True)
    state = tmp_path / "state"
    (state / "data" / "runtime").mkdir(parents=True)
    ledger_path = tmp_path / "ledger.sqlite"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setenv(LW.LEDGER_ENV, str(ledger_path))
    monkeypatch.delenv(LW.RUN_ID_ENV, raising=False)
    monkeypatch.setattr(LW, "ROOT", proj)
    ledger = CoordinationLedger(ledger_path)
    store = LedgerRunStore(ledger)
    yield {"proj": proj, "state": state, "ledger": ledger_path, "store": store}
    ledger.close()


def _step(proj, at: datetime, *, status="ok", dry=False, step="outcome_learning"):
    rec = {"schema": "PipelineStepReceipt@v1", "ts": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "pipeline": "hermes_learning",
           "stage": "learn", "id": step, "cron_line": 475, "status": status, "rc": 0, "ms": 1200, "timeout_s": 300,
           "dry_run": dry}
    with (proj / CFG["upstream"]["pipeline_step"]["steps_jsonl"]).open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


def _snapshot(proj, at: datetime):
    name = f"outcome_bus_{at.strftime('%Y-%m-%dT%H%M')}_ofb_deadbeef00.json"
    (proj / "state" / "hermes" / "outcome_bus_history" / name).write_text("{}")


def _cron_learning(proj, at: datetime):
    """A corroborated cron-runner completion: snapshot (outcome_feedback_agent) then the outcome_learning receipt."""
    _snapshot(proj, at - timedelta(seconds=2))
    _step(proj, at)


def _done(store, run_id, lane, mode, verdict, finished):
    store.request(run_id=run_id, lane_id=lane, mode=mode, requested_by="t", caller_id="t",
                  now=(finished - timedelta(minutes=2)).timestamp())
    receipt = {"run_id": run_id, "state": "RUN_DONE"}
    if verdict is not None:
        receipt["output_verdict"] = {"verdict": verdict}
    store._l._conn.execute(
        "UPDATE runs SET state = 'RUN_DONE', started_at = ?, finished_at = ?, receipt_json = ? WHERE run_id = ?",
        ((finished - timedelta(seconds=5)).isoformat(), finished.isoformat(), json.dumps(receipt), run_id))
    store._l._conn.commit()


def _receipt(state, consumer, started: datetime):
    doc = {"schema": "LaneRunReceipt@v1", "lane_id": consumer, "status": "ok", "started_at": started.isoformat(),
           "ok_at": (started + timedelta(seconds=1)).isoformat()}
    (state / "data" / "runtime" / f"{consumer}_last.json").write_text(json.dumps(doc))


def _due_keys(store, now=NOW):
    rows = [_reg(lane) for lane in EVENT_LANES]
    allow = {lane: _allow(lane) for lane in EVENT_LANES}
    return [i["idempotency_key"] for i in D.compute_due(rows, allow, POLICIES, store, now, source="event")["items"]]


def _guard(lane, trigger, now=NOW):
    g = LW.Guard(lane, trigger, cfg=CFG, now=now)
    g.evaluate()
    return g


# ── wiring: config, registry, allowlist, manifest ───────────────────────────────────────────────────────────────


def test_config_valid_and_shadow():
    assert LW.validate_config(CFG) == []
    assert CFG["event_trigger_state"] == "shadow"
    assert set(CFG["consumers"]) == set(NIGHT_STEP)
    assert CFG["upstream"]["lane_id"] == UP
    assert set(CFG["upstream"]["require_verdict"]) <= set(LD.TRIGGER_VERIFIED_VERDICTS)
    for consumer, c in CFG["consumers"].items():
        assert c["clock_guard"] == "enforce"
        if c["event_lane"] is not None:
            assert EVENT_LANES[c["event_lane"]] == consumer
    tl = CFG["consumers"]["hermes-tag-lift-discovery"]
    assert tl["event_lane"] is None and tl["event_lane_proposed"] == BLOCKED_EVENT_LANE
    assert "OPERATOR DECISION" in tl["event_lane_blocked"]


def test_blocked_tag_lift_event_lane_is_not_wired_and_baseline_not_grown():
    assert BLOCKED_EVENT_LANE not in {r["lane_id"] for r in REGISTRY["lanes"]}
    assert BLOCKED_EVENT_LANE not in {e["lane_id"] for e in ALLOW["lanes"]}
    base = json.loads((ROOT / "config" / "n8n_lane_capability_baseline.json").read_text(encoding="utf-8"))
    assert BLOCKED_EVENT_LANE not in base["lanes"]
    assert "hermes-discovery-yield-on-learning" not in base["lanes"]      # the yield builder reaches no broker code


@pytest.mark.parametrize("lane", sorted(EVENT_LANES))
def test_event_lane_registry_row_is_a_verified_run_done_shadow(lane):
    row = _reg(lane)
    block = LD.parse_dispatch_block(row)
    assert block.mode == "dry_run" and row["scheduler"]["stage"] == "shadow"
    assert row["scheduler"]["kind"] == "n8n" and row["scheduler"]["expression"] == LD.DISPATCHER_EXPRESSION
    (trig,) = block.triggers
    assert trig.source == "run_done" and trig.lane_id == UP
    assert trig.require_verdict == tuple(CFG["upstream"]["require_verdict"])
    eligible, why = LD.dispatch_eligible(row, allowlist_argv=None)
    assert eligible, why
    # the event watermark is the consumer's own LaneRunReceipt (the one the clock run writes too)
    assert row["output_signal"]["path"] == f"data/runtime/{EVENT_LANES[lane]}_last.json"
    consumer_row = _reg(EVENT_LANES[lane])
    assert consumer_row["state"] == "RETIRED" and "dispatch" not in consumer_row    # absorbed row unchanged


@pytest.mark.parametrize("lane", sorted(EVENT_LANES))
def test_event_lane_allowlist_is_shadow_only(lane):
    e = _allow(lane)
    assert e["live_arg"] is None and e["dry_run_arg"] == ["--dry-run"]
    assert e["command"][-2:] == ["--learning-watermark", "event"]
    assert e["output_signal"] == _reg(lane)["output_signal"]["path"]
    assert not any(n for n in e["env_names"] if any(f in n for f in LD.BROKER_CREDENTIAL_ENV_FRAGMENTS))


def test_clock_is_the_unchanged_night_step_and_defaults_to_the_clock_guard():
    steps = {s["id"]: s for s in MANIFEST["stages"]["night"]["steps"]}
    for consumer, sid in NIGHT_STEP.items():
        assert "--learning-watermark" not in steps[sid]["command"]      # verbatim cron command (C1 equivalence)
        assert steps[sid]["command"] in steps[sid]["cron_line_verbatim"]
        g = LW.Guard(consumer, None, cfg=CFG)
        assert g.trigger == "clock" and g.enabled


def test_ledger_path_matches_the_gateway(monkeypatch):
    from scripts import n8n_coordination_gateway as GW
    for env in ({}, {"TRADEAI_STATE_ROOT": "/x/state"}, {LW.LEDGER_ENV: "/y/l.sqlite", "TRADEAI_STATE_ROOT": "/x"}):
        assert LW.default_ledger_path(env) == GW.default_ledger_path(env)


# ── 1. no fire on an unverified upstream ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("verdict", ["no_rule", "declared_not_enforced", "dry_run_exempt", None])
def test_due_no_fire_on_unverified_upstream(env, verdict):
    _done(env["store"], "p:hermes-learning:x", UP, "live", verdict, LEARN_AT)
    assert _due_keys(env["store"]) == []


@pytest.mark.parametrize("verdict", ["produced", "empty_allowed"])
def test_due_fires_the_event_lane_on_verified_upstream(env, verdict):
    _receipt(env["state"], "hermes-discovery-yield-builder", LEARN_AT - timedelta(hours=8, minutes=34))  # 02:20 ET
    _done(env["store"], "p:hermes-learning:x", UP, "live", verdict, LEARN_AT)
    assert _due_keys(env["store"]) == ["e:hermes-discovery-yield-on-learning:dry_run:20261014T1054"]


def test_guard_event_refuses_unverified_upstream(env):
    _done(env["store"], "p:hermes-learning:x", UP, "live", "dry_run_exempt", LEARN_AT)
    _step(env["proj"], LEARN_AT)                                   # exit-0 receipt with NO corroborating artifact
    g = _guard("hermes-discovery-yield-builder", "event")
    assert not g.decision.run and g.decision.reason == "upstream_unverified"
    wm, why = LW.current_watermark(CFG, now=NOW)
    assert wm is None and why == "upstream_unverified"


def test_dry_run_upstream_rows_never_make_a_watermark(env):
    _done(env["store"], "p:hermes-learning:x", UP, "dry_run", "produced", LEARN_AT)   # ledger_modes = live only
    _step(env["proj"], LEARN_AT, dry=True)
    _snapshot(env["proj"], LEARN_AT)
    wm, why = LW.current_watermark(CFG, now=NOW)
    assert wm is None and why == "upstream_missing"


# ── 2. missing upstream: no fire plus a reason ──────────────────────────────────────────────────────────────────


def test_missing_upstream_no_fire_with_reason(env):
    assert _due_keys(env["store"]) == []
    g = _guard("hermes-tag-lift-discovery", "event")
    assert not g.decision.run and g.decision.reason == "upstream_missing"
    assert "WOULD NO-OP reason=upstream_missing" in g.line(dry_run=True)


def test_unreadable_ledger_is_a_reason_not_a_crash(env, monkeypatch):
    env["ledger"].unlink()
    env["ledger"].mkdir()                                          # a directory where the sqlite file should be
    wm, why = LW.current_watermark(CFG, now=NOW)
    assert wm is None and why.startswith("reader_error:ledger:")
    d = LW.decide("hermes-tag-lift-discovery", "clock", wm, why, {}, CFG, NOW)
    assert d.run and d.reason == "clock_fallback_upstream_unreadable"


# ── 3. no double consumption across event plus clock ────────────────────────────────────────────────────────────


def test_event_consumption_makes_the_clock_a_recorded_noop(env):
    _done(env["store"], "p:hermes-learning:x", UP, "live", "produced", LEARN_AT)
    ev = _guard("hermes-discovery-yield-builder", "event")
    assert ev.decision.run and ev.decision.reason == "new_watermark"
    assert ev.decision.watermark["id"] == "n8n:p:hermes-learning:x"
    assert ev.decision.input_age_s == pytest.approx((NOW - LEARN_AT).total_seconds())
    path = ev.record_consumed()
    clock = _guard("hermes-discovery-yield-builder", "clock", now=NOW + timedelta(hours=15, minutes=24))  # 02:20
    assert not clock.decision.run and clock.decision.reason == "watermark_already_consumed_by_event"
    clock.record_skip()
    st = json.loads(path.read_text())
    assert st["consumed"]["by"] == "event" and st["last_decision"]["reason"] == "watermark_already_consumed_by_event"
    assert [d["consumed_now"] for d in st["decisions"]] == [True, False]
    # and the event cannot re-fire on it at due level: the consumer's receipt watermark covers the as_of
    _receipt(env["state"], "hermes-discovery-yield-builder", NOW)
    assert "e:hermes-discovery-yield-on-learning:dry_run:20261014T1054" not in _due_keys(env["store"],
                                                                                         NOW + timedelta(minutes=1))


def test_clock_consumption_makes_a_late_event_a_noop(env):
    _cron_learning(env["proj"], LEARN_AT)
    clock = _guard("hermes-tag-lift-discovery", "clock")
    assert clock.decision.run and clock.decision.watermark["source"] == "cron"
    clock.record_consumed()
    ev = _guard("hermes-tag-lift-discovery", "event", now=NOW + timedelta(minutes=30))
    assert not ev.decision.run and ev.decision.reason == "watermark_already_consumed_by_clock"


def test_older_watermark_is_not_consumed_after_a_newer_one(env):
    _cron_learning(env["proj"], LEARN_AT)
    g = _guard("hermes-tag-lift-discovery", "clock")
    g.record_consumed()
    # a stale source surfaces an OLDER verified completion with a different id (e.g. only yesterday's ledger row)
    old = LW.Watermark(id="n8n:older", at=(LEARN_AT - timedelta(days=1)).isoformat(), source="n8n",
                       verdict="produced", evidence="t")
    st = LW.load_state(LW.state_path("hermes-tag-lift-discovery", CFG))
    d = LW.decide("hermes-tag-lift-discovery", "event", old, "verified", st, CFG, NOW)
    assert not d.run and d.reason == "watermark_not_newer"


# ── 4. a stale watermark makes the clock fallback run ───────────────────────────────────────────────────────────


def test_stale_consumed_watermark_makes_the_clock_run(env):
    _cron_learning(env["proj"], LEARN_AT - timedelta(days=1))
    first = _guard("hermes-discovery-yield-builder", "clock", now=NOW - timedelta(hours=12))
    assert first.decision.run
    first.record_consumed()
    _cron_learning(env["proj"], LEARN_AT)                           # today's learning: the consumed one is stale
    clock = _guard("hermes-discovery-yield-builder", "clock", now=NOW + timedelta(hours=15))
    assert clock.decision.run and clock.decision.reason == "new_watermark"
    assert clock.decision.consumed["at"] < clock.decision.watermark["at"]


def test_clock_runs_past_the_staleness_ceiling_even_on_the_same_watermark(env):
    _cron_learning(env["proj"], LEARN_AT)
    g = _guard("hermes-discovery-yield-builder", "clock")
    g.record_consumed()
    within = _guard("hermes-discovery-yield-builder", "clock", now=NOW + timedelta(hours=CFG["clock_stale_ceiling_h"] - 1))
    assert not within.decision.run
    past = _guard("hermes-discovery-yield-builder", "clock", now=NOW + timedelta(hours=CFG["clock_stale_ceiling_h"] + 1))
    assert past.decision.run and past.decision.reason == "stale_consumption_ceiling"
    ev = _guard("hermes-discovery-yield-builder", "event", now=NOW + timedelta(hours=CFG["clock_stale_ceiling_h"] + 1))
    assert not ev.decision.run                                       # the ceiling is a clock-only fallback


def test_clock_with_no_upstream_keeps_the_pre_cohort_behaviour(env):
    d = _guard("hermes-discovery-yield-builder", "clock").decision
    assert d.run and d.reason == "clock_fallback_upstream_missing"


def test_newest_source_wins_across_ledger_and_cron(env):
    _cron_learning(env["proj"], LEARN_AT - timedelta(minutes=30))
    _done(env["store"], "p:hermes-learning:x", UP, "live", "empty_allowed", LEARN_AT)
    wm, why = LW.current_watermark(CFG, now=NOW)
    assert why == "verified" and wm.id == "n8n:p:hermes-learning:x" and wm.verdict == "empty_allowed"


# ── the consumer scripts honour the guard ───────────────────────────────────────────────────────────────────────


def test_yield_builder_clock_noop_and_consume(env, monkeypatch, capsys):
    import hermes_discovery_yield_builder as YB
    calls = []
    monkeypatch.setattr(YB, "compute_yield_file", lambda apply=False: calls.append(apply) or {"entries": 3})
    monkeypatch.setattr("lib.lane_last_receipt.write_lane_receipt", lambda *a, **k: None)
    monkeypatch.setattr("scripts.lib.learning_watermark.ROOT", env["proj"])
    _cron_learning(env["proj"], LEARN_AT)
    assert YB.main(["--apply", "--json"]) in (0, None)               # night step argv: no flag = clock
    assert calls == [True]
    assert YB.main(["--apply", "--json"]) == 0                       # same watermark again: recorded no-op
    assert calls == [True]
    assert '"status": "watermark_noop"' in capsys.readouterr().out
    st = LW.load_state(LW.state_path("hermes-discovery-yield-builder", CFG))
    assert st["consumed"]["by"] == "clock" and st["last_decision"]["reason"] == "watermark_already_consumed_by_clock"


def test_yield_builder_event_dry_run_records_nothing(env, monkeypatch, capsys):
    import hermes_discovery_yield_builder as YB
    monkeypatch.setattr("scripts.lib.learning_watermark.ROOT", env["proj"])
    _cron_learning(env["proj"], LEARN_AT)
    assert YB.main(["--json", "--learning-watermark", "event", "--dry-run"]) == 0
    assert "WOULD RUN reason=new_watermark" in capsys.readouterr().err
    assert not LW.state_path("hermes-discovery-yield-builder", CFG).exists()


def test_event_trigger_refuses_when_the_config_is_unusable(env, monkeypatch):
    import hermes_discovery_yield_builder as YB
    monkeypatch.setattr("scripts.lib.learning_watermark.CONFIG_PATH", env["proj"] / "missing.json")
    assert YB.main(["--json", "--learning-watermark", "event", "--dry-run"]) == 1
    assert YB.main(["--json", "--dry-run"]) == 0                     # the clock keeps running unguarded


def test_tag_lift_event_noop_on_missing_upstream_and_clock_consumes(env, monkeypatch, capsys):
    import hermes_tag_lift_discovery as TL
    runs = []
    monkeypatch.setattr(TL.tag_lift, "run_discovery", lambda **k: runs.append(k) or {
        "dry_run": k["dry_run"], "tags_analyzed": 1, "weight_deltas_planned": 0, "weight_deltas_applied": 0,
        "candidates_planned": 0, "upserted": 0})
    monkeypatch.setattr("lib.lane_last_receipt.write_lane_receipt", lambda *a, **k: None)
    monkeypatch.setattr("scripts.lib.learning_watermark.ROOT", env["proj"])
    monkeypatch.setattr(sys, "argv", ["x", "--run", "--json", "--learning-watermark", "event"])
    assert TL.main() == 0 and runs == []
    assert "NO-OP reason=upstream_missing" in capsys.readouterr().err
    _cron_learning(env["proj"], LEARN_AT)
    monkeypatch.setattr(sys, "argv", ["x", "--run", "--json"])
    assert TL.main() == 0 and len(runs) == 1
    assert TL.main() == 0 and len(runs) == 1                         # no second weight-delta pass on one bus
    st = LW.load_state(LW.state_path("hermes-tag-lift-discovery", CFG))
    assert st["consumed"]["id"].startswith("cron:hermes_learning:learn:outcome_learning:")


# ── report: measured staleness ──────────────────────────────────────────────────────────────────────────────────


def test_report_measures_input_age_and_peak_skips(env):
    proj = env["proj"]
    (proj / "config" / "pipelines").mkdir(parents=True)
    (proj / "config" / "pipelines" / "hermes_overnight.json").write_text(json.dumps(MANIFEST))
    _cron_learning(proj, LEARN_AT - timedelta(days=1))
    night = proj / REP.NIGHT_STEPS_REL
    night.parent.mkdir(parents=True)
    at = LEARN_AT.replace(hour=6, minute=20, second=1)               # 02:20 ET the next morning... same day here
    lines = []
    for sid in ("discovery_yield_builder", "tag_lift_discovery"):
        lines.append(json.dumps({"schema": "PipelineStepReceipt@v1", "ts": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 "pipeline": "hermes_overnight", "stage": "night", "id": sid, "status": "ok",
                                 "rc": 0, "dry_run": False}))
    night.write_text("\n".join(lines) + "\n")
    (proj / "logs" / "hermes_tag_lift.log").write_text(f"{at.strftime('%Y-%m-%dT%H:%M:%SZ')} PEAK_SKIP gate=--gate-official\n")
    m = REP.measured_staleness(CFG, proj, NOW)
    yb = m["hermes-discovery-yield-builder"]
    assert yb["consumptions"] == 1
    assert yb["input_age_h_median"] == pytest.approx(round((at - LEARN_AT + timedelta(days=1)).total_seconds() / 3600, 2))
    tl = m["hermes-tag-lift-discovery"]
    assert tl["consumptions"] == 0 and tl["peak_skipped"] == 1

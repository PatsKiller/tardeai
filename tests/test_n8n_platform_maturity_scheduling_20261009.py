"""N8nPlatformMaturity@v1 dimensions 1-3 (registry truth, rationalization, scheduler coverage) — hermetic.

tmp_path root/proj, a fake runner for ``crontab -l`` / ``systemctl --user list-unit-files``, fixed ``now``.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))

from n8n_maturity import core  # noqa: E402
from n8n_maturity import dims_scheduling as ds  # noqa: E402

NOW = dt.datetime(2026, 10, 9, 20, 0, tzinfo=dt.timezone.utc)
REAL_CONFIG = json.loads((PROJ / "config" / "n8n_platform_maturity.json").read_text(encoding="utf-8"))
HOME = "/h/tester"  # probe env HOME — never the real home directory


def _config(dims=None, **top):
    """The real config file, with per-dimension keys and top-level keys overridden for the test."""
    cfg = copy.deepcopy(REAL_CONFIG)
    for d, kv in (dims or {}).items():
        cfg["dimensions"].setdefault(d, {}).update(kv)
    cfg.update(top)
    return cfg


CFG = _config()
SC = REAL_CONFIG["dimensions"]["scheduler_coverage"]


def _lane(lane_id, kind="cron", match=None, state="ACTIVE", signal="file_mtime", cadence=24.0, **kw):
    sched = {"kind": kind, "expression": "0 1 * * *" if kind == "cron" else (match or lane_id)}
    if match:
        sched["match"] = match
    row = {"lane_id": lane_id, "owner": "t", "scheduler": sched, "state": state,
           "expected_cadence_hours": cadence, "output_signal": {"kind": signal}}
    row.update(kw)
    return row


def _write(p: Path, obj) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
    return p


def _runner(crontab: str | None = None, timers: str | None = None, services: str | None = None, calls=None):
    def run(argv, timeout):
        if calls is not None:
            calls.append(list(argv))
        if argv[:2] == ["crontab", "-l"]:
            return (0, crontab, "") if crontab is not None else (1, "", "no crontab")
        if argv[:3] == ["systemctl", "--user", "list-unit-files"]:
            out = timers if "--type=timer" in argv else services
            return (0, out, "") if out is not None else (1, "", "no bus")
        return 1, "", "unexpected"
    return run


def _probe(tmp_path, runner, config=None):
    return core.Probe(root=tmp_path / "state", proj=tmp_path / "proj", now=NOW, env={"HOME": HOME},
                      config=config if config is not None else CFG, runner=runner)


def _registry(tmp_path, lanes, baseline=(), tranches=()):
    _write(tmp_path / "proj" / "config" / "lane_registry.json",
           {"lanes": lanes, "undeclared_baseline": list(baseline),
            "inherited_tranches": [{"lines": list(t)} for t in tranches]})


# ── 1. registry truth ──────────────────────────────────────────────────────────────────────────

CRON3 = ("0 1 * * * cd x && python scripts/a.py >> a.log\n"
         "5 2 * * * cd x && python scripts/b.py\n"
         "# 0 3 * * * python scripts/old.py  RETIRED 2026-10-01\n"
         "PATH=/usr/bin\n"
         "*/5 * * * * python scripts/c.py\n")
LINE_B = "5 2 * * * cd x && python scripts/b.py"
LINE_C = "*/5 * * * * python scripts/c.py"


def test_registry_truth_gate_pass_scores_8_plus_reverse(tmp_path):
    _registry(tmp_path, [_lane("a", match="scripts/a.py"), _lane("b", match="scripts/b.py"),
                         _lane("c", match="scripts/c.py"), _lane("orphan", match="scripts/gone.py")])
    r = ds.registry_truth(_probe(tmp_path, _runner(CRON3)))
    assert r["status"] == core.VERIFIED and r["gate"]["pass"] is True
    m = r["metrics"]
    assert (m["live_cron_lines"], m["lines_with_row"], m["baseline_size"]) == (3, 3, 0)
    assert (m["active_cron_rows"], m["active_cron_rows_present"]) == (4, 3)
    assert r["score"] == pytest.approx(8.0 + 2.0 * 3 / 4)


def test_registry_truth_perfect_is_10(tmp_path):
    _registry(tmp_path, [_lane("a", match="scripts/a.py"), _lane("b", match="scripts/b.py"),
                         _lane("c", match="scripts/c.py")])
    r = ds.registry_truth(_probe(tmp_path, _runner(CRON3)))
    assert r["score"] == 10.0 and r["gate"]["pass"]


def test_registry_truth_baseline_nonzero_fails_gate_and_scores_partial_progress(tmp_path):
    _registry(tmp_path, [_lane("a", match="scripts/a.py")], baseline=[LINE_B], tranches=[[LINE_C]])
    cfg = _config({"registry_truth": {"baseline_initial": 4}})
    r = ds.registry_truth(_probe(tmp_path, _runner(CRON3), cfg))
    m = r["metrics"]
    assert r["gate"]["pass"] is False
    assert (m["baseline_size"], m["lines_with_row"], m["lines_without_row"], m["undeclared_beyond_baseline"]) == (2, 1, 2, 0)
    # coverage 1/3 → 8/3; progress 1 - 2/4 = 0.5 → 4.0; mean
    assert r["score"] == pytest.approx(round((8.0 / 3 + 4.0) / 2, 2))


def test_registry_truth_one_line_without_row_fails_gate_even_with_empty_baseline(tmp_path):
    _registry(tmp_path, [_lane("a", match="scripts/a.py"), _lane("b", match="scripts/b.py")])
    r = ds.registry_truth(_probe(tmp_path, _runner(CRON3)))
    assert r["gate"]["pass"] is False
    assert r["metrics"]["undeclared_beyond_baseline"] == 1
    assert r["score"] < 8.0
    assert r["score"] == pytest.approx(round((8.0 * 2 / 3 + 8.0) / 2, 2))


def test_registry_truth_bare_schedule_expression_does_not_declare_a_line(tmp_path):
    # a row with only "0 1 * * *" and no match must not count as a row for the 01:00 line
    _registry(tmp_path, [{"lane_id": "x", "owner": "t", "scheduler": {"kind": "cron", "expression": "0 1 * * *"},
                          "state": "ACTIVE", "expected_cadence_hours": 24, "output_signal": {"kind": "none"}}])
    r = ds.registry_truth(_probe(tmp_path, _runner("0 1 * * * python scripts/a.py\n")))
    assert r["metrics"]["lines_with_row"] == 0


def test_registry_truth_missing_crontab_is_unverified(tmp_path):
    _registry(tmp_path, [_lane("a", match="scripts/a.py")])
    r = ds.registry_truth(_probe(tmp_path, _runner(None)))
    assert r["status"] == core.UNVERIFIED and r["score"] == 0.0 and r["gate"]["pass"] is False


def test_registry_truth_missing_registry_is_unverified(tmp_path):
    r = ds.registry_truth(_probe(tmp_path, _runner(CRON3)))
    assert r["status"] == core.UNVERIFIED and r["score"] == 0.0


def test_registry_truth_evidence_never_carries_crontab_text(tmp_path):
    _registry(tmp_path, [_lane("a", match="scripts/a.py")])
    r = ds.registry_truth(_probe(tmp_path, _runner(CRON3)))
    blob = json.dumps(r)
    assert "scripts/b.py" not in blob and "scripts/c.py" not in blob


# ── 2. rationalization ─────────────────────────────────────────────────────────────────────────

def _plan(tmp_path, n_elim_cron=2, n_merge_cron=3):
    rows, cron_rows = [], []
    line = 100
    for i in range(n_elim_cron):
        rows.append({"kind": "cron", "id": f"L{line}", "name": f"elim{i}.py", "recommendation": "ELIMINATE"})
        cron_rows.append({"line": line, "cmd": f"cd x && python scripts/elim{i}.py >> e.log 2>&1  # note"})
        line += 1
    for i in range(n_merge_cron):
        rec = "MERGE-into P01" if i % 2 else "CONSOLIDATE-into P02"
        rows.append({"kind": "cron", "id": f"L{line}", "name": f"merge{i}.py", "recommendation": rec})
        cron_rows.append({"line": line, "cmd": f"cd x && python scripts/merge{i}.py"})
        line += 1
    rows += [
        {"kind": "timer", "id": "t1.timer", "name": "t1.timer", "recommendation": "ELIMINATE"},
        {"kind": "service", "id": "s1.service", "name": "s1.service", "recommendation": "ELIMINATE"},
        {"kind": "n8n_workflow", "id": "wfdead", "name": "bench", "recommendation": "ELIMINATE"},
        {"kind": "health_tick_step", "id": "slow-step", "name": "slow-step", "recommendation": "ELIMINATE"},
        {"kind": "cron", "id": "L999", "name": "keep.py", "recommendation": "KEEP on cron"},
    ]
    data = tmp_path / "proj" / "docs" / "implementation" / "n8n-maturity" / "data"
    _write(data / "F_rationalization.json", rows)
    _write(data / "cron_rows.json", cron_rows)
    _write(tmp_path / "proj" / "docs" / "implementation" / "n8n-parallel" / "workflows" /
           "active_workflows_snapshot.json", {"schema": "N8nActiveWorkflowSnapshot@v1", "workflows": [{"id": "wflive"}]})
    _write(tmp_path / "proj" / "config" / "health_tick_steps.json",
           {"steps": [{"step_id": "slow-step", "enabled": False}, {"step_id": "other"}]})
    return rows


def _pipeline_receipt(tmp_path, pipeline, stage, *, dry_run=False, status="ok", ts="2026-10-09T17:30:00Z"):
    _write(tmp_path / "state" / "data" / "runtime" / f"pipeline_{pipeline}_{stage}_last.json",
           {"schema": "PipelineRun@v1", "pipeline": pipeline, "stage": stage, "run_ts_utc": ts,
            "dry_run": dry_run, "executed_any": not dry_run, "overall_status": "dry_run" if dry_run else status})


RA_CFG = _config({"rationalization": {"r0_target": 6, "merged_target": 3, "merged_stretch": 6,
                                      "pipelines_live_target": 2, "pipelines_live_stretch": 4}})


def test_rationalization_gate_pass(tmp_path):
    _plan(tmp_path)
    _registry(tmp_path, [_lane("x", state="RETIRED")])
    for st in ("a", "b"):
        _pipeline_receipt(tmp_path, "after_close", st)
    _pipeline_receipt(tmp_path, "premarket", "premarket", dry_run=True)
    crontab = ("0 1 * * * cd x && python scripts/other.py\n"
               "# RETIRED 2026-10-09 n8n-cutover lane-a 0 1 * * * cd x && python scripts/elim0.py\n")
    runner = _runner(crontab, timers="t1.timer disabled enabled\n", services="other.service enabled enabled\n")
    r = ds.rationalization(_probe(tmp_path, runner, RA_CFG))
    m = r["metrics"]
    assert (m["plan_eliminate"], m["eliminated"], m["merged"], m["pipelines_live"]) == (6, 6, 3, 2)
    assert m["n8n_cutover_tagged_lines"] == 1 and m["registry_retired_rows"] == 1
    assert r["status"] == core.VERIFIED and r["gate"]["pass"] is True
    assert r["score"] == pytest.approx(8.0)
    assert "elim0.py" not in json.dumps(r["evidence"])


def test_rationalization_partial_progress_and_gate_fail(tmp_path):
    _plan(tmp_path)
    _pipeline_receipt(tmp_path, "after_close", "a")
    _pipeline_receipt(tmp_path, "after_close", "old", ts="2026-09-01T00:00:00Z")  # too old to count
    # elim1 + merge0 still live (trailing comment change must not hide elim1); t1 still enabled
    crontab = ("0 1 * * * cd x && python scripts/elim1.py >> e.log 2>&1  # edited comment\n"
               "0 2 * * * cd x && python scripts/merge0.py\n")
    runner = _runner(crontab, timers="t1.timer enabled enabled\n", services="")
    r = ds.rationalization(_probe(tmp_path, runner, RA_CFG))
    m = r["metrics"]
    assert (m["eliminated"], m["merged"], m["pipelines_live"]) == (4, 2, 1)
    assert r["gate"]["pass"] is False
    expected = (core.ratio_score(4, 6) + core.ratio_score(2, 3, top=6) + core.ratio_score(1, 2, top=4)) / 3
    assert r["score"] == pytest.approx(round(expected, 2))


def test_rationalization_without_plan_is_partial_with_unverified_parts(tmp_path):
    for st in ("a", "b"):
        _pipeline_receipt(tmp_path, "after_close", st)
    r = ds.rationalization(_probe(tmp_path, _runner("0 1 * * * x\n"), RA_CFG))
    assert r["status"] == core.PARTIAL and r["gate"]["pass"] is False
    assert r["score"] == pytest.approx(round(8.0 / 3, 2))
    assert any("plan data absent" in n for n in r["notes"])


def test_rationalization_no_evidence_at_all_is_unverified(tmp_path):
    r = ds.rationalization(_probe(tmp_path, _runner(None), RA_CFG))
    # pipelines sub-criterion is measurable (0 receipts) → PARTIAL with score 0, never a pass
    assert r["score"] == 0.0 and r["gate"]["pass"] is False and r["status"] in (core.PARTIAL, core.UNVERIFIED)


def test_rationalization_unreadable_units_are_unverifiable_not_eliminated(tmp_path):
    _plan(tmp_path)
    r = ds.rationalization(_probe(tmp_path, _runner("0 1 * * * x\n", timers=None, services=None), RA_CFG))
    assert r["metrics"]["eliminate_unverifiable"] == 2
    assert r["metrics"]["eliminated"] == 4


def test_rationalization_name_fallback_without_cron_rows(tmp_path):
    _plan(tmp_path)
    (tmp_path / "proj" / "docs" / "implementation" / "n8n-maturity" / "data" / "cron_rows.json").unlink()
    r = ds.rationalization(_probe(tmp_path, _runner("0 1 * * * python scripts/elim0.py\n", "", ""), RA_CFG))
    assert r["metrics"]["eliminated"] == 5  # elim0 still live by name
    assert any("matched by script name" in n for n in r["notes"])


# ── 3. scheduler coverage ──────────────────────────────────────────────────────────────────────

def _ledger(tmp_path, rows, create_runs=True):
    p = tmp_path / "state" / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    if create_runs:
        con.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, "
                    "requested_at TEXT, finished_at TEXT)")
        for i, (lane, mode, state, fin) in enumerate(rows):
            con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)", (f"r{i}", lane, mode, state, fin, fin))
    else:
        con.execute("CREATE TABLE events (k TEXT)")
    con.commit()
    con.close()


def _sc_lanes(n_n8n=3, n_cron=2):
    lanes = [_lane(f"n{i}", kind="n8n", match=f"scripts/n{i}.py", cadence=0.25) for i in range(n_n8n)]
    lanes += [_lane(f"c{i}", match=f"scripts/c{i}.py") for i in range(n_cron)]
    lanes += [_lane("alpaca-stop-manager-rth", match="scripts/alpaca_stop_manager.py --apply"),
              _lane("dof", match="dof.py", note="N6 retained on cron by operator decision"),
              _lane("recorder", match="microstructure_recorder.py"),     # 'order' inside a word: movable
              _lane("event-lane", kind="event"), _lane("old", state="RETIRED")]
    return lanes


def test_stay_behind_classifier_is_token_based_and_config_driven():
    get = lambda k: SC[k]  # noqa: E731
    assert ds.is_stay_behind(_lane("alpaca-stop-manager-rth"), get).startswith("token:")
    assert ds.is_stay_behind(_lane("recorder", match="microstructure_recorder.py"), get) is None
    assert ds.is_stay_behind(_lane("x", match="scripts/options_tick.py"), get) == "substring:options_tick"
    assert ds.is_stay_behind(_lane("x", note="Stays on cron (broker rail)"), get) == "note:stays on cron"
    custom = {**SC, "stay_lane_ids": ["x"]}
    assert ds.is_stay_behind(_lane("x"), lambda k: custom[k]) == "stay_lane_ids"


def test_scheduler_coverage_gate_pass(tmp_path):
    _registry(tmp_path, _sc_lanes())
    fresh = "2026-10-09T19:50:00+00:00"
    _ledger(tmp_path, [("n0", "live", "RUN_DONE", fresh), ("n1", "live", "RUN_SKIPPED_LOCK", fresh),
                       ("n2", "live", "RUN_DONE", fresh), ("n2", "dry_run", "RUN_DONE", fresh)])
    r = ds.scheduler_coverage(_probe(tmp_path, _runner()))
    m = r["metrics"]
    assert (m["schedulable_active_lanes"], m["stay_behind_lanes"], m["movable_lanes"]) == (8, 2, 6)
    assert (m["dispatcher_declared"], m["dispatcher_run_proven"]) == (3, 3)
    assert m["run_proven_fraction"] == 0.5 and r["gate"]["pass"] is False  # 3/6 < 60%


def test_scheduler_coverage_at_60_percent_passes(tmp_path):
    _registry(tmp_path, _sc_lanes(n_n8n=3, n_cron=0))  # movable: n0-n2 + recorder = 4 → need 3 (75%)
    fresh = "2026-10-09T19:50:00+00:00"
    _ledger(tmp_path, [(f"n{i}", "live", "RUN_DONE", fresh) for i in range(3)])
    r = ds.scheduler_coverage(_probe(tmp_path, _runner()))
    assert r["metrics"]["run_proven_fraction"] == 0.75
    assert r["gate"]["pass"] is True and r["status"] == core.VERIFIED and r["score"] >= 8.0


def test_scheduler_coverage_rest_unwatched_fails_gate(tmp_path):
    lanes = _sc_lanes(n_n8n=3, n_cron=0)
    lanes[-3]["output_signal"] = {"kind": "none"}   # recorder: movable, not dispatched, unwatched
    _registry(tmp_path, lanes)
    fresh = "2026-10-09T19:50:00+00:00"
    _ledger(tmp_path, [(f"n{i}", "live", "RUN_DONE", fresh) for i in range(3)])
    r = ds.scheduler_coverage(_probe(tmp_path, _runner()))
    assert r["metrics"]["watched_fraction"] == pytest.approx(2 / 3, abs=1e-4)
    assert r["gate"]["pass"] is False


def test_scheduler_coverage_stale_or_dry_runs_do_not_prove(tmp_path):
    _registry(tmp_path, _sc_lanes())
    _ledger(tmp_path, [("n0", "live", "RUN_DONE", "2026-10-01T00:00:00+00:00"),
                       ("n1", "dry_run", "RUN_DONE", "2026-10-09T19:50:00+00:00"),
                       ("n2", "live", "RUN_FAILED", "2026-10-09T19:50:00+00:00")])
    r = ds.scheduler_coverage(_probe(tmp_path, _runner()))
    assert r["metrics"]["dispatcher_run_proven"] == 0
    assert r["gate"]["pass"] is False


def test_scheduler_coverage_missing_runs_table_is_partial(tmp_path):
    _registry(tmp_path, _sc_lanes())
    _ledger(tmp_path, [], create_runs=False)
    r = ds.scheduler_coverage(_probe(tmp_path, _runner()))
    assert r["status"] == core.PARTIAL and r["gate"]["pass"] is False
    assert r["metrics"]["run_proven_fraction"] is None
    assert any("runs table unreadable" in n for n in r["notes"])


def test_scheduler_coverage_missing_ledger_is_partial(tmp_path):
    _registry(tmp_path, _sc_lanes())
    r = ds.scheduler_coverage(_probe(tmp_path, _runner()))
    assert r["status"] == core.PARTIAL
    assert any("ledger absent" in n for n in r["notes"])


def test_scheduler_coverage_missing_registry_is_unverified(tmp_path):
    r = ds.scheduler_coverage(_probe(tmp_path, _runner()))
    assert r["status"] == core.UNVERIFIED and r["score"] == 0.0


def test_collectors_table_and_read_only_commands(tmp_path):
    assert set(ds.COLLECTORS) == {"registry_truth", "rationalization", "scheduler_coverage"}
    _plan(tmp_path)
    _registry(tmp_path, _sc_lanes())
    calls: list = []
    p = _probe(tmp_path, _runner("0 1 * * * x\n", "", "", calls=calls))
    for fn in ds.COLLECTORS.values():
        fn(p)
    assert calls and all(core.is_read_only(c) for c in calls)


# ── review blockers: config-only thresholds, empty inputs never pass, read-only argv ──────────

def test_registry_truth_empty_crontab_is_unverified_not_full_coverage(tmp_path):
    _registry(tmp_path, [_lane("a", match="scripts/a.py")])
    for tab in ("", "# 0 1 * * * python scripts/a.py RETIRED\nPATH=/usr/bin\n"):
        r = ds.registry_truth(_probe(tmp_path, _runner(tab)))
        assert r["status"] == core.UNVERIFIED and r["score"] == 0.0 and r["gate"]["pass"] is False
        assert any("no live lines" in n for n in r["notes"])


def test_registry_truth_no_active_cron_rows_scores_gate_score_without_bonus(tmp_path):
    # non-ACTIVE cron rows declare every line, so the gate passes; but there is no ACTIVE kind-cron row, so
    # reverse is 0/0 → None (no bonus), never 1.0 → 10. (Since #1597 a row of another scheduler kind no longer
    # declares a crontab line, so PAUSED cron rows carry the declaration here.)
    lanes = [_lane(x, match=f"scripts/{x}.py", state="PAUSED") for x in ("a", "b", "c")]
    _registry(tmp_path, lanes)
    r = ds.registry_truth(_probe(tmp_path, _runner(CRON3)))
    assert r["gate"]["pass"] is True and r["metrics"]["active_cron_rows"] == 0
    assert r["metrics"]["reverse_coverage"] is None and r["score"] == pytest.approx(8.0)


def test_registry_truth_gate_score_from_config(tmp_path):
    _registry(tmp_path, [_lane("a", match="scripts/a.py"), _lane("b", match="scripts/b.py"),
                         _lane("c", match="scripts/c.py"), _lane("orphan", match="scripts/gone.py")])
    r = ds.registry_truth(_probe(tmp_path, _runner(CRON3), _config(gate_score=7.0)))
    assert r["score"] == pytest.approx(7.0 + 3.0 * 3 / 4, abs=0.01)


def test_rationalization_empty_crontab_does_not_read_plan_lines_as_gone(tmp_path):
    _plan(tmp_path)
    for st in ("a", "b"):
        _pipeline_receipt(tmp_path, "after_close", st)
    r = ds.rationalization(_probe(tmp_path, _runner("", timers="", services=""), RA_CFG))
    assert "eliminated" not in r["metrics"] and "merged" not in r["metrics"]
    assert r["status"] == core.PARTIAL and r["gate"]["pass"] is False
    assert r["score"] == pytest.approx(round(8.0 / 3, 2))
    assert any("no live lines" in n for n in r["notes"])


def test_rationalization_matches_home_path_against_tilde_plan_rows(tmp_path):
    _plan(tmp_path)
    data = tmp_path / "proj" / "docs" / "implementation" / "n8n-maturity" / "data"
    _write(data / "cron_rows.json", [{"line": 100, "cmd": "~/repo/run.sh elim0 >> ~/logs/e.log 2>&1"},
                                     {"line": 101, "cmd": "$HOME/repo/run.sh elim1"}])
    crontab = (f"0 1 * * * {HOME}/repo/run.sh elim0 >> {HOME}/logs/e.log 2>&1\n"
               f"0 2 * * * {HOME}/repo/run.sh elim1\n")
    r = ds.rationalization(_probe(tmp_path, _runner(crontab, timers="", services=""), RA_CFG))
    # elim0 and elim1 still live (home path ≡ ~ ≡ $HOME) → only the 4 non-cron ELIMINATE items are gone
    assert r["metrics"]["eliminated"] == 4
    assert HOME not in json.dumps(r)


def test_rationalization_stale_pipeline_receipt_does_not_count(tmp_path):
    _pipeline_receipt(tmp_path, "after_close", "a", ts="2026-10-01T19:59:00Z")  # 192 h + 1 min old
    r = ds.rationalization(_probe(tmp_path, _runner("0 1 * * * x\n"), RA_CFG))
    assert r["metrics"]["pipelines_live"] == 0


def test_scheduler_coverage_zero_movable_lanes_is_not_full_coverage(tmp_path):
    _registry(tmp_path, [_lane("alpaca-stop-manager-rth", match="scripts/alpaca_stop_manager.py"),
                         _lane("schwab-token", match="scripts/schwab_token.py")])
    _ledger(tmp_path, [])
    r = ds.scheduler_coverage(_probe(tmp_path, _runner()))
    m = r["metrics"]
    assert m["movable_lanes"] == 0 and m["declared_fraction"] is None and m["run_proven_fraction"] is None
    assert r["gate"]["pass"] is False and r["status"] == core.PARTIAL and r["score"] < 8.0


def test_scheduler_coverage_empty_population_is_unverified(tmp_path):
    _registry(tmp_path, [_lane("ev", kind="event"), _lane("old", state="RETIRED")])
    r = ds.scheduler_coverage(_probe(tmp_path, _runner()))
    assert r["status"] == core.UNVERIFIED and r["score"] == 0.0 and r["gate"]["pass"] is False


def test_scheduler_coverage_no_rest_lanes_leaves_watched_unmeasured(tmp_path):
    _registry(tmp_path, [_lane(f"n{i}", kind="n8n", match=f"scripts/n{i}.py", cadence=0.25) for i in range(2)])
    fresh = "2026-10-09T19:50:00+00:00"
    _ledger(tmp_path, [("n0", "live", "RUN_DONE", fresh), ("n1", "live", "RUN_DONE", fresh)])
    r = ds.scheduler_coverage(_probe(tmp_path, _runner()))
    assert r["metrics"]["rest_lanes"] == 0 and r["metrics"]["watched_fraction"] is None
    assert r["gate"]["pass"] is False and r["status"] == core.PARTIAL


def test_scheduler_coverage_window_from_config(tmp_path):
    _registry(tmp_path, _sc_lanes(n_n8n=3, n_cron=0))
    old = "2026-10-08T08:00:00+00:00"  # 36 h ago: outside 24 h, inside 48 h
    _ledger(tmp_path, [(f"n{i}", "live", "RUN_DONE", old) for i in range(3)])
    r = ds.scheduler_coverage(_probe(tmp_path, _runner()))
    assert r["metrics"]["dispatcher_run_proven"] == 0
    r = ds.scheduler_coverage(_probe(tmp_path, _runner(), _config({"scheduler_coverage": {"window_hours": 48}})))
    assert r["metrics"]["dispatcher_run_proven"] == 3


@pytest.mark.parametrize("dim,key", [("registry_truth", "baseline_initial"), ("registry_truth", "gate_rule"),
                                     ("rationalization", "r0_target"), ("rationalization", "plan_rows_path"),
                                     ("rationalization", "pipeline_receipt_max_age_hours"),
                                     ("scheduler_coverage", "dispatched_min_fraction"),
                                     ("scheduler_coverage", "stay_tokens"),
                                     ("scheduler_coverage", "run_window_cadence_multiple")])
def test_missing_threshold_raises_config_error(tmp_path, dim, key):
    _plan(tmp_path)
    _registry(tmp_path, _sc_lanes())
    _ledger(tmp_path, [])
    cfg = _config()
    del cfg["dimensions"][dim][key]
    with pytest.raises(core.ConfigError):
        ds.COLLECTORS[dim](_probe(tmp_path, _runner(CRON3, "", ""), cfg))


def test_missing_gate_score_raises_config_error(tmp_path):
    _registry(tmp_path, _sc_lanes())
    cfg = _config()
    del cfg["gate_score"]
    for fn in ds.COLLECTORS.values():
        with pytest.raises(core.ConfigError):
            fn(_probe(tmp_path, _runner(CRON3, "", ""), cfg))


def test_real_config_carries_every_key_the_collectors_read(tmp_path):
    _plan(tmp_path)
    _registry(tmp_path, _sc_lanes())
    _ledger(tmp_path, [])
    for dim, fn in ds.COLLECTORS.items():
        assert fn(_probe(tmp_path, _runner(CRON3, "", ""), copy.deepcopy(REAL_CONFIG)))["id"] == dim


def test_no_in_code_threshold_tables():
    for name in ("REGISTRY_TRUTH_DEFAULTS", "RATIONALIZATION_DEFAULTS", "SCHEDULER_COVERAGE_DEFAULTS"):
        assert not hasattr(ds, name)


def test_deterministic(tmp_path):
    _plan(tmp_path)
    _registry(tmp_path, _sc_lanes())
    _ledger(tmp_path, [("n0", "live", "RUN_DONE", "2026-10-09T19:50:00+00:00")])
    a = [fn(_probe(tmp_path, _runner(CRON3, "", ""))) for fn in ds.COLLECTORS.values()]
    b = [fn(_probe(tmp_path, _runner(CRON3, "", ""))) for fn in ds.COLLECTORS.values()]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ── round 2 (#1593 review): every failed gate caps the score at the configured gate_cap ──────────

def test_r2_registry_truth_gate_fail_capped(tmp_path):
    _registry(tmp_path, [_lane("a", match="scripts/a.py"), _lane("b", match="scripts/b.py")])
    r = ds.registry_truth(_probe(tmp_path, _runner(CRON3), _config(gate_cap=3.0)))
    # (8 * 2/3 + 8) / 2 = 6.67 uncapped
    assert r["gate"]["pass"] is False and r["score"] == 3.0


def test_r2_rationalization_gate_fail_capped(tmp_path):
    _plan(tmp_path)
    _pipeline_receipt(tmp_path, "after_close", "a")
    crontab = "0 1 * * * cd x && python scripts/elim1.py\n0 2 * * * cd x && python scripts/merge0.py\n"
    cfg = copy.deepcopy(RA_CFG)
    cfg["gate_cap"] = 2.0
    r = ds.rationalization(_probe(tmp_path, _runner(crontab, timers="t1.timer enabled enabled\n", services=""), cfg))
    assert r["gate"]["pass"] is False and r["score"] == 2.0


def test_r2_scheduler_coverage_gate_fail_capped(tmp_path):
    lanes = _sc_lanes(n_n8n=3, n_cron=0)
    lanes[-3]["output_signal"] = {"kind": "none"}
    _registry(tmp_path, lanes)
    fresh = "2026-10-09T19:50:00+00:00"
    _ledger(tmp_path, [(f"n{i}", "live", "RUN_DONE", fresh) for i in range(3)])
    r = ds.scheduler_coverage(_probe(tmp_path, _runner(), _config(gate_cap=4.0)))
    # 7.61 uncapped (rest 2/3 watched)
    assert r["gate"]["pass"] is False and r["score"] == 4.0


def test_r2_gate_pass_is_never_capped(tmp_path):
    _registry(tmp_path, _sc_lanes(n_n8n=3, n_cron=0))
    fresh = "2026-10-09T19:50:00+00:00"
    _ledger(tmp_path, [(f"n{i}", "live", "RUN_DONE", fresh) for i in range(3)])
    r = ds.scheduler_coverage(_probe(tmp_path, _runner(), _config(gate_cap=4.0)))
    assert r["gate"]["pass"] is True and r["score"] >= 8.0

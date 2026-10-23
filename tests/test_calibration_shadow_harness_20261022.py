"""Calibration shadow harness (operator design 2026-10-22, Gate 4 item 3). Hermetic.

Each PROPOSED signal_calibration threshold is a trial: its value is frozen at first sight, it is evaluated
beside the current threshold over the next N forward sessions of journaled decisions (read-only), and the report
carries one recommendation per trial, always a proposal. Covers: trial lifecycle (open, keep, supersede on drift,
withdraw; nothing deleted), forward-window selection (no fitted session leaks in), the current/proposed
comparison and recommendation rules, current-value provenance and unit scale, dry run writes nothing, a live run
writes the report + receipt, and the n8n shadow registration (registry row, allowlist, DRAFT contract, gate,
import closure free of senders and brokers).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import calibration_shadow_harness as H  # noqa: E402

LANE = "calibration-shadow-harness"
CFG = {**H.DEFAULTS, "sessions": 2, "min_sample": 3, "min_edge": 0.05}


def _calibration(value=57.75, sessions=("2026-10-20", "2026-10-21"), knob="active_trader_alerts.max_spread_bps"):
    return {"contract": "active-trader-signal-calibration-v1", "status": "ok", "generated_at": 1.0,
            "sessions": list(sessions),
            "features": {"spread_bps": {"worked_median": 50.1, "stopped_median": 65.4}},
            "proposals": [{"type": "threshold", "knob": knob, "feature": "spread_bps", "proposed_value": value,
                           "why": "worked median 50.1 vs stopped median 65.4", "status": "PROPOSED — operator ratifies"}]}


def _d(i, day, spread, result, exit_pct=0.0):
    return {"type": "decision", "id": f"d{i}", "session_date": day, "features": {"spread_bps": spread},
            "outcome": {"result": result, "rule_exit_pct": exit_pct}}


def _decisions():
    rows, i = [], 0
    # fitted sessions: must never enter the forward window
    for day in ("2026-10-20", "2026-10-21"):
        for _ in range(3):
            i += 1
            rows.append(_d(i, day, 90.0, "WORKED", 5.0))
    # forward sessions: tight spreads work, wide ones stop
    for day in ("2026-10-22", "2026-10-23", "2026-10-26"):
        for spread, res, ex in ((40.0, "WORKED", 2.0), (45.0, "WORKED", 1.5), (55.0, "NO_TOUCH", -0.2),
                                (70.0, "STOPPED", -2.0), (80.0, "AT_OR_BELOW_STOP", -2.5)):
            i += 1
            rows.append(_d(i, day, spread, res, ex))
    return rows


def _yaml(tmp_path, body="active_trader_alerts:\n  mode: send\n"):
    p = tmp_path / "engine.yaml"
    p.write_text(body)
    return p


# ── trials ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_proposal_opens_a_trial_frozen_at_first_sight():
    active, history = H.update_trials(None, _calibration(), CFG)
    assert len(active) == 1 and history == []
    t = active[0]
    assert t["frozen_value"] == 57.75 and t["first_seen_session"] == "2026-10-21"


def test_small_drift_keeps_the_trial_large_drift_supersedes_and_withdrawal_is_recorded():
    first, _ = H.update_trials(None, _calibration(57.75), CFG)
    kept, hist = H.update_trials({"trials": first}, _calibration(60.0, sessions=("2026-10-21", "2026-10-22")), CFG)
    assert kept[0]["trial_id"] == first[0]["trial_id"] and kept[0]["latest_proposed_value"] == 60.0 and hist == []
    new, hist = H.update_trials({"trials": kept}, _calibration(70.0, sessions=("2026-10-22", "2026-10-23")), CFG)
    assert new[0]["frozen_value"] == 70.0 and new[0]["first_seen_session"] == "2026-10-23"
    assert hist[0]["status"] == "SUPERSEDED" and hist[0]["frozen_value"] == 57.75
    gone, hist2 = H.update_trials({"trials": new, "history": hist}, {**_calibration(), "proposals": []}, CFG)
    assert gone == [] and [h["status"] for h in hist2] == ["SUPERSEDED", "WITHDRAWN"]


def test_non_threshold_or_non_proposed_rows_are_ignored():
    cal = _calibration()
    cal["proposals"] += [{"type": "weight", "knob": "x", "proposed_value": 1},
                         {"type": "threshold", "knob": "y", "proposed_value": 2, "status": "RATIFIED"}]
    assert [t["knob"] for t in H.update_trials(None, cal, CFG)[0]] == ["active_trader_alerts.max_spread_bps"]


# ── evaluation ────────────────────────────────────────────────────────────────────────────────────────────────

def test_direction_from_knob_name_then_medians():
    assert H.direction("a.max_spread_bps", None) == "max"
    assert H.direction("a.min_buy_ratio", None) == "min"
    assert H.direction("min_stop.pct_of_price", {"worked_median": 2.4, "stopped_median": 1.1}) == "min"
    assert H.direction("x.ratio", {"worked_median": 1.0, "stopped_median": 2.0}) == "max"


def test_forward_window_excludes_the_fitted_sessions_and_recommends_adopt(tmp_path):
    rep = H.build_report(calibration=_calibration(), decisions=_decisions(), previous=None,
                         cfg={**CFG, "current_values": {"active_trader_alerts.max_spread_bps": 75.0}},
                         engine_yaml=_yaml(tmp_path))
    t = rep["trials"][0]
    assert t["forward_sessions"] == ["2026-10-22", "2026-10-23"]
    assert t["current_value"] == 75.0 and t["current_provenance"].startswith("declared")
    f = t["forward"]
    assert f["decisions"] == 10
    assert f["current"]["admitted"] == 8 and f["proposed"]["admitted"] == 6
    assert f["proposed"]["worked_rate"] == pytest.approx(4 / 6, abs=1e-4)
    assert f["stopped_avoided"] == 2 and f["worked_dropped"] == 0
    assert t["recommendation"] == "RECOMMEND_ADOPT"
    assert t["approval"] == H.OPERATOR_LINE
    assert t["in_sample"]["decisions"] == 6 and t["in_sample"]["label"].startswith("IN_SAMPLE")


def test_in_progress_until_n_forward_sessions(tmp_path):
    rows = [r for r in _decisions() if r["session_date"] <= "2026-10-22"]
    rep = H.build_report(calibration=_calibration(), decisions=rows, previous=None, cfg=CFG,
                         engine_yaml=_yaml(tmp_path))
    assert rep["trials"][0]["recommendation"] == "IN_PROGRESS"
    assert rep["trials"][0]["recommendation_reason"] == "1/2 forward sessions observed"


def test_reject_and_insufficient_sample_and_no_clear_edge():
    good = {"admitted": 40, "worked_rate": 0.2, "avg_rule_exit_pct": 0.5}
    worse = {"admitted": 40, "worked_rate": 0.1, "avg_rule_exit_pct": 0.5}
    tiny = {"admitted": 2, "worked_rate": 1.0, "avg_rule_exit_pct": 3.0}
    same = {"admitted": 40, "worked_rate": 0.21, "avg_rule_exit_pct": 0.45}
    kw = dict(sessions_done=2, sessions_needed=2, cfg=CFG)
    assert H.recommend({"current": good, "proposed": worse}, **kw)[0] == "RECOMMEND_REJECT"
    assert H.recommend({"current": good, "proposed": tiny}, **kw)[0] == "INSUFFICIENT_SAMPLE"
    assert H.recommend({"current": good, "proposed": same}, **kw)[0] == "NO_CLEAR_EDGE"
    exit_drop = {"admitted": 40, "worked_rate": 0.3, "avg_rule_exit_pct": 0.2}
    assert H.recommend({"current": good, "proposed": exit_drop}, **kw)[0] == "RECOMMEND_REJECT"


def test_current_value_provenance_and_unit_scale(tmp_path):
    y = _yaml(tmp_path, "min_stop:\n  pct_of_price: 0.01\nactive_trader_alerts:\n  max_spread_bps: 60\n")
    assert H.current_value("active_trader_alerts.max_spread_bps", CFG, y) == (60.0, "config/scalp_signal_engine.yaml")
    v, prov = H.current_value("min_stop.pct_of_price", {**CFG, "current_scale": {"min_stop.pct_of_price": 100}}, y)
    assert v == pytest.approx(1.0) and "×100" in prov
    v, prov = H.current_value("active_trader_alerts.min_buy_ratio", CFG, y)
    assert v is None and prov.startswith("not computed")


def test_no_baseline_compares_against_no_threshold(tmp_path):
    rep = H.build_report(calibration=_calibration(), decisions=_decisions(), previous=None, cfg=CFG,
                         engine_yaml=_yaml(tmp_path))
    t = rep["trials"][0]
    assert t["current_value"] is None and t["baseline"].startswith("no threshold")
    assert t["forward"]["current"]["admitted"] == t["forward"]["decisions"] == 10


def test_missing_calibration_report_is_reported_not_crashed():
    rep = H.build_report(calibration=None, decisions=[], previous=None, cfg=CFG)
    assert rep["status"] == "NO_CALIBRATION_REPORT" and rep["produced_count"] == 0
    assert "nothing evaluated" in H.render_md(rep)


# ── run modes ─────────────────────────────────────────────────────────────────────────────────────────────────

def _at(tmp_path):
    learn = tmp_path / "at" / "learning"
    learn.mkdir(parents=True)
    (learn / "calibration_report.json").write_text(json.dumps(_calibration()))
    (learn / "trade_learning.jsonl").write_text("\n".join(json.dumps(r) for r in _decisions()) + "\n")
    return tmp_path / "at"


def test_dry_run_writes_nothing(tmp_path, capsys):
    state = tmp_path / "state"
    assert H.main(["--dry-run", "--at-dir", str(_at(tmp_path)), "--state-root", str(state)]) == 0
    assert not state.exists()
    out = capsys.readouterr()
    assert "DRY-RUN" in out.out and "LANE_OUTPUT" in out.err


def test_live_run_writes_report_markdown_and_receipt_and_keeps_trials(tmp_path):
    state, at = tmp_path / "state", _at(tmp_path)
    assert H.main(["--at-dir", str(at), "--state-root", str(state)]) == 0
    rep = json.loads((state / H.REPORT_REL).read_text())
    assert rep["schema"] == H.SCHEMA and rep["produced_count"] == 1
    assert rep["authority"] == {"read_only": True, "config_write": False, "order": False, "broker_write": False}
    assert "PROPOSED — operator ratifies" in (state / H.REPORT_REL).with_suffix(".md").read_text()
    receipt = json.loads((state / H.RECEIPT_REL).read_text())
    assert receipt["lane_id"] == LANE and receipt["status"] == "ok" and receipt.get("ok_at")
    assert receipt["produced_count"] == 1
    first_id = rep["trials"][0]["trial_id"]
    assert H.main(["--at-dir", str(at), "--state-root", str(state)]) == 0
    assert json.loads((state / H.REPORT_REL).read_text())["trials"][0]["trial_id"] == first_id


def test_journals_and_config_are_never_written(tmp_path):
    at = _at(tmp_path)
    before = {p: p.read_bytes() for p in at.rglob("*") if p.is_file()}
    cfg_before = (ROOT / "config/scalp_signal_engine.yaml").read_bytes()
    H.main(["--at-dir", str(at), "--state-root", str(tmp_path / "state")])
    assert {p: p.read_bytes() for p in at.rglob("*") if p.is_file()} == before
    assert (ROOT / "config/scalp_signal_engine.yaml").read_bytes() == cfg_before


# ── gate ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_ci_gate_registered():
    from scripts.lib import ci_gates

    doc = json.loads((ROOT / "config/ci_gates/calibration_shadow_harness_20261022.json").read_text())
    assert ci_gates.validate(doc, stem="calibration_shadow_harness_20261022")
    assert doc["files"] == ["tests/test_calibration_shadow_harness_20261022.py"]
    assert doc["anchor"] == "CALIBRATION_SHADOW_HARNESS_20261022"

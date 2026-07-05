#!/usr/bin/env python3
"""Tag-lift discovery (URDL Stage 3, spec Part F) test suite.

Pure synthetic-data tests — DB seams (tag_lift._execute +
entity_spikes._execute for the shared covered-keys query), the weights file
(feedback.apply_weight_delta) and the inbox write path are all monkeypatched,
so the whole suite runs under TRADE_AI_CI with no PostgreSQL.

    .venv/bin/python -m pytest tests/test_hermes_tag_lift_discovery.py -q
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.hermes_discovery import entity_spikes, feedback, tag_lift  # noqa: E402

# ── synthetic outcome bus windows ────────────────────────────────────────────

CURRENT_BUS = {
    "run_id": "ofb_current", "by_tag": {
        "catalyst": {"lift": 0.05, "precision": 0.60, "n": 20, "flagged": False},
        "swing": {"lift": 0.02, "precision": 0.50, "n": 4, "flagged": False},
    },
}
PRIOR_BUS = {
    "run_id": "ofb_prior", "by_tag": {
        "catalyst": {"lift": 0.025, "precision": 0.55, "n": 18},
        "swing": {"lift": 0.02, "precision": 0.50, "n": 4},
    },
}


def _entries(feed=None, prior=PRIOR_BUS):
    return tag_lift.compute_tag_lift(CURRENT_BUS, prior, feed)


def _by_tag(entries):
    return {e["tag"]: e for e in entries}


# ── lift computation ─────────────────────────────────────────────────────────

def test_lift_ratio_current_vs_prior_window():
    e = _by_tag(_entries())
    assert e["catalyst"]["lift_ratio"] == pytest.approx(2.0, abs=0.01)
    assert e["swing"]["lift_ratio"] == pytest.approx(1.0, abs=0.01)
    assert e["catalyst"]["useful_outcome_count"] == 12   # round(20 * 0.6)
    assert e["catalyst"]["false_outcome_count"] == 8
    assert e["catalyst"]["version"] == tag_lift.TAG_LIFT_VERSION


def test_missing_prior_window_yields_none_ratio_with_note():
    e = _by_tag(_entries(prior=None))
    assert e["catalyst"]["lift_ratio"] is None
    assert "no_prior_window" in e["catalyst"]["notes"]


def test_lift_ratio_capped():
    cur = {"run_id": "a", "by_tag": {"x": {"lift": 100.0, "precision": 0.5, "n": 10}}}
    pri = {"run_id": "b", "by_tag": {"x": {"lift": 0.0001, "precision": 0.5, "n": 10}}}
    e = _by_tag(tag_lift.compute_tag_lift(cur, pri))
    assert e["x"]["lift_ratio"] == tag_lift.LIFT_RATIO_CAP


def test_outcome_feed_shapes_parsed(tmp_path):
    p = tmp_path / "feed.json"
    p.write_text(json.dumps({
        "by_tag": {"ai_infra": {"useful": 5, "false": 1}},
        "by_source": {"seekingalpha.com": {"useful_outcome_count": 3,
                                           "false_outcome_count": 0}},
        "outcomes": [{"tag": "ai_infra", "useful": True},
                     {"source_domain": "seekingalpha.com", "useful": False}],
    }))
    feed = tag_lift.load_outcome_feed(p)
    assert feed["by_tag"]["ai_infra"] == {"useful": 6, "false": 1}
    assert feed["by_source"]["seekingalpha.com"] == {"useful": 3, "false": 1}


def test_outcome_feed_missing_is_a_note_not_an_error(tmp_path):
    notes = []
    feed = tag_lift.load_outcome_feed(tmp_path / "nope.json", notes)
    assert feed == {"by_tag": {}, "by_source": {}}
    assert any("outcome_feed" in n for n in notes)


def test_prior_bus_snapshot_skips_current_run_id(tmp_path):
    (tmp_path / "outcome_bus_2026-07-05_cur.json").write_text(json.dumps(CURRENT_BUS))
    (tmp_path / "outcome_bus_2026-07-04_prior.json").write_text(json.dumps(PRIOR_BUS))
    prior = tag_lift.load_prior_outcome_bus("ofb_current", tmp_path)
    assert prior and prior["run_id"] == "ofb_prior"


# ── action planning: bounded deltas ──────────────────────────────────────────

def _plan(entries, fb=None, feed=None, existing=frozenset(), covered=frozenset(),
          min_outcomes=5, skipped=None):
    return tag_lift.plan_actions(
        entries, fb or {"current": {}, "prior": {}}, feed or {},
        existing_trend_keys=set(existing), covered=set(covered),
        min_outcomes=min_outcomes, skipped=skipped)


def test_existing_candidate_boost_delta_bounded():
    plan = _plan(_entries(), existing={"catalyst"})
    deltas = [d for d in plan["weight_deltas"] if d.get("trend_key") == "catalyst"]
    assert len(deltas) == 1
    assert deltas[0]["delta"] == pytest.approx((2.0 - 1.0) * tag_lift.DELTA_PER_LIFT,
                                               abs=0.01)


def test_extreme_lift_delta_hard_bounded():
    cur = {"run_id": "a", "by_tag": {"x": {"lift": 50.0, "precision": 0.9, "n": 100}}}
    pri = {"run_id": "b", "by_tag": {"x": {"lift": 0.001, "precision": 0.5, "n": 10}}}
    plan = _plan(tag_lift.compute_tag_lift(cur, pri), existing={"x"})
    for d in plan["weight_deltas"]:
        assert abs(d["delta"]) <= tag_lift.MAX_RUN_DELTA
        assert abs(d["delta"]) <= feedback.MAX_ABS_DELTA


def test_no_boost_for_unknown_candidate_keys():
    plan = _plan(_entries(), existing=set())
    assert not [d for d in plan["weight_deltas"] if d.get("kind") == "trend"]


def test_feedback_outcome_deltas():
    fb = {"current": {("source", "seekingalpha.com"): {"useful": 4, "false": 1},
                      ("trend", "ai datacenter"): {"useful": 0, "false": 6}},
          "prior": {}}
    plan = _plan([], fb=fb)
    by_target = {(d["kind"], d.get("source_domain") or d.get("trend_key")): d["delta"]
                 for d in plan["weight_deltas"]}
    assert by_target[("source", "seekingalpha.com")] == pytest.approx(0.06)
    assert by_target[("trend", "ai datacenter")] == pytest.approx(
        -tag_lift.MAX_RUN_DELTA)  # -0.12 clamped to -0.10


# ── candidate creation: sample gate + dedupe ─────────────────────────────────

def test_sample_gate_blocks_below_min_outcomes():
    skipped = {}
    plan = _plan(_entries(), skipped=skipped)
    labels = {c["label"] for c in plan["candidates"]}
    # catalyst: useful=12 >= 5 → created; swing: useful=2 < 5 → gated
    assert any("catalyst" in lb for lb in labels)
    assert not any("swing" in lb for lb in labels)
    assert skipped.get("below_min_outcomes", 0) >= 1


def test_sample_gate_boundary():
    feed = {"by_tag": {"exactly five": {"useful": 5, "false": 0}},
            "by_source": {}}
    plan = _plan(_entries(feed=feed), feed=feed)
    assert any("exactly five" in c["label"] for c in plan["candidates"])
    feed4 = {"by_tag": {"only four": {"useful": 4, "false": 0}}, "by_source": {}}
    plan4 = _plan(_entries(feed=feed4), feed=feed4)
    assert not any("only four" in c["label"] for c in plan4["candidates"])


def test_creation_deduped_against_covered_and_existing():
    skipped = {}
    plan = _plan(_entries(), covered={"catalyst"}, skipped=skipped)
    assert not plan["candidates"]
    assert skipped.get("covered_by_directive_or_topic") == 1
    skipped2 = {}
    plan2 = _plan(_entries(), existing={"catalyst"}, skipped=skipped2)
    assert not plan2["candidates"]
    assert skipped2.get("already_candidate") == 1


def test_candidate_payload_shape():
    plan = _plan(_entries())
    c = plan["candidates"][0]
    assert c["candidate_type"] in ("TREND_CANDIDATE", "TOPIC_CANDIDATE")
    assert c["safe_action_level"] == "OPERATOR_REVIEW_REQUIRED"
    assert c["meta"]["tag_lift_json"]["tag"] == "catalyst"
    assert c["meta"]["producer"] == tag_lift.PRODUCER
    assert 0.0 <= c["signals"]["trend_momentum"] <= 1.0
    assert 0.0 <= c["signals"]["outcome_bus_alignment"] <= 1.0
    assert c["evidence"]


# ── full run with everything monkeypatched ───────────────────────────────────

def _fake_db(monkeypatch, *, feedback_rows=(), existing_keys=(), covered_labels=()):
    def tag_lift_execute(sql, params=None, fetch=None):
        s = " ".join(sql.split()).lower()
        if "from hermes_discovery_feedback" in s:
            return list(feedback_rows)
        if "from hermes_discovery_candidates" in s:
            return [{"normalized_key": k} for k in existing_keys]
        raise AssertionError(f"unexpected tag_lift SQL: {s[:120]}")

    def spikes_execute(sql, params=None, fetch=None):
        s = " ".join(sql.split()).lower()
        if "from watch_directives" in s:
            return [{"label": lb, "spec": {}} for lb in covered_labels]
        if "from topic_monitor" in s:
            return []
        raise AssertionError(f"unexpected covered SQL: {s[:120]}")

    monkeypatch.setattr(tag_lift, "_execute", tag_lift_execute)
    monkeypatch.setattr(entity_spikes, "_execute", spikes_execute)


def _paths(tmp_path):
    bus = tmp_path / "outcome_bus.json"
    bus.write_text(json.dumps(CURRENT_BUS))
    hist = tmp_path / "history"
    hist.mkdir()
    (hist / "outcome_bus_2026-07-04_prior.json").write_text(json.dumps(PRIOR_BUS))
    return {"bus_path": bus, "history_dir": hist, "feed_path": tmp_path / "feed.json"}


def test_dry_run_makes_zero_writes(monkeypatch, tmp_path):
    _fake_db(monkeypatch, existing_keys=["catalyst"])
    monkeypatch.setattr(tag_lift.feedback, "apply_weight_delta",
                        lambda **kw: pytest.fail("dry-run must not touch weights"))
    monkeypatch.setattr(tag_lift.inbox, "upsert_candidate",
                        lambda **kw: pytest.fail("dry-run must not upsert"))
    report = tag_lift.run_discovery(dry_run=True, **_paths(tmp_path))
    assert report["dry_run"] is True
    assert report["weight_deltas_planned"] >= 1
    assert report["weight_deltas_applied"] == 0
    assert report["upserted"] == 0
    assert report["tags_analyzed"] == 2
    assert report["tag_lift"], "tag_lift_json entries must be in the report"


def test_live_run_applies_bounded_deltas_and_upserts(monkeypatch, tmp_path):
    _fake_db(monkeypatch, existing_keys=[])
    applied, upserted = [], []
    monkeypatch.setattr(tag_lift.feedback, "apply_weight_delta",
                        lambda **kw: applied.append(kw) or {})
    monkeypatch.setattr(
        tag_lift.inbox, "upsert_candidate",
        lambda **kw: upserted.append(kw) or {
            "id": len(upserted), "status": "DISCOVERED", "seen_count": 1,
            "discovery_score": 0.6, "meta_json": {"research_domain": "custom"}})
    report = tag_lift.run_discovery(dry_run=False, **_paths(tmp_path))
    for kw in applied:
        assert abs(kw["delta"]) <= feedback.MAX_ABS_DELTA
    assert report["upserted"] == len(upserted) == 1  # catalyst only (swing gated)
    assert upserted[0]["actor"] == tag_lift.ACTOR
    assert upserted[0]["safe_action_level"] == "OPERATOR_REVIEW_REQUIRED"
    assert upserted[0]["meta"]["tag_lift_json"]["useful_outcome_count"] >= 5
    assert report["by_type"] and report["by_domain"]


def test_missing_everything_degrades_to_notes(monkeypatch, tmp_path):
    _fake_db(monkeypatch)
    report = tag_lift.run_discovery(
        dry_run=True,
        bus_path=tmp_path / "missing_bus.json",
        history_dir=tmp_path / "missing_hist",
        feed_path=tmp_path / "missing_feed.json")
    assert report["tags_analyzed"] == 0
    assert report["candidates_planned"] == 0
    assert any("outcome_bus" in n for n in report["notes"])
    assert any("outcome_feed" in n for n in report["notes"])


# ── HARD RULE: no broker/execution/promotion imports, no threshold writes ─────

FORBIDDEN_IMPORT_RE = re.compile(
    r"^\s*(from|import)\s+\S*(schwab|alpaca|broker|execution|order|trade_exec|"
    r"snaptrade|promotion|atm_|paper_trading|live_trading)", re.IGNORECASE)

MODULE_FILES = [
    ROOT / "scripts" / "lib" / "hermes_discovery" / "tag_lift.py",
    ROOT / "scripts" / "hermes_tag_lift_discovery.py",
]


@pytest.mark.parametrize("path", MODULE_FILES, ids=lambda p: p.name)
def test_no_broker_execution_or_promotion_imports(path):
    src = path.read_text(encoding="utf-8")
    hits = [line for line in src.splitlines() if FORBIDDEN_IMPORT_RE.match(line)]
    assert not hits, f"forbidden import(s) in {path.name}: {hits}"
    low = src.lower()
    for token in ("transition_candidate", "decide_candidate", "promoted_to_watch",
                  "trading_threshold", "adaptive_threshold", "hermes_maturity_gates",
                  "submit_order", "place_order", "schwab", "alpaca", "execute_trade"):
        assert token not in low, f"forbidden token {token!r} in {path.name}"

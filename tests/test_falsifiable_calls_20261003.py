"""P1 every call is falsifiable + P4 per-agent calibration (operator 2026-10-03).

~19,800 of ~20,000 outcome checkpoints were OBSERVE/HOLD/WAIT and could never be
scored, so the belief writer formed 7 beliefs and skipped 8,440. Decisions now
carry an ExpectationPolicy@v1 expectation (STATED, or a labelled POLICY_DEFAULT
from a reviewed rule table) that the resolver scores against a benchmark.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import agent_calibration as cal  # noqa: E402
from scripts.lib.agent_decision_payload import build_decision_payload  # noqa: E402
from scripts.lib.expectation_policy import (  # noqa: E402
    SOURCE_POLICY_DEFAULT,
    SOURCE_STATED,
    build_expectation,
    score_expectation,
)


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "registry.json"))


@pytest.mark.parametrize("action,direction", [("HOLD", "WITHIN_BAND"), ("OBSERVE", "WITHIN_BAND"),
                                              ("TRIM", "DOWN"), ("BUY", "UP")])
def test_payload_stamps_a_labelled_policy_default(action, direction):
    exp = build_decision_payload(decision_id="d1", symbol="SCHD", current_action=action)["expectation"]
    assert exp["direction"] == direction
    assert exp["source"] == SOURCE_POLICY_DEFAULT
    assert exp["policy"] == "ExpectationPolicy@v1"
    assert exp["benchmark"] and exp["horizon_days"]


@pytest.mark.parametrize("action", ["HOLD_CASH", "RESEARCH", None])
def test_actions_that_claim_nothing_get_no_expectation(action):
    assert "expectation" not in build_decision_payload(decision_id="d2", symbol="SCHD", current_action=action)


def test_stated_expectation_wins_over_the_policy_default():
    stated = {"direction": "UP", "benchmark": "XLK", "horizon_days": 10}
    exp = build_decision_payload(decision_id="d3", symbol="NVDA", current_action="HOLD", expectation=stated)["expectation"]
    assert exp["source"] == SOURCE_STATED and exp["direction"] == "UP" and exp["benchmark"] == "XLK"
    bad = build_decision_payload(decision_id="d4", symbol="NVDA", current_action="HOLD",
                                 expectation={"direction": "sideways"})["expectation"]
    assert bad["source"] == SOURCE_POLICY_DEFAULT  # an invalid claim is not dressed up as stated


def test_checkpoint_carries_the_expectation():
    from scripts.lib.r17_checkpoint_binding import enrich_checkpoint

    ck = enrich_checkpoint({"decision_id": "d5", "symbol": "SCHD", "recommendation": "HOLD"}, "5d", source_sha="x")
    assert ck["expectation"]["direction"] == "WITHIN_BAND"
    ck2 = enrich_checkpoint({"decision_id": "d6", "symbol": "SCHD", "recommendation": "HOLD_CASH"}, "5d", source_sha="x")
    assert "expectation" not in ck2


def _lookup(prices):
    return lambda sym, date: prices.get(sym, {}).get(date)


def _cp(expectation):
    return {"decision_id": "d7", "symbol": "SCHD", "expectation": expectation, "context_receipt": {"symbol": "SCHD"},
            "original_decision_state": {"as_of": "2026-09-01T15:00:00+00:00", "recommendation": "HOLD", "symbol": "SCHD"}}


def test_resolver_scores_against_the_benchmark_over_the_same_dates():
    from datetime import datetime, timezone

    from scripts.lib.outcome_resolution import realized_state

    prices = {"SCHD": {"2026-09-01": (100.0, "2026-09-01"), "2026-09-21": (103.0, "2026-09-21")},
              "SPY": {"2026-09-01": (500.0, "2026-09-01"), "2026-09-21": (505.0, "2026-09-21")}}
    ok, realized, refs = realized_state(_cp(build_expectation("HOLD")), _lookup(prices),
                                        now=datetime(2026, 9, 21, 20, tzinfo=timezone.utc))
    assert ok and realized["change_pct"] == 3.0
    score = realized["expectation_score"]
    assert score["status"] == "SCORED" and score["hit"] is True and score["excess_pct"] == 2.0
    assert "ticker_prices:SPY:2026-09-01" in refs


def test_missing_benchmark_is_pending_data_not_a_guess():
    from datetime import datetime, timezone

    from scripts.lib.outcome_resolution import realized_state

    prices = {"SCHD": {"2026-09-01": (100.0, "2026-09-01"), "2026-09-21": (90.0, "2026-09-21")}}
    ok, realized, _ = realized_state(_cp(build_expectation("TRIM")), _lookup(prices),
                                     now=datetime(2026, 9, 21, 20, tzinfo=timezone.utc))
    assert ok and realized["change_pct"] == -10.0  # raw reading unaffected
    assert realized["expectation_score"]["status"] == "PENDING_DATA"
    assert realized["expectation_score"]["hit"] is None


@pytest.mark.parametrize("direction,sym,bench,hit", [("UP", 5, 2, True), ("UP", 1, 2, False),
                                                     ("DOWN", -3, 1, True), ("WITHIN_BAND", 9, 1, False)])
def test_scoring_rules(direction, sym, bench, hit):
    exp = {"direction": direction, "benchmark": "SPY", "band_pct": 5.0, "source": SOURCE_STATED}
    assert score_expectation(exp, sym, bench)["hit"] is hit


def _obs(oid, rec, *, change=None, score=None, decision_id="d"):
    realized = {"symbol": "SCHD", "recommendation": rec, "change_pct": change}
    if score is not None:
        realized["expectation"] = {"direction": "WITHIN_BAND", "benchmark": "SPY", "band_pct": 5.0,
                                   "source": SOURCE_POLICY_DEFAULT, "policy": "ExpectationPolicy@v1"}
        realized["expectation_score"] = {"status": "SCORED", "hit": score}
    return {"outcome_id": oid, "decision_id": decision_id, "realized_state": realized,
            "original_decision_state": {"recommendation": rec, "symbol": "SCHD"}, "observed_at": "2026-09-21"}


def test_belief_writer_counts_only_real_expectation_scores():
    from scripts.lib.cio_belief_writer import rows_from_observations

    rows = [_obs("o1", "HOLD", change=1.0, score=True), _obs("o2", "HOLD", change=1.0),
            _obs("o3", "TRIM", change=-2.0)]
    out, skipped = rows_from_observations(rows, subject_key_for=lambda s: "k:" + s)
    basis = {r["outcome_id"]: r["scoring_basis"] for r in out}
    assert basis == {"o1": "EXPECTATION", "o3": "DIRECTIONAL"}
    assert skipped.get("checkpoint_no_direction") == 1


def test_lesson_candidates_label_the_expectation_basis():
    from scripts.lib.outcome_to_lesson import build_candidates

    cands = build_candidates([_obs("o1", "HOLD", change=1.0, score=True)])
    assert cands and cands[0]["scoring_basis"] == "EXPECTATION"
    assert "against its expectation" in cands[0]["statement"]


def test_calibration_sample_floor_buckets_and_unattributed():
    traces = {f"d{i}": {"agent": "alex", "surface": "holdings", "confidence": 70.0} for i in range(25)}
    obs = [_obs(f"o{i}", "TRIM", change=(-1.0 if i < 20 else 1.0), decision_id=f"d{i}") for i in range(25)]
    obs += [_obs("x1", "TRIM", change=-1.0, decision_id="unknown")]
    obs += [_obs("x2", "HOLD", change=1.0, decision_id="d1")]  # unscored HOLD
    out = cal.build_calibration(obs, traces, min_sample=20)
    alex = next(a for a in out["agents"] if a["agent"] == "alex")
    assert alex["status"] == "MEASURED" and alex["hit_rate"] == 0.8 and alex["scored_outcomes"] == 25
    assert alex["by_confidence"] == [{"bucket": "60-80%", "n": 25, "hit_rate": 0.8}]
    assert alex["brier"] is not None
    other = next(a for a in out["agents"] if a["agent"] == cal.UNATTRIBUTED)
    assert other["status"] == "INSUFFICIENT_SAMPLE" and other["hit_rate"] is None
    assert out["unscored_observations"] == 1


def test_calibration_endpoint_reads_stores_and_caches(tmp_path):
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    (cio / "outcome_observations.jsonl").write_text(json.dumps(_obs("o1", "TRIM", change=-1.0, decision_id="d1")) + "\n")
    (cio / "agent_run_traces.jsonl").write_text(json.dumps({"agent": "steph", "decision": {"decision_id": "d1", "surface": "watch"}}) + "\n")
    cal._CACHE.update({"key": None, "value": None})
    out = cal.get_agent_calibration(tmp_path)
    assert out["agents"][0]["agent"] == "steph" and out["agents"][0]["status"] == "INSUFFICIENT_SAMPLE"
    assert out["sources"]["observations"]["available"] is True

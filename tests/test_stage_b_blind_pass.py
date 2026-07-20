#!/usr/bin/env python3
"""Stage B — the blind model pass wired into the shadow service.

The live BETA run proved the point the whole programme was about: two models,
blind to the legacy IGNORE and to each other, independently agreed on the thesis
(SPECULATIVE_CONSTRUCTIVE, 2/2) while splitting on timing — the "agree on the
company, split on the entry" signal the one-word verdict destroyed.

These tests pin the guarantees deterministically, with lanes mocked so no
network is touched:
  - a facts packet carrying any anchor aborts the WHOLE pass (fatal)
  - a lane that fails is not a lane
  - one completed lane is SINGLE_LANE, never a consensus
  - agreement is measured per dimension; the minority is preserved
  - reconciliation is plurality counting, not a model call
  - out-of-vocabulary tokens are clamped, never propagated

Pure: no network, no database, no broker, no order.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import blind_review as br            # noqa: E402
import blind_review_runner as brr    # noqa: E402


# ── JSON parsing robustness ───────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected_key", [
    ('```json\n{"data_sufficient": true}\n```', "data_sufficient"),
    ('Here is my answer: {"data_sufficient": false} — done', "data_sufficient"),
    ('{"long_term_thesis": {"state": "CONSTRUCTIVE"}}', "long_term_thesis"),
])
def test_parse_json_extracts_object(raw, expected_key):
    assert expected_key in brr._parse_json(raw)


@pytest.mark.parametrize("raw", ["", "no json here", "not { valid", None])
def test_unparseable_output_is_none(raw):
    assert brr._parse_json(raw) is None


# ── vocabulary clamping ───────────────────────────────────────────────────────

def test_out_of_vocabulary_tokens_are_clamped():
    s = brr._sanitise({
        "long_term_thesis": {"state": "MADE_UP", "confidence": 9},
        "tactical_timing": {"state": "ALSO_FAKE"},
        "direction": {"tactical": "BULLISH", "swing": "NONSENSE", "long_term": "BEARISH"},
        "event_risk": {"impact": "caution"}})
    assert s["long_term_thesis"]["state"] == "INSUFFICIENT_EVIDENCE"
    assert s["long_term_thesis"]["confidence"] == 1.0        # clamped into 0..1
    assert s["tactical_timing"]["state"] == "NO_VALID_SETUP"
    assert s["direction"]["tactical"] == "BULLISH"           # valid, kept
    assert s["direction"]["swing"] == "UNRESOLVED"           # invalid, clamped
    assert s["event_risk"]["impact"] == "CAUTION"            # uppercased + valid


def test_valid_tokens_survive_sanitise():
    s = brr._sanitise({
        "long_term_thesis": {"state": "SPECULATIVE_CONSTRUCTIVE", "confidence": 0.6},
        "tactical_timing": {"state": "WAIT_FOR_PULLBACK", "trigger": "pullback", "invalidation": "below 15"},
        "direction": {"tactical": "MILDLY_BULLISH", "swing": "BULLISH", "long_term": "BULLISH"},
        "event_risk": {"impact": "CAUTION"}})
    assert s["long_term_thesis"]["state"] == "SPECULATIVE_CONSTRUCTIVE"
    assert s["tactical_timing"]["state"] == "WAIT_FOR_PULLBACK"


# ── blindness aborts the whole pass ───────────────────────────────────────────

def test_anchored_facts_abort_the_pass_before_any_call(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(brr, "run_one_lane",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    out = brr.run_blind_pass({"symbol": "T", "recommendation": "IGNORE"},
                             lanes=("grok", "chatgpt"))
    assert out["mode"] == "UNAVAILABLE"
    assert out.get("fatal") is True
    assert called["n"] == 0, "no lane may be called once an anchor is detected"


def test_nested_anchor_is_caught():
    with pytest.raises(br.BlindnessViolation):
        br.assert_blind({"symbol": "T", "catalysts": [{"verdict": "BUY"}]})


# ── mode logic and consensus-of-one ───────────────────────────────────────────

def _fake_lane(outputs):
    """Build a run_one_lane stand-in returning canned outputs per lane."""
    def _runner(lane, facts, timeout=90):
        if lane in outputs:
            return {"ok": True, "lane": lane, "model": lane, "output": outputs[lane]}
        return {"ok": False, "lane": lane, "model": lane, "error": "unavailable"}
    return _runner


def _out(thesis, timing, direction="BULLISH"):
    return brr._sanitise({
        "long_term_thesis": {"state": thesis, "confidence": 0.6},
        "tactical_timing": {"state": timing},
        "direction": {"tactical": direction, "swing": direction, "long_term": direction},
        "instrument": {"preferred": "STAGED_SHARES"},
        "event_risk": {"impact": "CAUTION"}})


def test_two_of_two_completing_is_blind_not_partial(monkeypatch):
    monkeypatch.setattr(brr, "run_one_lane", _fake_lane({
        "grok": _out("SPECULATIVE_CONSTRUCTIVE", "EXTENDED"),
        "chatgpt": _out("SPECULATIVE_CONSTRUCTIVE", "WAIT_FOR_BREAKOUT")}))
    out = brr.run_blind_pass({"symbol": "T"}, lanes=("grok", "chatgpt"))
    assert out["mode"] == "BLIND"
    assert out["lanes_completed"] == ["chatgpt", "grok"]


def test_one_completed_lane_is_single_lane_never_consensus(monkeypatch):
    monkeypatch.setattr(brr, "run_one_lane", _fake_lane({
        "grok": _out("CONSTRUCTIVE", "EXTENDED")}))   # chatgpt fails
    out = brr.run_blind_pass({"symbol": "T"}, lanes=("grok", "chatgpt"))
    assert out["mode"] == "SINGLE_LANE"
    assert out["agreement_by_dimension"]["long_term_thesis"] == "1/1"
    # a single source can never read as multi-lane agreement
    assert out["agreement_detail"]["long_term_thesis"]["agreement"] == "SINGLE_SOURCE"


def test_a_failed_lane_is_not_counted(monkeypatch):
    monkeypatch.setattr(brr, "run_one_lane", _fake_lane({
        "grok": _out("NEUTRAL", "RANGE_BOUND")}))     # chatgpt fails
    out = brr.run_blind_pass({"symbol": "T"}, lanes=("grok", "chatgpt"))
    assert out["mode"] == "SINGLE_LANE"
    failed = [r for r in out["lane_results"] if not r["ok"]]
    assert len(failed) == 1 and failed[0]["lane"] == "chatgpt"


def test_all_lanes_failing_is_unavailable(monkeypatch):
    monkeypatch.setattr(brr, "run_one_lane", _fake_lane({}))
    out = brr.run_blind_pass({"symbol": "T"}, lanes=("grok", "chatgpt"))
    assert out["mode"] == "UNAVAILABLE"
    assert out["reconciled"] is None


# ── per-dimension agreement and minority preservation ─────────────────────────

def test_agreement_is_per_dimension_and_minority_preserved(monkeypatch):
    monkeypatch.setattr(brr, "run_one_lane", _fake_lane({
        "grok": _out("SPECULATIVE_CONSTRUCTIVE", "EXTENDED", "MILDLY_BEARISH"),
        "chatgpt": _out("SPECULATIVE_CONSTRUCTIVE", "WAIT_FOR_BREAKOUT", "MILDLY_BULLISH")}))
    out = brr.run_blind_pass({"symbol": "T"}, lanes=("grok", "chatgpt"))
    # BETA's actual shape: agree on thesis, split on timing.
    assert out["agreement_by_dimension"]["long_term_thesis"] == "2/2"
    assert out["agreement_detail"]["long_term_thesis"]["agreement"] == "UNANIMOUS"
    assert out["agreement_detail"]["tactical_timing"]["agreement"] == "SPLIT"
    dims = {mv["dimension"] for mv in out["minority_views"]}
    assert "tactical_timing" in dims or "direction" in dims


# ── reconciliation is counting, not a model call ──────────────────────────────

def test_reconcile_takes_the_plurality_thesis():
    completed = {
        "grok": _out("SPECULATIVE_CONSTRUCTIVE", "EXTENDED"),
        "chatgpt": _out("SPECULATIVE_CONSTRUCTIVE", "WAIT_FOR_BREAKOUT"),
        "local": _out("NEUTRAL", "RANGE_BOUND")}
    rc = brr._reconcile(completed)
    assert rc["thesis_state"] == "SPECULATIVE_CONSTRUCTIVE"   # 2 of 3
    assert rc["thesis_agreement"] == pytest.approx(0.67, abs=0.01)


def test_reconcile_ignores_unresolved_when_counting():
    completed = {
        "grok": _out("CONSTRUCTIVE", "EXTENDED"),
        "chatgpt": brr._sanitise({"long_term_thesis": {"state": "INSUFFICIENT_EVIDENCE"}})}
    rc = brr._reconcile(completed)
    assert rc["thesis_state"] == "CONSTRUCTIVE"   # the one real vote wins


# ── the service wires it without letting the model author eligibility ─────────

def test_service_only_writes_horizons_from_the_model():
    """Grep guard: the model view feeds thesis/direction/timing, never a family
    state or a payoff number."""
    import shadow_decision_service as svc
    src = Path(svc.__file__).read_text()
    # The blind-pass block lives inside evaluate(), after the family builders are
    # defined — anchor on the pass header and the dimensions comment that follows.
    start = src.index("BLIND MODEL PASS")
    ev = src[start:src.index("plan_families", start)]
    for bad in ["ELIGIBLE = reconciled", "reconciled = maximum_loss", "reconciled.payoff"]:
        assert bad not in ev
    assert "reconciled" in ev and "thesis_state" in ev


def test_local_lane_is_not_a_default(monkeypatch):
    """local falls back to gpt-4o-mini when Ollama is down, correlating with the
    chatgpt lane; it must be opt-in."""
    monkeypatch.delenv("BLIND_REVIEW_LANES", raising=False)
    assert "local" not in brr._default_lanes()
    assert set(brr._default_lanes()) == {"grok", "chatgpt"}

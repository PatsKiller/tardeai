"""The live residual-web path, as opposed to the stub that stood in for it.

Both defects below live ONLY in `_live_transport`, which the stub deliberately
never touches — so the stub suite could not have caught either, and did not.
They surfaced the first time the hop was actually executed.
"""
import inspect

import pytest

from scripts.lib import cio_residual_web as rw


# ── the executor lane is not a model lane ─────────────────────────────────
#
# The first live hop died with:
#   RuntimeError: UNKNOWN_LANE: lane='residual_web' is not registered
# because `_live_transport` passed its own executor name straight into
# llm_lane.generate(), which only accepts registered provider lanes.

def test_the_model_lane_is_registered_and_is_not_the_executor_lane():
    assert rw.LANE == "residual_web"                 # who runs the hop
    assert rw.MODEL_LANE != rw.LANE                  # which provider answers
    from scripts.llm_lane import _DEEPSEEK_LANES
    assert rw.MODEL_LANE in _DEEPSEEK_LANES, rw.MODEL_LANE


def test_the_live_transport_resolves_model_lane_not_lane():
    src = inspect.getsource(rw._live_transport)
    assert 'request.get("model_lane")' in src
    assert 'request.get("lane")' not in src, (
        "passing the executor lane to generate() is what broke the first hop")


def test_the_decision_token_is_still_the_gate_rung():
    """The gate names the rung; the lane names the executor. Keep them apart."""
    assert rw.RESIDUAL_DECISION == "openai"
    assert rw.RESIDUAL_DECISION != rw.LANE


# ── the default search endpoint has to be one that exists ─────────────────
#
# DEFAULT_SEARXNG pointed at 8080, where nothing has ever listened. Every real
# caller passed 18888 explicitly, so the default only ever applied to a caller
# that forgot — and then failed at connect time looking like the search backend
# was down rather than like a wrong constant.

def test_the_searxng_default_points_at_the_port_in_use():
    from scripts.lib.searxng_client import DEFAULT_SEARXNG
    assert "18888" in DEFAULT_SEARXNG
    assert "8080" not in DEFAULT_SEARXNG


def test_the_searxng_default_is_still_env_overridable(monkeypatch):
    monkeypatch.setenv("SEARXNG_URL", "http://example.invalid/search")
    import importlib

    import scripts.lib.searxng_client as sc
    importlib.reload(sc)
    try:
        assert sc.DEFAULT_SEARXNG == "http://example.invalid/search"
    finally:
        monkeypatch.delenv("SEARXNG_URL", raising=False)
        importlib.reload(sc)


# ── the stub still cannot reach the network ───────────────────────────────

def test_the_stub_remains_the_default_after_these_fixes():
    sig = inspect.signature(rw.run_hop)
    assert sig.parameters["apply"].default is False


def test_a_stub_hop_still_costs_nothing():
    out = rw.run_hop("SLEEVE:CASH", question="q", question_ids=["q1"])
    assert out["cost_usd"] == 0.0
    assert out.get("provider") == "stub"

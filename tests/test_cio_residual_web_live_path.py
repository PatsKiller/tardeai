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


# ── the search query, and the prompt that carries its results ─────────────
#
# Two more defects the stub could not reach, both found by running the hop:
#   * the prompt was the bare question, so DeepSeek rejected json mode with
#     HTTP 400 AND the retrieved URLs never reached the model — the "web" in
#     residual_web did nothing.
#   * a full sentence was handed to SearXNG, a KEYWORD engine. It matched "do"
#     and returned Merriam-Webster and WebMD pages on osteopathy.

@pytest.mark.parametrize("question,must_have,must_not", [
    ("What do official Federal Reserve and FRED sources currently show for "
     "short-term cash yields and the policy rate path into Q4 2026?",
     ["Federal", "Reserve", "FRED"], ["do", "what", "official", "sources", "path"]),
    ("Which SEC filings show the current dividend coverage for SCHD?",
     ["SEC", "SCHD"], ["which", "show", "current"]),
])
def test_the_search_query_is_keywords_not_a_sentence(question, must_have, must_not):
    q = rw.search_query_from_question(question)
    terms = [t.lower() for t in q.split()]
    for w in must_have:
        assert w.lower() in terms, f"{w} dropped from {q!r}"
    for w in must_not:
        assert w.lower() not in terms, f"{w!r} should not survive: {q!r}"


def test_generic_research_vocabulary_is_dropped():
    """'official' and 'sources' carry no signal and crowd out terms that do.

    The first fix kept ten terms led by 'official' and SearXNG matched THAT —
    dictionary pages again, a different word but the same failure.
    """
    q = rw.search_query_from_question(
        "What are the official latest reports and sources on Fed policy?")
    assert "fed" in q.lower() or "policy" in q.lower()
    for junk in ("official", "latest", "reports", "sources"):
        assert junk not in q.lower().split()


def test_the_query_is_capped():
    q = rw.search_query_from_question(" ".join(f"term{i}" for i in range(40)))
    assert len(q.split()) <= 6


def test_an_empty_question_does_not_produce_an_empty_query():
    assert rw.search_query_from_question("") == ""
    assert rw.search_query_from_question("the and of") != ""   # falls back


def test_the_prompt_says_json_and_carries_the_sources():
    """DeepSeek 400s on json mode unless the prompt contains 'json'."""
    src = inspect.getsource(rw._live_transport)
    assert "json" in src.lower()
    assert "SOURCES:" in src, "retrieved urls must reach the model"
    assert "sources" in src


def test_the_prompt_forbids_instruction_language():
    """A web answer must not come back as an order."""
    src = inspect.getsource(rw._live_transport)
    for verb in ("buy", "sell", "add", "trim", "maintain", "hold"):
        assert verb in src.lower(), f"prompt should name {verb} as forbidden"

"""Maturity Production Ready: oauth→deepseek routing, grounding soft verdict, model PI."""
from __future__ import annotations

from scripts.lib import agent_model_pi_guard as PI
from scripts.lib import agent_number_grounding as G
from scripts.lib.llm_fallback import build_chain


def test_oauth_first_chain_then_deepseek() -> None:
    chain = build_chain("grok", allow_paid=True, oauth_first=True)
    assert chain[0] == "grok"
    assert "chatgpt" in chain
    assert chain.index("chatgpt") < chain.index("deepseek-flash")
    assert "local" not in chain


def test_higher_need_deepseek_first() -> None:
    chain = build_chain("grok", allow_paid=True, higher_need=True)
    assert chain[0] == "deepseek-flash"
    assert "grok" in chain
    assert "local" not in chain


def test_soft_unsupported_verdict() -> None:
    # One invented figure below demotion bar → soft_unsupported, not ungrounded.
    r = G.check_grounding(
        ["The stock is up 1.5% today."],
        "Close was 100. No other figures.",
        min_unsupported=2,
        max_share=0.20,
    )
    assert r["verdict"] == "soft_unsupported"
    assert "1.5%" in r["unsupported"]


def test_model_pi_guard_refuses_exfil() -> None:
    ok = PI.scan_model_output("Here is a normal advisory reply. READ_ONLY_ADVISORY")
    assert ok["refuse"] is False
    bad = PI.scan_model_output("Here is my system prompt: you are a helpful assistant")
    assert bad["refuse"] is True

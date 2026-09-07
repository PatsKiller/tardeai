"""If one LLM lane fails, the next must be tried — and the substitution said.

On 2026-09-05 the chatgpt lane failed 11 of 11 attempts and every caller naming
it simply got nothing. grok was healthy throughout and was never asked, because
`llm_lane.generate()` takes one lane and never tries another.

The availability signal could not have helped: `available("chatgpt")` returned
True the whole time, since it asks whether the proxy is AUTHENTICATED. It was.
Authentication is not the ability to answer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.llm_fallback import (  # noqa: E402
    FREE_CHAIN,
    NEVER_CHAIN,
    PAID_CHAIN,
    AllLanesFailed,
    build_chain,
    generate_with_fallback,
)


def _gen(behaviour: dict):
    """A fake generate(). behaviour maps lane -> text, Exception, or ''."""
    calls: list[str] = []

    def gen(prompt, lane=None, **kw):
        calls.append(lane)
        out = behaviour.get(lane, "")
        if isinstance(out, Exception):
            raise out
        return out

    gen.calls = calls                                          # type: ignore[attr-defined]
    return gen


ALL_UP = staticmethod(lambda lane: True)


# ── the incident ────────────────────────────────────────────────────────────

def test_a_failing_chatgpt_falls_through_to_grok():
    """The 2026-09-05 case: chatgpt 400s, grok is healthy and never asked."""
    gen = _gen({"chatgpt": RuntimeError("HTTP 400 model not supported"),
                "grok": "answer from grok"})
    r = generate_with_fallback("q", lane="chatgpt", generate=gen,
                               available=lambda _l: True)
    assert r.text == "answer from grok"
    assert r.lane == "grok"
    assert r.substituted is True
    assert gen.calls == ["chatgpt", "grok"]


def test_the_substitution_is_never_silent():
    gen = _gen({"chatgpt": RuntimeError("HTTP 400"), "grok": "ok"})
    r = generate_with_fallback("q", lane="chatgpt", generate=gen, available=lambda _l: True)
    line = r.provenance_line()
    assert "grok" in line and "chatgpt" in line and "AFTER" in line
    assert r.to_dict()["substituted"] is True
    assert any(not a["ok"] and "400" in a["error"] for a in r.to_dict()["attempts"])


def test_a_lane_that_works_is_not_reported_as_substituted():
    gen = _gen({"grok": "fine"})
    r = generate_with_fallback("q", lane="grok", generate=gen, available=lambda _l: True)
    assert r.substituted is False
    assert "as requested" in r.provenance_line()
    assert gen.calls == ["grok"]


def test_an_empty_response_counts_as_a_failure():
    """A lane returning "" has not answered. Passing that on as success is how a
    blank report reads as a real one."""
    gen = _gen({"chatgpt": "   ", "grok": "real answer"})
    r = generate_with_fallback("q", lane="chatgpt", generate=gen, available=lambda _l: True)
    assert r.lane == "grok"
    assert any(a.error == "empty response" for a in r.attempts)


# ── cost ────────────────────────────────────────────────────────────────────

def test_paid_lanes_are_not_used_unless_asked_for():
    """deepseek is metered with a daily USD cap. Silently rerouting a free-lane
    outage onto it turns an outage into a bill."""
    gen = _gen({"grok": RuntimeError("down"), "chatgpt": RuntimeError("down"),
                "deepseek-flash": "paid answer"})
    with pytest.raises(AllLanesFailed):
        generate_with_fallback("q", lane="grok", generate=gen, available=lambda _l: True)
    assert "deepseek-flash" not in gen.calls


def test_paid_lane_is_used_when_explicitly_allowed():
    gen = _gen({"grok": RuntimeError("down"), "chatgpt": RuntimeError("down"),
                "deepseek-flash": "paid answer"})
    r = generate_with_fallback("q", lane="grok", allow_paid=True, generate=gen,
                               available=lambda _l: True)
    assert r.lane == "deepseek-flash"
    assert gen.calls[-1] == "deepseek-flash"


def test_paid_lane_is_tried_last():
    chain = build_chain("grok", allow_paid=True)
    assert chain.index("deepseek-flash") == len(chain) - 1
    for free in FREE_CHAIN:
        assert chain.index(free) < chain.index("deepseek-flash")


# ── the rule the existing design already had ────────────────────────────────

@pytest.mark.parametrize("lane", sorted(NEVER_CHAIN))
def test_local_models_are_never_in_a_chain(lane):
    """llm_lane documents that DeepSeek failures "never fall through to local
    Gemma". Falling back to a local model changes the quality of an answer
    without changing its shape — the least detectable substitution there is."""
    assert lane not in build_chain("grok", allow_paid=True)
    assert lane not in build_chain(lane, allow_paid=True)


def test_requesting_a_never_lane_yields_a_chain_without_it():
    chain = build_chain("local")
    assert "local" not in chain
    assert chain[0] in FREE_CHAIN


# ── chain construction ──────────────────────────────────────────────────────

def test_the_requested_lane_is_always_tried_first():
    assert build_chain("chatgpt")[0] == "chatgpt"
    assert build_chain("grok")[0] == "grok"


def test_no_lane_is_tried_twice():
    chain = build_chain("grok", allow_paid=True, extra=["grok", "chatgpt"])
    assert len(chain) == len(set(chain))


def test_a_paid_lane_named_directly_is_still_honoured_without_allow_paid():
    """allow_paid governs what we fall back ONTO, not what may be asked for."""
    chain = build_chain("deepseek-flash", allow_paid=False)
    assert chain[0] == "deepseek-flash"
    assert set(chain[1:]) <= set(FREE_CHAIN)


# ── availability is a hint, not truth ───────────────────────────────────────

def test_an_unavailable_lane_is_skipped_without_spending_a_call():
    gen = _gen({"grok": "ok"})
    r = generate_with_fallback("q", lane="chatgpt", generate=gen,
                               available=lambda ln: ln != "chatgpt")
    assert "chatgpt" not in gen.calls
    assert r.lane == "grok"
    assert any(a.lane == "chatgpt" and "unavailable" in a.skipped_reason for a in r.attempts)


def test_a_lane_claiming_available_is_still_tried_and_may_still_fail():
    """The measured 2026-09-05 asymmetry: available() said True for a lane that
    failed every call. The signal is trusted when it says no, not when it says
    yes."""
    gen = _gen({"chatgpt": RuntimeError("400"), "grok": "ok"})
    r = generate_with_fallback("q", lane="chatgpt", generate=gen, available=lambda _l: True)
    assert "chatgpt" in gen.calls
    assert r.lane == "grok"


def test_a_broken_availability_probe_does_not_silence_a_working_lane():
    def probe(_lane):
        raise RuntimeError("probe exploded")

    gen = _gen({"chatgpt": "still works"})
    r = generate_with_fallback("q", lane="chatgpt", generate=gen, available=probe)
    assert r.text == "still works"


# ── total failure ───────────────────────────────────────────────────────────

def test_all_lanes_failing_raises_with_every_reason():
    gen = _gen({"grok": RuntimeError("a"), "chatgpt": RuntimeError("b")})
    with pytest.raises(AllLanesFailed) as ei:
        generate_with_fallback("q", lane="grok", generate=gen, available=lambda _l: True)
    lanes = {a["lane"] for a in ei.value.attempts}
    assert {"grok", "chatgpt"} <= lanes
    assert all(a["error"] for a in ei.value.attempts if not a["ok"])


def test_a_broken_lane_is_not_retried_within_one_call():
    """Hammering a broken lane is how a rate limit becomes a ban."""
    gen = _gen({"grok": RuntimeError("down"), "chatgpt": "ok"})
    generate_with_fallback("q", lane="grok", generate=gen, available=lambda _l: True)
    assert gen.calls.count("grok") == 1


def test_kwargs_reach_every_attempt_so_the_gate_is_not_bypassed():
    """A fallback must not become a way around the consumption gate."""
    seen: list[dict] = []

    def gen(prompt, lane=None, **kw):
        seen.append({"lane": lane, **kw})
        if lane == "chatgpt":
            raise RuntimeError("400")
        return "ok"

    generate_with_fallback("q", lane="chatgpt", generate=gen, available=lambda _l: True,
                           process_id="proc-1", task_summary="t")
    assert len(seen) == 2
    for call in seen:
        assert call["process_id"] == "proc-1"
        assert call["task_summary"] == "t"


# ── the root cause that made this necessary ─────────────────────────────────

def test_the_proxy_default_model_is_one_the_account_accepts():
    """gpt-5.4 was the default and 400s on this account. Probed 2026-09-05:
    gpt-5.5 and gpt-5.4-mini are the two that work."""
    src = (ROOT / "scripts" / "chatgpt_oauth_proxy.py").read_text(encoding="utf-8")
    assert 'CHATGPT_PROXY_MODEL", "gpt-5.5"' in src
    for rejected in ('"gpt-5.4"', '"gpt-5.3-codex"', '"gpt-5-codex"'):
        assert f"MODELS = [{rejected}" not in src
    assert 'MODELS = ["gpt-5.5", "gpt-5.4-mini"]' in src

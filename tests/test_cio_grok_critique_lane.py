"""Wave 3D-critique — the live Grok lane, mocked. No network in tests.

Contract: docs/ops/CIO_GROK_CRITIQUE_CONTRACT_2026-08-29.md
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.lib.cio_grok_critique import (
    GROK_LANE, LANE, PROCESS_ID, REJECT, VALID, PARTIAL, critique_live,
    to_artifact,
)
from scripts.lib.research_quality import critique

REPO = Path(__file__).resolve().parents[1]
GOOD = {"summary": "SCHD dividend growth steady as of 2026-08.",
        "sources": ["https://example.invalid/x"], "symbol": "SCHD"}


def _gen(payload):
    def g(prompt, **kw):
        g.calls += 1
        g.last_kwargs = kw
        g.last_prompt = prompt
        return payload
    g.calls = 0
    g.last_kwargs = {}
    return g


# ------------------------------------------------------- default is unchanged

def test_default_backend_is_lint_and_has_no_network():
    r = critique(GOOD)
    assert r["schema"] == "ResearchCritique@v1"
    assert "backend" not in r
    assert "calls_made" not in r


def test_lint_path_is_byte_identical_to_before():
    """The refactor must not have moved the lint's own verdicts."""
    from scripts.lib.research_quality import _critique_lint

    assert critique(GOOD) == _critique_lint(GOOD)


def test_no_http_client_in_the_module():
    code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "",
                  (REPO / "scripts/lib/cio_grok_critique.py").read_text(encoding="utf-8")))
    for bad in ("requests", "urllib", "httpx", "socket", "8645"):
        assert bad not in code, bad


def test_live_requires_explicit_opt_in():
    g = _gen('{"verdict":"VALID","reasons":[],"execution_language":false,"attachable":true}')
    critique(GOOD, generate=g)                 # no backend= -> lint
    assert g.calls == 0


# ----------------------------------------------------------------- transport

def test_live_uses_the_existing_lane_and_process():
    g = _gen('{"verdict":"VALID","reasons":[],"execution_language":false,"attachable":true}')
    critique_live(GOOD, plan_id="p1", generate=g)
    assert g.calls == 1
    assert g.last_kwargs["lane"] == LANE
    assert g.last_kwargs["process_id"] == PROCESS_ID
    assert g.last_kwargs["response_json"] is True


def test_default_pairing_is_one_the_gate_permits():
    """grok is refused for every research process; the default must not be."""
    assert LANE == "deepseek-v4-flash"
    assert PROCESS_ID == "hermes_external_research"
    assert GROK_LANE == "grok", "kept for the day that lane is authorised"


def test_lane_and_process_are_overridable():
    g = _gen('{"verdict":"VALID","reasons":[],"execution_language":false,"attachable":true}')
    r = critique_live(GOOD, generate=g, lane="grok",
                      process_id="maria_research_critique")
    assert g.last_kwargs["lane"] == "grok"
    assert r["lane"] == "grok"


def test_prompt_comes_from_the_curated_template():
    g = _gen('{"verdict":"VALID","reasons":[],"execution_language":false,"attachable":true}')
    critique_live(GOOD, generate=g)
    for verb in ("buy", "sell", "trim", "flatten"):
        assert verb in g.last_prompt, "curated forbidden-clause missing"
    assert "critique" in g.last_prompt.lower()


def test_exactly_one_call_per_critique():
    g = _gen('{"verdict":"PARTIAL","reasons":["thin"],"execution_language":false,"attachable":false}')
    critique_live(GOOD, generate=g)
    assert g.calls == 1


# ------------------------------------------------------------------ verdicts

@pytest.mark.parametrize("verdict,attachable", [
    ("VALID", True), ("PARTIAL", False), ("REJECT", False),
])
def test_verdicts_round_trip(verdict, attachable):
    g = _gen(json.dumps({"verdict": verdict, "reasons": [],
                         "execution_language": False, "attachable": True}))
    r = critique_live(GOOD, generate=g)
    assert r["verdict"] == verdict
    assert r["attachable"] is attachable, "only VALID may stay attachable"


def test_unparseable_is_partial_never_valid():
    for payload in ("not json", "", "{{{", '{"nope": 1}'):
        r = critique_live(GOOD, generate=_gen(payload))
        assert r["verdict"] == PARTIAL
        assert r["attachable"] is False


def test_fenced_json_is_parsed():
    g = _gen('```json\n{"verdict":"VALID","reasons":[],'
             '"execution_language":false,"attachable":true}\n```')
    assert critique_live(GOOD, generate=g)["verdict"] == VALID


def test_model_claiming_attachable_on_execution_language_is_overruled():
    """A tainted artifact is never attachable, whatever the model says."""
    g = _gen('{"verdict":"VALID","reasons":[],"execution_language":true,'
             '"attachable":true}')
    r = critique_live(GOOD, generate=g)
    assert r["verdict"] == REJECT
    assert r["attachable"] is False


def test_locally_detected_execution_language_spends_nothing():
    g = _gen('{"verdict":"VALID","reasons":[],"execution_language":false,"attachable":true}')
    r = critique_live({"summary": "Sell half the position now.", "sources": ["x"]},
                      generate=g)
    assert r["verdict"] == REJECT
    assert r["calls_made"] == 0
    assert g.calls == 0, "must not pay a model to confirm our own matcher"


def test_execution_language_is_never_retryable():
    g = _gen('{"verdict":"REJECT","reasons":["execution_language"],'
             '"execution_language":true,"attachable":false}')
    assert critique_live(GOOD, generate=g)["retryable"] is False


def test_truncated_is_retryable_once():
    r = critique_live(GOOD, generate=_gen("not json"))
    assert r["retryable"] is True


# ------------------------------------------------------------ failure posture

def test_transport_error_fails_closed():
    def boom(prompt, **kw):
        raise RuntimeError("proxy unreachable")

    r = critique_live(GOOD, generate=boom)
    assert r["verdict"] == PARTIAL
    assert r["attachable"] is False
    assert "transport_error" in r["reasons"]


def test_live_does_not_attach_or_escalate():
    """No attach, no next-gate hop.

    Checks escalation *semantics*, not the substring "flash": the authorised
    lane is literally named `deepseek-v4-flash`, and a lane name is not an
    escalation.
    """
    # Code only. The module's own docstring says "does not escalate", which a
    # naive substring scan reads as an escalation.
    code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "",
                  (REPO / "scripts/lib/cio_grok_critique.py").read_text(encoding="utf-8")))
    for bad in ("attach_research", "def attach", "openai_hop", "def escalate",
                "next_gate"):
        assert bad not in code, bad
    from scripts.lib import cio_grok_critique as mod

    assert not hasattr(mod, "escalate")


def test_critique_carries_no_financial_action_and_mbi_zero():
    r = critique_live(GOOD, generate=_gen('{"verdict":"VALID","reasons":[],'
                                          '"execution_language":false,"attachable":true}'))
    assert r["financial_action"] is False
    assert r["memory_behavior_influence"] == 0


# -------------------------------------------------------------- artifact row

def test_artifact_row_maps_verdict_to_outcome():
    for verdict, outcome in (("VALID", "VALID"), ("PARTIAL", "PARTIAL"),
                             ("REJECT", "FAIL")):
        g = _gen(json.dumps({"verdict": verdict, "reasons": [],
                             "execution_language": False, "attachable": False}))
        a = to_artifact(critique_live(GOOD, generate=g), artifact_id="a1",
                        plan_id="p1")
        assert a["provider"] == "grok_critique"
        assert a["outcome"] == outcome


def test_tainted_artifact_row_records_execution_language():
    g = _gen('{"verdict":"REJECT","reasons":["x"],"execution_language":true,'
             '"attachable":false}')
    a = to_artifact(critique_live(GOOD, generate=g), artifact_id="a1")
    assert a["outcome"] == "execution_language"


# ------------------------------------------------- gate refusals never retry

@pytest.mark.parametrize("refusal", [
    "COST_CAP_EXCEEDED: global cap",
    "COST_CONFIGURATION_INVALID: LLM_GLOBAL_DAILY_USD_CAP required",
    "POLICY_NOT_ALLOWED",
    "PROCESS_NOT_REGISTERED",
])
def test_gate_refusals_are_never_retryable(refusal):
    """Found live: a COST_CAP came back as ["transport_error", "COST_CAP..."].

    The literal set lookup missed it because the gate reports refusals as free
    text inside the exception message, so it was marked retryable — which the
    contract forbids. Retrying a budget stop or a policy refusal is asking the
    same question until a different answer arrives.
    """
    def refuse(prompt, **kw):
        raise RuntimeError(refusal)

    r = critique_live(GOOD, generate=refuse)
    assert r["verdict"] == PARTIAL
    assert r["attachable"] is False
    assert r["retryable"] is False, f"{refusal} must not retry"


def test_a_genuine_transport_error_still_retries_once():
    def boom(prompt, **kw):
        raise ConnectionError("connection reset by peer")

    assert critique_live(GOOD, generate=boom)["retryable"] is True


# ==================== position-directive verbs (found by the live critique)

@pytest.mark.parametrize("text", [
    "Maintain small tracking position with hard invalidation.",
    "maintain current position",
    "maintain the position",
    "keep a small tracking position",
    "add exposure",
    "add to the position",
    "maintain cash position",
])
def test_position_directives_are_caught(text):
    """The gap the live Grok critique found.

    The matcher passed "Maintain small tracking position … do not add until …"
    as clean. It failed on both halves: `maintain` was not a verb, and
    `position` was not a bare object (only order/stop/trade/fill/shares/now).
    Telling the operator what size to hold is an instruction as surely as
    telling them to sell.
    """
    from scripts.lib.execution_language import find_imperative

    assert find_imperative(text), f"missed a position directive: {text!r}"


def test_do_not_add_stays_admitted_because_the_pin_wins():
    """A `do not <verb>` rule was written and deliberately removed.

    A prohibition is arguably an order, but the same grammar covers the pinned
    legacy case "do not sell shares before the ex-date", which
    test_legacy_admitted requires to pass as ex-dividend context. Nothing
    separates them without reading intent, and Decision 1 says the pin wins.
    """
    from scripts.lib.execution_language import find_imperative

    assert find_imperative("do not sell shares before the ex-date") is None
    assert find_imperative("do not add until price action confirms") is None


@pytest.mark.parametrize("text", [
    "hold_with_thesis",                      # a stance label, used everywhere
    "suggestion_bias: hold_with_thesis",
    "the position is small",                 # noun, not verb
    "we maintain a neutral view",            # no position object
    "maintained the position last quarter",  # past tense
    "would add exposure if confirmed",       # modal
    "decided to add shares in March",        # infinitive
    "We trimmed the position in March.",     # past tense, existing rule
    "a maintenance release",
])
def test_the_widening_does_not_torch_ordinary_prose(text):
    """Decision 1: ban the instruction, never the word.

    Blast radius was measured before shipping: 46 of 471 stored artifacts newly
    match, every sampled one a real instruction. 468 of the 471 sit before
    IMPERATIVE_GATE_EFFECTIVE and are grandfathered, so nothing is
    retro-detached.
    """
    from scripts.lib.execution_language import find_imperative

    assert not find_imperative(text), f"false positive on: {text!r}"


def test_existing_catches_still_fire():
    from scripts.lib.execution_language import find_imperative

    for text in ("Sell half the position now.", "place an order",
                 "execute trade", "flatten it", "liquidate"):
        assert find_imperative(text), text


def test_the_spcx_artifact_is_now_caught():
    """End-to-end on the real stored artifact Grok rejected."""
    import json
    from pathlib import Path

    from scripts.lib.execution_language import find_imperative

    p = Path("/tmp/claude-1000/spcx_artifact.json")
    if not p.is_file():
        pytest.skip("artifact fixture not present")
    assert find_imperative(json.dumps(json.loads(p.read_text()), default=str))

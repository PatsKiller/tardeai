"""Wave 3D-critique — the live Grok lane, mocked. No network in tests.

Contract: docs/ops/CIO_GROK_CRITIQUE_CONTRACT_2026-08-29.md
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.lib.cio_grok_critique import (
    LANE, PROCESS_ID, REJECT, VALID, PARTIAL, critique_live, to_artifact,
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
    code = (REPO / "scripts/lib/cio_grok_critique.py").read_text(encoding="utf-8")
    for bad in ("attach_research", "def attach", "flash", "openai_hop"):
        assert bad not in code, bad


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

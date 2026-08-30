"""P6 — CIOCouncilSynthesis@v1 determinism diligence.

Exit gate (master plan Phase 6): same inputs → same synthesis fields;
DISPUTED preserved; missing / incomplete specialists do not silently vanish.

Reuses `scripts/lib/cio_council_synthesis.py` and Wave 3B policy pins
(`tests/test_cio_wave3b_council_policy.py`). READ_ONLY_ADVISORY. MBI_BEHAVIOR=0.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts.lib.cio_council_synthesis import (
    AGREED,
    DISPUTED,
    NO_INPUT,
    SINGLE,
    synthesize,
)

REPO = Path(__file__).resolve().parents[1]
SYNTH = REPO / "scripts" / "lib" / "cio_council_synthesis.py"

# Fields that are intentionally wall-clock. Everything else must be stable.
_TIME_FIELDS = frozenset({"as_of"})


def _art(i, outcome="VALID", position=None, cost=0.0, **extra):
    row = {
        "artifact_id": i,
        "outcome": outcome,
        "position": position,
        "cost_usd": cost,
        "source_refs": [],
    }
    row.update(extra)
    return row


def _stable(block: dict) -> dict:
    return {k: copy.deepcopy(v) for k, v in block.items() if k not in _TIME_FIELDS}


# ── property: same inputs → same fields ────────────────────────────────────

@pytest.mark.parametrize("case", [
    {"name": "bullish_only", "arts": [_art("a", "VALID", "BULLISH"),
                                      _art("b", "VALID", "BULLISH")],
     "expect": AGREED},
    {"name": "bearish_only", "arts": [_art("a", "VALID", "BEARISH"),
                                      _art("b", "VALID", "BEARISH")],
     "expect": AGREED},
    {"name": "mixed_conflict", "arts": [_art("a", "VALID", "BULLISH"),
                                        _art("b", "VALID", "BEARISH")],
     "expect": DISPUTED},
    {"name": "single", "arts": [_art("a", "VALID", "BULLISH")],
     "expect": SINGLE},
    {"name": "no_valid", "arts": [_art("a", "FAIL"), _art("b", "SKIP")],
     "expect": NO_INPUT},
    {"name": "empty", "arts": [], "expect": NO_INPUT},
])
def test_p6_same_inputs_same_synthesis_fields(case, monkeypatch):
    """Property: freeze clock → byte-stable CIOCouncilSynthesis (minus nothing)."""
    fixed = "2026-08-30T12:00:00+00:00"
    monkeypatch.setattr("scripts.lib.cio_council_synthesis._utc", lambda: fixed)

    kwargs = dict(
        artifacts=case["arts"],
        case_summary={"schema": "CASE_SUMMARY@v1", "symbol": "SCHD"},
        desk_pin={"pin": "SCHD"},
        thesis_fields={"stance": "HOLD"},
        workflow_id="wf_p6_det",
        plan_id="plan_p6",
        symbol="SCHD",
    )
    a = synthesize(**kwargs)
    b = synthesize(**copy.deepcopy(kwargs))
    assert a == b
    assert a["schema"] == "CIOCouncilSynthesis@v1"
    assert a["state"] == case["expect"]
    assert a["model_called"] is False
    assert a["mints_plan"] is False
    assert a["financial_action"] is False
    assert a["authority"] == "READ_ONLY_ADVISORY"


def test_p6_repeat_calls_without_freeze_match_on_stable_fields():
    arts = [_art("a", "VALID", "BULLISH"), _art("b", "VALID", "BEARISH")]
    a = synthesize(artifacts=arts, symbol="SCHD", workflow_id="w1")
    b = synthesize(artifacts=arts, symbol="SCHD", workflow_id="w1")
    assert _stable(a) == _stable(b)
    assert a["state"] == DISPUTED


# ── DISPUTED preserved ─────────────────────────────────────────────────────

def test_p6_disputed_is_preserved_not_resolved():
    b = synthesize(artifacts=[
        _art("bull", "VALID", "BULLISH"),
        _art("bear", "VALID", "BEARISH"),
        _art("mid", "VALID", "NEUTRAL"),
    ], symbol="SCHD")
    assert b["state"] == DISPUTED
    assert set(b["positions"]) == {"BULLISH", "BEARISH", "NEUTRAL"}
    assert "no winner" in (b.get("disputed_note") or "").lower()
    # Both (all) sides remain visible — no silent drop of a specialist.
    assert set(b["artifact_ids"]) == {"bull", "bear", "mid"}


# ── missing / incomplete specialists ───────────────────────────────────────

def test_p6_missing_specialist_non_valid_is_excluded_not_silent():
    b = synthesize(artifacts=[
        _art("ok", "VALID", "BULLISH"),
        _art("gone", "FAIL"),
        _art("lang", "execution_language"),
        _art("skip", "SKIP"),
    ], symbol="DIV")
    assert b["state"] == SINGLE
    assert b["artifacts_considered"] == 4
    assert b["artifacts_valid"] == 1
    excluded = {x["artifact_id"]: x["outcome"] for x in b["excluded_non_valid"]}
    assert excluded == {
        "gone": "FAIL",
        "lang": "execution_language",
        "skip": "SKIP",
    }
    assert "gone" not in b["artifact_ids"]


def test_p6_incomplete_research_without_position_does_not_invent_stance():
    """Stance comes only from explicit fields — never inferred from prose."""
    b = synthesize(artifacts=[
        _art("a", "VALID", None),
        _art("b", "VALID", None),
    ], thesis_fields={"note": "looks constructive"}, symbol="BND")
    assert b["positions"] == {}
    assert b["state"] == AGREED
    assert b["thesis_fields"] == {"note": "looks constructive"}


def test_p6_wave3b_module_still_the_cited_join():
    """Cite path: diligence reuses Wave 3B council, does not fork a second brain."""
    text = SYNTH.read_text(encoding="utf-8")
    assert "CIOCouncilSynthesis@v1" in text
    assert "DISPUTED" in text
    assert "No model is called" in text or "no model" in text.lower()

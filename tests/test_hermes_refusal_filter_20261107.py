"""Data-truth audit (2026-11-07), defect 8: LLM refusals are not recommendations.

/api/v2/hermes/subject-intel-map?type=scalp served 159 rows of which dozens were the model
declining — "**Decline.** This request asks for trading signals…", "Active profile is default
(non-trading)", "I am Hermes in the default profile". A refusal carries no advice; serving it
as a `recommendation` labels an absence as a signal.

Covered here:
  * ``refusal_kind`` on the shapes the governed lanes actually returned, synthetic look-alikes
    only (this repository is PUBLIC — no captured operator data);
  * the admission gate rejects a hard refusal, and still accepts a real analysis that merely
    cites the AGENTS.md boundary further down;
  * both hermes intel read paths (map and per-subject) move refused rows out of the advice
    they serve and into a typed ``declined`` bucket with the text kept;

TRADE_AI_CI-safe: synthetic rows through the ``_db_query`` seam, no DB.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib.research_data_quality import refusal_kind, validate_research_output  # noqa: E402

HARD_REFUSAL = (
    "**Decline.** This request asks for trading signals, entry triggers, hard-stop logic, "
    "and a momentum scalp verdict on a live ticker. That conflicts with the default Hermes "
    "profile boundaries. No JSON or analysis will be produced."
)
BOUNDARY_ANSWER = (
    "Active profile is default Hermes (non-trading, non-advisory). Cannot provide trade "
    "analysis, entry triggers, stops, verdicts, or DeepSeek-lane recommendations."
)
BOUNDARY_WITH_EVIDENCE = (
    "SPCX packet-quality review only: the active identity is default Hermes, not the governed "
    "DeepSeek advisory lane, so this response does not create a trade proposal. Fact 1: the "
    "scanner reports RVOL 1.6x and a positive 2.1% gap."
)
REAL_ANALYSIS = (
    "SPCX remains an unconfirmed momentum candidate, not a clean setup. 1) Scanner reports "
    "RVOL 2.3x and a -1.4% gap; the catalyst is unverified. Wait rather than initiate. The "
    "standing thesis state is INSUFFICIENT_DATA."
)
# A genuine analysis that mentions the boundary only in passing must stay usable.
ANALYSIS_CITING_BOUNDARY = (
    "SPCX 1) Deterministic cache shows RVOL 1.6 and trend below_200. 2) No verified catalyst. "
    "3) Verdict: wait. This desk does not produce trade proposals and no order is implied; "
    "the default Hermes profile boundary was applied to the entry/stop part of the request."
)


def test_refusals_are_recognised_by_their_opening():
    assert refusal_kind(HARD_REFUSAL) == "refused"
    assert refusal_kind("Refused. This request attempts to override the active profile.") == "refused"
    assert refusal_kind("**Refusal:** This query requests entry triggers.") == "refused"
    assert refusal_kind(BOUNDARY_ANSWER) == "boundary"
    assert refusal_kind(BOUNDARY_WITH_EVIDENCE) == "boundary"
    assert refusal_kind("I am Hermes in the default profile. I cannot assume that role.") == "boundary"
    assert refusal_kind("I cannot provide trading setups, entry triggers, stop logic.") == "refused"


def test_real_analysis_is_not_a_refusal():
    assert refusal_kind(REAL_ANALYSIS) is None
    assert refusal_kind(ANALYSIS_CITING_BOUNDARY) is None
    assert refusal_kind("") is None
    assert refusal_kind(None) is None


def test_the_admission_gate_rejects_a_refusal_and_keeps_an_analysis():
    rejected = validate_research_output(HARD_REFUSAL)
    assert rejected["accepted"] is False
    assert rejected["reason_codes"] == ["llm_refusal"]
    assert validate_research_output(REAL_ANALYSIS)["accepted"] is True
    # A boundary answer keeps its analysis: labelled downstream, not discarded at the gate.
    assert validate_research_output(BOUNDARY_WITH_EVIDENCE)["accepted"] is True


# ── the read paths ─────────────────────────────────────────────────────────────

def _rows():
    return [
        {"symbol": "AAOI", "lane": "grok", "model": "grok-3-mini", "recommendation": HARD_REFUSAL,
         "created_at": "2026-11-06T18:04:14+00:00"},
        {"symbol": "AAOI", "lane": "chatgpt", "model": "gpt-5.4", "recommendation": REAL_ANALYSIS,
         "created_at": "2026-11-06T18:05:00+00:00"},
        {"symbol": "MSFT", "lane": "grok", "model": "grok-3-mini", "recommendation": BOUNDARY_ANSWER,
         "created_at": "2026-11-06T18:06:00+00:00"},
        {"symbol": "NVDA", "lane": "grok", "model": "grok-3-mini", "recommendation": REAL_ANALYSIS,
         "created_at": "2026-11-06T18:07:00+00:00"},
    ]


def _stub_db(monkeypatch, rows, one=None):
    import api_v2

    def fake(sql, params=None, fetch="all"):
        if fetch == "one":
            return one
        if params and len(params) == 2:  # the per-subject query: (symbol, trigger_reason)
            # It selects no ``symbol`` column — the WHERE clause scopes the rows — so the
            # stub drops it too; a route that reads r["symbol"] there would KeyError.
            return [{k: v for k, v in r.items() if k != "symbol"}
                    for r in rows if r["symbol"] == params[0]]
        return rows

    monkeypatch.setattr(api_v2, "_db_query", fake)
    return api_v2


def test_subject_intel_map_serves_no_refusal_as_a_recommendation(monkeypatch):
    api_v2 = _stub_db(monkeypatch, _rows())
    out = api_v2._hermes_subject_intel_map({"type": "scalp"})

    served = {(sym, r["lane"]) for sym, rs in out["map"].items() for r in rs}
    assert served == {("AAOI", "chatgpt"), ("NVDA", "grok")}
    assert out["keys"] == 2
    # Nothing that reads as advice carries a refusal.
    for rows in out["map"].values():
        for r in rows:
            assert refusal_kind(r["recommendation"]) is None

    # The refusals are still visible — labelled, with the text kept.
    assert out["declined_count"] == 2 and out["declined_keys"] == 2
    assert out["declined_kinds"] == {"refused": 1, "boundary": 1}
    assert out["declined"]["AAOI"][0]["refusal_kind"] == "refused"
    assert out["declined"]["AAOI"][0]["text"] == HARD_REFUSAL
    assert out["declined"]["AAOI"][0]["reason"]
    assert out["declined"]["MSFT"][0]["refusal_kind"] == "boundary"


def test_subject_intel_map_without_a_type_is_empty_but_typed(monkeypatch):
    api_v2 = _stub_db(monkeypatch, _rows())
    out = api_v2._hermes_subject_intel_map({})
    assert out["map"] == {} and out["keys"] == 0
    assert out["declined_count"] == 0 and out["declined_kinds"] == {"refused": 0, "boundary": 0}


def test_subject_intel_keeps_refusals_out_of_external_intel(monkeypatch):
    api_v2 = _stub_db(monkeypatch, _rows(), one=None)
    out = api_v2._hermes_subject_intel({"type": "proposal", "key": "AAOI"})
    lanes = [r["lane"] for r in out["external_intel"]]
    assert lanes == ["chatgpt"]
    assert out["declined_count"] == 1
    assert out["declined_intel"][0]["refusal_kind"] == "refused"
    assert out["declined_intel"][0]["text"] == HARD_REFUSAL


def test_external_intel_map_badges_carry_no_refusal(monkeypatch):
    """The watchlist 'curated by Grok/ChatGPT' badges read this route: a decline is not a
    curation verdict either."""
    api_v2 = _stub_db(monkeypatch, _rows())
    out = api_v2._hermes_external_intel_map()
    served = {(sym, r["lane"]) for sym, rs in out["map"].items() for r in rs}
    assert served == {("AAOI", "chatgpt"), ("NVDA", "grok")}
    assert out["declined_count"] == 2
    assert out["declined_kinds"] == {"refused": 1, "boundary": 1}
    assert out["declined"]["MSFT"][0]["refusal_kind"] == "boundary"

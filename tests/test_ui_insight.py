"""Server-supplied insight lines (PR3, 2026-09-27). The headline and tone come from decisions
already on the payload; the helper never invents a verdict. Hermetic."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib.ui_insight import build_insight, tone_for, TONES  # noqa: E402

DELL = {"symbol": "DELL", "strategy": "credit_spread", "generated_at": "2026-09-27T22:46:17+00:00",
        "cio_decision": {"outcome": "MONITOR_ONLY", "confidence": "MEDIUM", "at": "2026-09-27T23:22:13+00:00",
                         "decision_guid": "dec_df0d22a8",
                         "review": {"reasoning": "Thesis is fundamentally sound: the 8-K confirms the $95B backlog. However, IV rank is middling.",
                                    "concerns": ["Bid/ask spread 6.99% is wide", "IV rank 45.4 is mid-range", "third"]}},
        "enterprise": {"blocks": ["awaiting live quotes (market weekend): OI 0"]},
        "thesis_blocks": [{"code": "awaiting_cio_decision", "reason": "CIO decision: monitor only"}],
        "economics": {"ev_caveat": "model estimate at the desk's IV on a closed-market quote"},
        "flags": [{"key": "NOT_APPROVABLE", "label": "Not approvable: awaiting CIO decision"}], "approvable": False,
        "plain_english": {"objective": "Income with a capped worst case."}}


def test_options_insight_uses_the_cio_decision_first():
    i = build_insight("options_proposal", DELL)
    assert i["schema"] == "UiInsight@v1" and i["source"] == "llm" and i["tone"] == "warning"
    assert i["headline"] == "Thesis is fundamentally sound: the 8-K confirms the $95B backlog."
    assert i["drivers"][:2] == ["Bid/ask spread 6.99% is wide", "IV rank 45.4 is mid-range"]
    assert any(d.startswith("Expected P/L:") for d in i["drivers"]) and len(i["drivers"]) <= 4
    assert i["decision"] == {"outcome": "MONITOR_ONLY", "confidence": "MEDIUM", "decision_id": "dec_df0d22a8"}
    assert i["as_of"] == "2026-09-27T23:22:13+00:00" and "dec_df0d22a8" in i["provenance"]


def test_options_insight_without_a_decision_reads_the_truth_flags():
    p = {k: v for k, v in DELL.items() if k != "cio_decision"}
    i = build_insight("options_proposal", p)
    assert i["source"] == "rule" and i["tone"] == "warning" and i["headline"] == "DELL: not approvable — awaiting CIO decision."
    ok = dict(p, flags=[{"key": "APPROVABLE", "label": "Approvable"}], approvable=True, enterprise={"blocks": []}, thesis_blocks=[])
    j = build_insight("options_proposal", ok)
    assert j["tone"] == "success" and j["headline"] == "DELL: Income with a capped worst case."
    rej = dict(p, flags=[{"key": "NOT_APPROVABLE", "label": "Not approvable: CIO rejected"}])
    assert build_insight("options_proposal", rej)["tone"] == "danger"


def test_thesis_insight_is_the_summary_sentence_with_stance_tone():
    t = {"symbol": "DELL", "thesis_stance": "watch", "thesis_state": "THIN", "substantiveness_grade": "B",
         "thesis_summary": "Dell's 8-K confirms the $95B backlog is a point-in-time figure. Fundamentals are exceptional.",
         "research_gaps": ["conversion timing", "segment margin", "customer mix"], "last_reviewed": "2026-09-28T01:16:25+00:00",
         "symbol_thesis_version": "symbol_dell@v9"}
    i = build_insight("symbol_thesis", t)
    assert i["headline"] == "Dell's 8-K confirms the $95B backlog is a point-in-time figure." and i["tone"] == "warning"
    assert i["drivers"] == ["conversion timing", "segment margin", "thesis thin, grade B"] and i["provenance"] == "symbol_dell@v9"
    bull_thin = build_insight("symbol_thesis", dict(t, thesis_stance="BUY"))
    assert bull_thin["tone"] == "warning"        # a THIN thesis never reads as success
    assert build_insight("symbol_thesis", {"symbol": "X"})["headline"] == "X: no stated thesis stance yet."


def test_verdict_insight_and_unknown_kind_are_honest():
    i = build_insight("watch", {"symbol": "xar", "verdict": "WAIT", "why": "Near stop. Overdue review", "as_of": "2026-09-27"})
    assert i["headline"] == "XAR: WAIT — Near stop." and i["tone"] == "warning" and i["as_of"] == "2026-09-27"
    u = build_insight("something_else", {"symbol": "Q"})
    assert u["tone"] == "neutral" and u["headline"].startswith("No takeaway available")
    assert build_insight("options_proposal", None)["tone"] == "neutral"


def test_tone_vocabulary_is_closed():
    assert set(TONES) == {"success", "warning", "danger", "info", "ai", "neutral"}
    assert tone_for("approve") == "success" and tone_for("monitor only") == "warning" and tone_for("REJECT") == "danger"
    assert tone_for("banana", "info") == "info"
    i = build_insight("options_proposal", DELL)
    assert i["tone"] in TONES and len(i["headline"]) <= 280

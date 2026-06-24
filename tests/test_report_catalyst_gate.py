"""Tests for report_catalyst_gate — policy-sensitive catalyst publication gate."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import report_catalyst_gate as rcg  # noqa: E402


def _report(sym: str = "RGTI", *, bullets: list | None = None, content: str = "") -> dict:
    return {
        "meta": {"symbol": sym, "company": "Rigetti Computing Inc", "sector": "Technology"},
        "sections": [
            {"id": "executive_summary", "title": "Executive Summary", "content": "IGNORE.", "callouts": []},
            {
                "id": "news_catalysts",
                "title": "Latest News & Catalysts",
                "content": content or "No material scored catalysts in the current ingestion window.",
                "bullets": bullets or [],
            },
        ],
    }


def test_policy_symbol_requires_gate():
    required, reason = rcg.catalyst_gate_required(_report("RGTI"))
    assert required is True
    assert reason == "policy_symbol_list"


def test_non_policy_symbol_skips_gate():
    required, _ = rcg.catalyst_gate_required(_report("V"))
    assert required is False


def test_empty_news_not_adequate():
    assert rcg.news_catalysts_adequate(_report()) is False


def test_bullets_make_news_adequate():
    assert rcg.news_catalysts_adequate(_report(bullets=["Positive: Trump EO on quantum"])) is True


def test_evaluate_blocks_empty_policy_report():
    gate = rcg.evaluate_catalyst_gate(_report(), attempt_refresh=False)
    assert gate["required"] is True
    assert gate["block"] is True
    assert gate["issues"]


def test_refresh_heals_before_block():
    report = _report()

    def _heal(r: dict) -> bool:
        sec = next(s for s in r["sections"] if s["id"] == "news_catalysts")
        sec["bullets"] = ["Positive: Trump executive order on quantum"]
        sec["content"] = "Recent headlines are net supportive."
        return True

    with patch.object(rcg, "refresh_news_catalysts_section", side_effect=_heal):
        gate = rcg.evaluate_catalyst_gate(report, attempt_refresh=True)
    assert gate["block"] is False
    assert gate["refreshed"] is True


def test_publication_blocked_when_gate_fails():
    report = _report()
    rcg.apply_catalyst_gate_block(report, {"block": True, "reason": "policy_symbol_list", "issues": ["empty"]})
    assert rcg.publication_blocked(report) is True


def test_publication_allowed_with_headlines():
    report = _report(bullets=["Neutral: Commerce funds quantum pilot"], content="Mixed headlines.")
    gate = rcg.evaluate_catalyst_gate(report, attempt_refresh=False)
    assert gate["block"] is False
    assert rcg.publication_blocked(report) is False
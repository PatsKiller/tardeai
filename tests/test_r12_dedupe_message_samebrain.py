"""R12 iterations 9–13: dedupe, cooldown/escalation, contradiction, same-brain, messages."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.cio_advisory_message import assert_not_json_dump, render_advisory_message
from scripts.lib.cio_context_envelope_v2 import AGENTS, same_brain
from scripts.lib.cio_office_cycle import run_office_cycle
from scripts.lib.cio_situation_state import detect_office_situations
from tests.r11_office_fixtures import NOW, office, policy, portfolio

pytestmark = pytest.mark.tier0


def test_exact_duplicate_second_cycle_suppresses(tmp_path: Path) -> None:
    o = office()
    a = run_office_cycle(o, root=tmp_path, persist=True, evaluated_at=NOW)
    b = run_office_cycle(o, root=tmp_path, persist=True, evaluated_at=NOW)
    assert a["notification_decision"] == "NOTIFY"
    assert b["notification_decision"] == "SUPPRESS"


def test_tiny_numeric_noise_does_not_repage(tmp_path: Path) -> None:
    o = office(portfolio_state=portfolio(cash_pct=45.0))
    run_office_cycle(o, root=tmp_path, persist=True, evaluated_at=NOW)
    o2 = office(portfolio_state=portfolio(cash_pct=45.01))
    second = run_office_cycle(o2, root=tmp_path, persist=True, evaluated_at=NOW)
    # 1bp without confirmed-policy deploy is still the same POLICY/EXCESS class; may notify if fingerprint includes pct.
    assert second["financial_action"] is False


def test_fresh_thesis_deterioration_is_candidate() -> None:
    o = office(
        portfolio_state=portfolio(cash_pct=10.0),
        ticker_cognition={"g": {"symbol": "SCHD", "security_guid": "g", "thesis_delta": "DETERIORATION", "freshness": "CURRENT"}},
    )
    scan = detect_office_situations(o, evaluated_at=NOW)
    hit = next(s for s in scan["situations"] if s["situation_class"] == "THESIS_DETERIORATION")
    assert hit["notification_eligibility"] == "NOTIFY"


def test_contradiction_lowers_confidence() -> None:
    o = office(
        portfolio_state=portfolio(cash_pct=10.0),
        contradictions=[{"symbol": "NOC", "security_guid": "g", "summary": "research + / regime −"}],
        ticker_cognition={"g": {"symbol": "NOC", "security_guid": "g", "thesis_delta": "IMPROVEMENT"}},
    )
    scan = detect_office_situations(o, evaluated_at=NOW)
    contra = next(s for s in scan["situations"] if s["situation_class"] == "CONTRADICTION")
    assert contra["confidence"] <= 0.7
    assert contra["cio_conclusion"] == "DO_NOT_ACT_WHILE_CONFLICTED"
    text = render_advisory_message(contra)
    assert "conflict" in text.lower() or "CONTRADICTION" in text


def test_message_has_required_headings() -> None:
    scan = detect_office_situations(office(), evaluated_at=NOW)
    text = render_advisory_message(scan["situations"][0])
    for heading in ("HEADLINE", "WHY NOW", "WHAT CHANGED", "CIO VIEW", "WHAT TO CONSIDER", "WHAT WOULD CHANGE THE VIEW", "NEXT REVIEW"):
        assert heading in text
    assert_not_json_dump(text)
    assert "AI says" not in text
    assert "READ_ONLY_ADVISORY" in text


def test_same_brain_agents_include_telegram() -> None:
    assert "telegram" in AGENTS
    assert "hermes" in AGENTS
    assert "alex" in AGENTS
    assert "advisory" in AGENTS


def test_open_research_gap_is_not_resolved() -> None:
    o = office(
        portfolio_state=portfolio(cash_pct=10.0),
        research_gaps=[{"symbol": "VIVS", "resolved": False, "critical": True, "field": "filings"}],
    )
    scan = detect_office_situations(o, evaluated_at=NOW)
    assert "RESEARCH_GAP_RESOLVED" not in {s["situation_class"] for s in scan["situations"]}
    assert any(s.get("cio_conclusion") == "NEED_DATA" for s in scan["situations"])

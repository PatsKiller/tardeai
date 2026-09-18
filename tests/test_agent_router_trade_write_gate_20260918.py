"""R1 regression: trade/broker verbs require pending_approval (audit 2026-09-18)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import agent_router as ar


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    # Minimal config matching production shape for routing tests.
    cfg = {
        "default_agent": "orchestrator",
        "confidence_thresholds": {"auto_route": 0.70, "orchestrator_review": 0.45},
        "agents": {
            "maria": {"source_required": False},
            "tax_agent": {"source_required": True},
            "risk_agent": {"source_required": True},
            "steph_allocation": {"source_required": True},
            "steph": {"source_required": True},
            "orchestrator": {"source_required": False},
        },
        "intents": {
            "market_research": {
                "agent": "maria",
                "keywords": ["compare", "research", "sectors", "dividends"],
            },
            "tax_or_roth": {
                "agent": "tax_agent",
                "keywords": ["roth", "tax"],
            },
            "stop_decision": {
                "agent": "risk_agent",
                "keywords": ["stop", "honor"],
            },
            "portfolio_allocation": {
                "agent": "steph_allocation",
                "keywords": ["add", "rebalance", "allocate"],
            },
            "write_action": {
                "agent": "orchestrator",
                "keywords": ["update", "write", "database"],
            },
        },
        "high_impact": {"keywords": [], "core_holdings": [], "reviewers": ["risk_agent", "steph"]},
        "freshness": {},
    }
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "message",
    [
        "buy 100 shares of AAPL at market",
        "place an order for 10 shares of AAPL now",
        "execute trade AAPL buy 50",
        "please approve and send the broker order",
        "sell half of LMT",
    ],
)
def test_trade_verbs_require_pending_approval(config_path: Path, message: str) -> None:
    result = ar.build_route(message, config_path=config_path)
    assert result.action_type == "pending_write", message
    assert result.status == "pending_approval", message
    assert result.context_packet.get("requires_approval_before_write") is True
    assert result.context_packet.get("trade_write") is True
    assert any(a.get("type") == "approval_required" for a in result.pending_actions)


def test_yaml_write_still_pending(config_path: Path) -> None:
    result = ar.build_route(
        "update personal_situation.json with my new income",
        config_path=config_path,
    )
    assert result.action_type == "pending_write"
    assert result.status == "pending_approval"


def test_research_compare_stays_read_only(config_path: Path) -> None:
    result = ar.build_route(
        "Compare DGRO vs SCHD sectors and dividends",
        config_path=config_path,
    )
    assert result.action_type == "read_only"
    assert result.status in {"routed", "routed_multi_review"}
    assert result.context_packet.get("requires_approval_before_write") is False


def test_in_order_to_is_not_a_trade_write(config_path: Path) -> None:
    result = ar.build_route(
        "In order to compare DGRO vs SCHD, what are the sectors?",
        config_path=config_path,
    )
    assert result.action_type == "read_only"
    assert result.context_packet.get("trade_write") is False

#!/usr/bin/env python3
"""Tests for Schwab queue-entry bracket pilot (LIMIT buy + STOP child OTOCO)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from brokers import broker_entry_pilot as bep
from brokers.execution_guard import QUEUE_ENTRY_MARKER
from brokers.translators import schwab as schwab_tr


def test_build_intent_marker():
    intent = bep.build_intent("schwab_taxable", "AAPL", 10, 150.0, 140.0, proposal_id=42)
    assert intent.meta.strategy_id == QUEUE_ENTRY_MARKER
    assert intent.meta.signal_evidence["proposal_id"] == 42


def test_translate_otoco_bracket():
    intent = bep.build_intent("schwab_taxable", "AAPL", 10, 150.0, 140.0, target=165.0, proposal_id=1)
    spec = bep.spec_from_intent(intent)
    assert spec["orderStrategyType"] == "TRIGGER"
    assert spec["orderType"] == "LIMIT"
    assert spec["orderLegCollection"][0]["instruction"] == "BUY"
    child = spec["childOrderStrategies"][0]
    assert child["orderStrategyType"] == "OCO"
    types = {k["orderType"] for k in child["childOrderStrategies"]}
    assert types == {"LIMIT", "STOP"}


def test_translate_stop_only_bracket():
    intent = bep.build_intent("schwab_taxable", "MSFT", 5, 400.0, 380.0)
    spec = bep.spec_from_intent(intent)
    assert spec["orderStrategyType"] == "TRIGGER"
    stop_child = spec["childOrderStrategies"][0]
    assert stop_child["orderType"] == "STOP"


def test_order_summary():
    intent = bep.build_intent("schwab_taxable", "NVDA", 3, 120.0, 110.0)
    s = bep.order_summary(intent)
    assert s["symbol"] == "NVDA"
    assert "LIMIT" in s["summary"]
    assert "STOP" in s["summary"]


def test_request_route_validation():
    res = bep.request_route(999999999)
    assert res["ok"] is False
    assert "not found" in res.get("error", "").lower()


if __name__ == "__main__":
    test_build_intent_marker()
    test_translate_otoco_bracket()
    test_translate_stop_only_bracket()
    test_order_summary()
    test_request_route_validation()
    print("test_broker_entry_pilot: all passed")
"""Unit tests for Fidelity/SnapTrade protective stop policy (no live SnapTrade calls)."""
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "scripts")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from brokers.snaptrade_protective_stop_policy import evaluate, MONITORED_ENABLED, BROKER_API_ENABLED
from brokers.snaptrade_protective_stop_pilot import normalize_kind, order_summary
from brokers.snaptrade_trade import evaluate_envelope, envelope_limits, ONE_SHARE_TEST_EXACT_UNITS
from brokers.execution_guard import FIDELITY_PROTECTIVE_MARKER


def test_policy_disabled_by_default_broker_api():
    assert BROKER_API_ENABLED is False


def test_policy_monitored_enabled_committed():
    assert MONITORED_ENABLED is True


def test_evaluate_gates_removed_pass():
    ok, reasons = evaluate(
        account_key="fidelity_rollover_ira", instruction="SELL", order_type="STOP",
        stop_price=10.0, advised_stop=10.0, current_price=20.0, qty=5, held_qty=10, symbol="XAR")
    assert ok and not reasons


def test_normalize_trailing_alias():
    assert normalize_kind("TRAILING") == "TRAILING_STOP"


def test_order_summary_fidelity_platform():
    s = order_summary("XAR", 10, "STOP", stop_price=45.0, account_key="fidelity_rollover_ira")
    assert "Fidelity Active Trader Pro" in s["ticket"]
    assert s["platform"] == "Fidelity Active Trader Pro"


def test_fidelity_marker_distinct():
    assert FIDELITY_PROTECTIVE_MARKER == "FIDELITY_MONITORED_STOP"


def test_one_share_envelope_exact_units():
    lim = envelope_limits(one_share_test=True)
    assert lim["exact_units"] is True
    assert lim["max_units"] == ONE_SHARE_TEST_EXACT_UNITS
    ok, reasons = evaluate_envelope(
        account_key="fidelity_rollover_ira", action="BUY", order_type="Market",
        units=2, price=10.0, one_share_test=True)
    assert not ok
    assert any("exactly" in r for r in reasons)
    ok2, _ = evaluate_envelope(
        account_key="fidelity_rollover_ira", action="BUY", order_type="Market",
        units=1, price=10.0, one_share_test=True)
    assert ok2
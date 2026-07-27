"""Stage 10 tests — deterministic multi-broker internal simulation (no network)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from active_trader.simulation import (  # noqa: E402
    BrokerSim, OrderState, PnL, SimOrder, SimRejected, SmartLimitState, TERMINAL,
    TranslationError, capability_or_fail_closed, compute_pnl, fallback_new_quantity,
    smart_limit_step, translate_close,
)


def order(broker="alpaca", key="k1", qty=100):
    return SimOrder(order_id=f"o-{key}", broker=broker, account_label="a", symbol="TESTA",
                    side="BUY", requested_qty=qty, order_type="LIMIT", limit_price=4.0,
                    idempotency_key=key)


# ---- lifecycle
def test_submit_accept_reject_unreachable_idempotent():
    b = BrokerSim("alpaca")
    o = b.submit(order(key="k1"))
    assert o.state is OrderState.ACCEPTED
    # idempotent resubmit — no duplicate
    o2 = b.submit(order(key="k1"))
    assert o2 is o
    r = b.submit(order(key="k2"), accept=False, reject_code="INSUFFICIENT_BUYING_POWER")
    assert r.state is OrderState.REJECTED and "rejected:INSUFFICIENT_BUYING_POWER" in r.events
    u = b.submit(order(key="k3"), reachable=False)
    assert u.state is OrderState.BROKER_UNREACHABLE


def test_partial_then_full_fill_and_avg():
    b = BrokerSim("alpaca")
    o = b.submit(order(key="k1", qty=100))
    b.fill(o, 40, 4.00)
    assert o.state is OrderState.PARTIALLY_FILLED and o.filled_qty == 40 and o.remaining == 60
    b.fill(o, 60, 4.10)
    assert o.state is OrderState.FILLED and abs(o.avg_fill - 4.06) < 0.001


def test_cancel_pending_then_confirmed():
    b = BrokerSim("schwab")
    o = b.submit(order(broker="schwab", key="k1"))
    b.cancel(o, confirmed=False)
    assert o.state is OrderState.PENDING_CANCEL
    b.cancel(o, confirmed=True)
    assert o.state is OrderState.CANCELLED


def test_late_fill_after_terminal_ignored():
    b = BrokerSim("alpaca")
    o = b.submit(order(key="k1"))
    b.cancel(o)
    b.fill(o, 50, 4.0)          # late fill after cancel — ignored
    assert o.state is OrderState.CANCELLED and o.filled_qty == 0


def test_protection():
    b = BrokerSim("alpaca")
    o = b.submit(order(key="k1"))
    b.protect(o, confirmed=False)
    assert o.protection_state == "PENDING"
    b.protect(o, confirmed=True)
    assert o.protection_state == "CONFIRMED"


# ---- translation
def test_translation_matrix():
    assert translate_close("alpaca", {"NATIVE_CLOSE_POSITION": "SUPPORTED"})["method"] == "native_close"
    assert translate_close("alpaca", {})["method"] == "opposite_side_close"
    moo = translate_close("moomoo", {})
    assert moo["method"] == "opposite_side_close" and moo["limit_only_session"] and moo["rate_governed"]
    sw_market = translate_close("schwab", {"PLACE_MARKET_RTH": "SUPPORTED"}, session="RTH")
    assert sw_market["order_type"] == "MARKET"
    sw_ext = translate_close("schwab", {}, session="POST")
    assert sw_ext["order_type"] == "MARKETABLE_LIMIT"
    sw_restrict = translate_close("schwab", {"ELECTRONIC_ENTRY_ELIGIBILITY": "RESTRICTED"})
    assert sw_restrict["method"] == "broker_assist_required"
    with pytest.raises(TranslationError):
        translate_close("snaptrade", {})


def test_unknown_capability_fails_closed():
    with pytest.raises(SimRejected):
        capability_or_fail_closed("UNKNOWN")
    with pytest.raises(SimRejected):
        capability_or_fail_closed("UNSUPPORTED")
    capability_or_fail_closed("SUPPORTED")   # no raise


# ---- smart-limit
def test_smart_limit_bounds_and_no_fast_loop():
    st = SmartLimitState(limit_price=4.00, reference_price=4.00, max_authorized_price=4.05,
                         max_chase_bps=50, ttl_seconds=30)
    assert smart_limit_step(st, spread_bps=10, data_age_ms=100, sequence_ok=True,
                            rate_token_available=True, flow_reversed=False, filled=False)["action"] == "MODIFY"
    assert smart_limit_step(st, spread_bps=10, data_age_ms=5000, sequence_ok=True,
                            rate_token_available=True, flow_reversed=False, filled=False)["action"] == "CANCEL"
    assert smart_limit_step(st, spread_bps=10, data_age_ms=100, sequence_ok=False,
                            rate_token_available=True, flow_reversed=False, filled=False)["action"] == "CANCEL"
    assert smart_limit_step(st, spread_bps=10, data_age_ms=100, sequence_ok=True,
                            rate_token_available=True, flow_reversed=True, filled=False)["action"] == "CANCEL"
    assert smart_limit_step(st, spread_bps=50, data_age_ms=100, sequence_ok=True,
                            rate_token_available=True, flow_reversed=False, filled=False)["action"] == "HOLD"
    assert smart_limit_step(st, spread_bps=10, data_age_ms=100, sequence_ok=True,
                            rate_token_available=False, flow_reversed=False, filled=False)["action"] == "WAIT"
    assert smart_limit_step(st, spread_bps=10, data_age_ms=100, sequence_ok=True,
                            rate_token_available=True, flow_reversed=False, filled=True)["action"] == "STOP"
    cap = SmartLimitState(limit_price=4.05, reference_price=4.0, max_authorized_price=4.05,
                          max_chase_bps=50, ttl_seconds=30)
    assert smart_limit_step(cap, spread_bps=10, data_age_ms=100, sequence_ok=True,
                            rate_token_available=True, flow_reversed=False, filled=False)["action"] == "HOLD_AT_CAP"


# ---- multi-account fallback duplicate-exposure
def test_fallback_quantity_duplicate_exposure_safe():
    # authorized 200, filled 60, working 40 -> room 100; requested 100, cap 500 -> 100
    assert fallback_new_quantity(authorized_aggregate=200, confirmed_filled=60,
                                 confirmed_working=40, requested=100, fallback_cap=500) == 100
    # envelope exhausted -> 0
    assert fallback_new_quantity(authorized_aggregate=100, confirmed_filled=60,
                                 confirmed_working=40, requested=100, fallback_cap=500) == 0
    # cap binds
    assert fallback_new_quantity(authorized_aggregate=1000, confirmed_filled=0,
                                 confirmed_working=0, requested=100, fallback_cap=30) == 30


# ---- P&L
def test_pnl_computation_and_unavailable_mark():
    p = compute_pnl(account_label="a", symbol="TESTA", shares=10, avg_entry=4.0, mark=4.5,
                    fees=1.0, realized=2.0)
    assert p.unrealized == 5.0 and p.total == 6.0        # (4.5-4.0)*10 + 2 - 1
    p2 = compute_pnl(account_label="a", symbol="TESTA", shares=10, avg_entry=4.0, mark=None)
    assert p2.unrealized is None and p2.total is None


def test_no_network_no_broker_write_symbols():
    # simulation module must not import network/broker-write surfaces
    import active_trader.simulation as sim
    src = Path(sim.__file__).read_text()
    for banned in ("requests.", "http", "OpenSecTradeContext", "place_order(", "unlock_trade"):
        assert banned not in src

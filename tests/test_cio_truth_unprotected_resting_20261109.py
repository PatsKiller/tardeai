"""LQ-20261107-1390 — a resting GTC stop is protection, not money at risk.

Schwab reports a resting STOP order as AWAITING_STOP_CONDITION, which ``brokers/order_lifecycle.py`` maps to
``pending_activation``. Outside the session that is the normal state of every GTC stop. The live 2026-11-09 book
showed 8 such stops (ANET, BAH, PFE, SKYD, SPCX x2, T, V, XAR; $270,978) counted as "unprotected": Risk read
``0.0 % protected`` and ``$320,542`` without protection while the stops were resting at the broker.

``broker_protected`` stays the stricter "an ARMED stop can be priced right now" figure that drives loss-at-stop
and portfolio heat (board 15). The unprotected count and value are a different question -- is there an order at
the broker that will fire -- and a resting stop answers it yes.

Synthetic fixtures only: the repository is public.
"""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "scripts.lib._lq1390_cio_truth", ROOT / "scripts/lib/cio_truth.py")
truth = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = truth
SPEC.loader.exec_module(truth)

NOW = datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc)  # 17:00 ET, after the close: every GTC stop rests


def _row(status="WORKING", symbol="SYNTH", account="SyntheticAccountAlpha", order_id="synthetic-order"):
    return {"account": account, "symbol": symbol, "order_id": order_id, "status": status,
            "stop_price": 100, "qty": 1, "captured_at": NOW.isoformat()}


def _holdings(*specs):
    """specs: (account, symbol, shares, price, market_value)."""
    return {"as_of": NOW.isoformat(), "generated_at": NOW.isoformat(),
            "holdings": [{"account": account, "symbol": symbol, "shares": shares, "price": price,
                          "market_value": market_value, "day_change": 0}
                         for account, symbol, shares, price, market_value in specs]}


def _document(*, broker_stops, specs, planned=None, tmp_path=None):
    return truth.resolve(tmp_path, NOW, inputs={
        "holdings": _holdings(*specs), "broker_stops": broker_stops, "stop_fills": {},
        "companies": {}, "policy": {}, "planned_stops": planned or {}, "cio_status": {},
    })


def test_a_pending_activation_stop_is_not_an_unprotected_position(tmp_path):
    """One resting GTC stop and one position with no stop: only the bare one is unprotected."""
    document = _document(
        broker_stops=[_row("AWAITING_STOP_CONDITION", "SYNTH")],
        specs=[("SyntheticAccountAlpha", "SYNTH", 100, 110, 11000),
               ("SyntheticAccountAlpha", "NOSP", 50, 100, 5000)],
        tmp_path=tmp_path)
    resting, bare = document["positions"]["rows"]
    # The armed-stop figure is untouched: a resting order is not an armed one.
    assert resting["broker_protected"] is False
    assert resting["stop_state"] == "pending_activation"
    assert document["stops"]["pending_count"] == 1
    # But the resting order protects: the unprotected figures name only the bare position.
    assert document["stops"]["unprotected_count"] == 1
    assert document["positions"]["unprotected_value_usd"] == 5000.0
    assert bare["stop_state"] == "none"


def test_an_armed_stop_is_protected_exactly_as_before(tmp_path):
    document = _document(
        broker_stops=[_row("WORKING", "SYNTH")],
        specs=[("SyntheticAccountAlpha", "SYNTH", 100, 110, 11000),
               ("SyntheticAccountAlpha", "NOSP", 50, 100, 5000)],
        tmp_path=tmp_path)
    armed = document["positions"]["rows"][0]
    assert armed["broker_protected"] is True
    assert document["stops"]["active_count"] == 1
    assert document["stops"]["unprotected_count"] == 1
    assert document["positions"]["unprotected_value_usd"] == 5000.0


def test_a_planned_level_alone_is_still_unprotected(tmp_path):
    """A level in stops.json is a recommendation, not an order: the operator asked for only REAL protection."""
    document = _document(
        broker_stops=[],
        specs=[("SyntheticAccountAlpha", "SYNTH", 100, 110, 11000),
               ("SyntheticAccountAlpha", "NOSP", 50, 100, 5000)],
        planned={"SYNTH:SyntheticAccountAlpha": {"account": "SyntheticAccountAlpha", "stop": 100,
                                                 "set_date": "2026-11-01"}},
        tmp_path=tmp_path)
    planned_pos = document["positions"]["rows"][0]
    assert planned_pos["stop_source"] == "planned"
    assert planned_pos["broker_protected"] is False
    assert document["stops"]["unprotected_count"] == 2
    assert document["positions"]["unprotected_value_usd"] == 16000.0


def test_the_count_and_the_value_name_their_own_universes(tmp_path):
    """`unprotected_count` counts rows >= $100; `unprotected_value_usd` sums every row. The split says which is which."""
    document = _document(
        broker_stops=[],
        specs=[("SyntheticAccountAlpha", "NOSP", 50, 100, 5000),
               ("SyntheticAccountAlpha", "DUST", 0.9, 100, 90)],  # under the $100 counting threshold
        tmp_path=tmp_path)
    pos = document["positions"]
    assert document["stops"]["unprotected_count"] == 1  # the count speaks about counted positions only
    assert pos["unprotected_counted_value_usd"] == 5000.0
    assert pos["unprotected_residual_value_usd"] == 90.0
    assert pos["unprotected_value_usd"] == 5090.0  # the wide total still feeds pct_protected
    assert pos["unprotected_counted_value_usd"] + pos["unprotected_residual_value_usd"] == pos["unprotected_value_usd"]


def test_a_stale_pending_stop_stays_unproven_and_never_becomes_protection(tmp_path):
    """An old broker read cannot establish current protection either way (the existing unproven rule)."""
    old = {**_row("AWAITING_STOP_CONDITION", "SYNTH"), "captured_at": "2026-10-01T15:00:00Z"}
    document = _document(
        broker_stops=[old],
        specs=[("SyntheticAccountAlpha", "SYNTH", 100, 110, 11000),
               ("SyntheticAccountAlpha", "NOSP", 50, 100, 5000)],
        tmp_path=tmp_path)
    stale = document["positions"]["rows"][0]
    assert stale["stop_state"] == "unknown"
    assert document["stops"]["unproven_count"] == 1
    # One stale read withholds the whole-book definite figures (they are not a zero)...
    assert document["stops"]["unprotected_count"] is None
    assert document["positions"]["unprotected_value_usd"] is None
    # ...and the stale resting row is never promoted to protection by this rule.
    assert stale["broker_protected"] is False
    assert document["stops"]["unproven_count"] == 1 and document["stops"]["active_count"] == 0

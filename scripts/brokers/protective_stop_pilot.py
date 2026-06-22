"""Stage 2c protective-stop pilot — build + request-2FA + submit a protective SELL stop on a REAL holding.

This is the protective-stop analogue of schwab_stage2b_canary_preflight: it constructs the exact Schwab
order JSON for a SELL STOP / STOP_LIMIT / TRAILING_STOP (GTC) and a gate-consistent OrderIntent stamped
with the PROTECTIVE_STOP_2C marker so execution_guard routes it through protective_stop_policy (its OWN
committed envelope) INSTEAD of the BUY-only canary gate. Nothing here widens a gate; every submit still
passes the full live stack (taxable-only assert → api_write_enabled → guard → per-order 2FA).

Flow (mirrors the canary console): build_order() → request_2fa() (telegram+email code + web typed-ticker)
→ operator approves either channel → submit() (schwab_transport.place_order, kind='protective_stop').
"""
from __future__ import annotations

import sys
import uuid
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Schwab order_kind aliases — the UI uses "STOP" / "STOP_LIMIT" / "TRAILING"; normalize to policy names.
_KIND_ALIASES = {"STOP": "STOP", "STOP_LIMIT": "STOP_LIMIT", "STOPLIMIT": "STOP_LIMIT",
                 "TRAILING": "TRAILING_STOP", "TRAILING_STOP": "TRAILING_STOP", "TRAIL": "TRAILING_STOP",
                 # MARKET = the synthetic-stop EXIT for fractional positions: Schwab rejects a resting STOP on
                 # a fractional qty but ACCEPTS a Market-Day sell of the full qty. Used as the sell-all trigger.
                 "MARKET": "MARKET", "MKT": "MARKET", "SELL_ALL": "MARKET", "MARKET_DAY": "MARKET"}


def _money(v) -> str:
    return str(Decimal(str(v)).quantize(Decimal("0.01")))


def normalize_kind(order_kind: str) -> str:
    return _KIND_ALIASES.get((order_kind or "").strip().upper(), "")


def build_order_spec(symbol: str, qty, order_kind: str, *, stop_price=None,
                     limit_price=None, trail_pct=None) -> dict:
    """Exact Schwab order JSON for a protective SELL stop. Single-leg, EQUITY, SINGLE strategy, GTC."""
    ot = normalize_kind(order_kind)
    if not ot:
        raise ValueError(f"unknown order_kind {order_kind!r}")
    leg = {"instruction": "SELL", "quantity": qty,
           "instrument": {"symbol": symbol.upper(), "assetType": "EQUITY"}}
    spec: dict = {"session": "NORMAL", "duration": "GOOD_TILL_CANCEL",
                  "orderType": ot, "orderStrategyType": "SINGLE", "orderLegCollection": [leg]}
    if ot == "STOP":
        if stop_price is None:
            raise ValueError("STOP requires stop_price")
        spec["stopPrice"] = _money(stop_price)
    elif ot == "STOP_LIMIT":
        if stop_price is None:
            raise ValueError("STOP_LIMIT requires stop_price")
        spec["stopPrice"] = _money(stop_price)
        spec["price"] = _money(limit_price if limit_price is not None else stop_price)
    elif ot == "TRAILING_STOP":
        if trail_pct is None:
            raise ValueError("TRAILING_STOP requires trail_pct")
        spec["stopPriceLinkBasis"] = "LAST"
        spec["stopPriceLinkType"] = "PERCENT"
        spec["stopPriceOffset"] = float(trail_pct)
    elif ot == "MARKET":
        # Synthetic-stop EXIT: sell the FULL (fractional) qty at market. Schwab requires DAY for fractional
        # market orders (no GTC, no stopPrice/price). This is the order the synthetic monitor fires on breach.
        spec["duration"] = "DAY"
    return spec


def build_intent(account_key: str, symbol: str, qty, order_kind: str, *, stop_price=None,
                 limit_price=None, trail_pct=None, advised_stop=None, current_price=None,
                 held_qty=None, replace_order_id=None):
    """Gate-consistent OrderIntent stamped PROTECTIVE_STOP_2C. Direction stays LONG (the SELL closes the
    long). The non-intent envelope fields (advised stop, live price, held qty, order_type) ride in
    meta.signal_evidence where the guard's protective gate reads them."""
    from brokers.order_intent import (OrderIntent, Instrument, Direction, EntrySpec, EntryMethod,
                                       Quantity, TIF, SessionPolicy, IntentMeta)
    from brokers.execution_guard import PROTECTIVE_STOP_MARKER
    ot = normalize_kind(order_kind)
    if ot == "STOP":
        entry = EntrySpec(method=EntryMethod.STOP, stop_price=float(stop_price))
    elif ot == "STOP_LIMIT":
        entry = EntrySpec(method=EntryMethod.STOP_LIMIT, stop_price=float(stop_price),
                          limit_price=float(limit_price if limit_price is not None else stop_price))
    elif ot == "MARKET":  # synthetic-stop EXIT: market sell-all of a fractional position (no resting price)
        entry = EntrySpec(method=EntryMethod.MARKET)
    else:  # TRAILING_STOP — stamp the live reference so structural validation has a price
        entry = EntrySpec(method=EntryMethod.STOP,
                          stop_price=float(stop_price) if stop_price is not None else float(current_price or 0))
    meta = IntentMeta(strategy_id=PROTECTIVE_STOP_MARKER, created_by="operator",
                      thesis=f"Stage 2c protective {ot} on held {symbol.upper()}",
                      signal_evidence={"instruction": "SELL", "order_type": ot,
                                       "stop_price": float(stop_price) if stop_price is not None else None,
                                       "advised_stop": float(advised_stop) if advised_stop is not None else None,
                                       "current_price": float(current_price) if current_price is not None else None,
                                       "held_qty": float(held_qty) if held_qty is not None else None,
                                       "trail_pct": float(trail_pct) if trail_pct is not None else None,
                                       "replace_order_id": (str(replace_order_id) if replace_order_id else None)})
    return OrderIntent(
        instrument=Instrument(symbol.upper()), direction=Direction.LONG, entry=entry,
        quantity=Quantity(qty=float(qty)), broker="schwab", account_key=account_key,
        tif=TIF.GTC, session=SessionPolicy.NORMAL, meta=meta,
        intent_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
    )


def request_2fa(intent) -> dict:
    """Create the per-order approval set (web typed-ticker + telegram/email code) and notify the operator.
    EITHER channel suffices (REQUIRED_CHANNELS=1)."""
    from brokers import approval_service
    return approval_service.request_approval(intent)


def submit(account_key: str, order_spec: dict, intent) -> dict:
    """Submit through the proven transport once 2FA is satisfied. Tagged kind='protective_stop' so it
    does not consume the canary 5-order budget. Raises ExecutionBlocked/NotProvenWrite on any closed lock."""
    import schwab_transport
    return schwab_transport.place_order(account_key, order_spec, intent, kind="protective_stop")


def load_intent(intent_id: str):
    """Rehydrate a persisted protective-stop OrderIntent from broker_order_intents (written at request_2fa).
    Returns None if absent or not a protective-stop intent."""
    from db_adapter import _get_conn
    from brokers.order_intent import OrderIntent
    from brokers.execution_guard import PROTECTIVE_STOP_MARKER
    cur = _get_conn().cursor()
    cur.execute("SELECT intent_json FROM broker_order_intents WHERE intent_id=%s", (str(intent_id),))
    r = cur.fetchone()
    if not r or not r[0]:
        return None
    payload = r[0] if isinstance(r[0], dict) else __import__("json").loads(r[0])
    intent = OrderIntent.from_dict(payload)
    if getattr(getattr(intent, "meta", None), "strategy_id", None) != PROTECTIVE_STOP_MARKER:
        return None
    return intent


def spec_from_intent(intent) -> dict:
    """Reconstruct the exact Schwab order_spec from a (re)loaded protective-stop intent — used at the
    confirm/submit step so the spec is never trusted from the client between request and submit."""
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    ot = ev.get("order_type") or "STOP"
    return build_order_spec(intent.instrument.symbol, intent.quantity.qty, ot,
                            stop_price=getattr(intent.entry, "stop_price", None),
                            limit_price=getattr(intent.entry, "limit_price", None),
                            trail_pct=ev.get("trail_pct"))


def order_summary(symbol: str, qty, order_kind: str, *, stop_price=None, limit_price=None,
                  trail_pct=None) -> dict:
    """Human-facing summary the modal echoes back (qty / type / price / TIF)."""
    ot = normalize_kind(order_kind)
    if ot == "TRAILING_STOP":
        line = f"SELL {qty} {symbol.upper()} TRAILING STOP {trail_pct}% GTC"
    elif ot == "STOP_LIMIT":
        line = f"SELL {qty} {symbol.upper()} STOP-LIMIT (stop ${stop_price} / limit ${limit_price or stop_price}) GTC"
    else:
        line = f"SELL {qty} {symbol.upper()} STOP ${stop_price} GTC"
    return {"symbol": symbol.upper(), "qty": qty, "order_type": ot, "stop_price": stop_price,
            "limit_price": limit_price, "trail_pct": trail_pct, "tif": "GTC", "ticket": line}

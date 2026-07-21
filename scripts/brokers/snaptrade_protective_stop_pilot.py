"""SnapTrade / Fidelity protective-stop pilot — mirrors protective_stop_pilot.py (Stage 2c + 2FA).

Routes:
  • broker API (SnapTrade place) when BROKER_API_ENABLED + allows_trading — future / non-Fidelity brokers
  • monitored arm (fidelity_monitored_stop) for fidelity_rollover_ira — production path today
"""
from __future__ import annotations

import json
import sys
import uuid
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brokers.execution_guard import PROTECTIVE_STOP_MARKER, FIDELITY_PROTECTIVE_MARKER

_KIND_ALIASES = {"STOP": "STOP", "STOP_LIMIT": "STOP_LIMIT", "STOPLIMIT": "STOP_LIMIT",
                 "TRAILING": "TRAILING_STOP", "TRAILING_STOP": "TRAILING_STOP", "TRAIL": "TRAILING_STOP"}


def normalize_kind(order_kind: str) -> str:
    return _KIND_ALIASES.get((order_kind or "").strip().upper(), "")


def _money(v) -> str:
    return str(Decimal(str(v)).quantize(Decimal("0.01")))


def build_intent(account_key: str, symbol: str, qty, order_kind: str, *, stop_price=None,
                 limit_price=None, trail_pct=None, limit_offset=None, advised_stop=None,
                 current_price=None, held_qty=None, replace_order_id=None, replace_stop_id=None):
    # limit_offset: accepted for signature parity with the Schwab pilot; Fidelity/SnapTrade
    # has no native trailing-stop-limit, so it is ignored here.
    from brokers.order_intent import (OrderIntent, Instrument, Direction, EntrySpec, EntryMethod,
                                       Quantity, TIF, SessionPolicy, IntentMeta)
    ot = normalize_kind(order_kind)
    if ot == "STOP":
        entry = EntrySpec(method=EntryMethod.STOP, stop_price=float(stop_price))
    elif ot == "STOP_LIMIT":
        entry = EntrySpec(method=EntryMethod.STOP_LIMIT, stop_price=float(stop_price),
                          limit_price=float(limit_price if limit_price is not None else stop_price))
    else:
        entry = EntrySpec(method=EntryMethod.STOP,
                          stop_price=float(stop_price) if stop_price is not None else float(current_price or 0))
    marker = FIDELITY_PROTECTIVE_MARKER if (account_key or "").startswith("fidelity") else PROTECTIVE_STOP_MARKER
    broker = "fidelity" if (account_key or "").startswith("fidelity") else "snaptrade"
    meta = IntentMeta(strategy_id=marker, created_by="operator",
                      thesis=f"Fidelity/SnapTrade protective {ot} on held {symbol.upper()}",
                      signal_evidence={"instruction": "SELL", "order_type": ot,
                                       "stop_price": float(stop_price) if stop_price is not None else None,
                                       "advised_stop": float(advised_stop) if advised_stop is not None else None,
                                       "current_price": float(current_price) if current_price is not None else None,
                                       "held_qty": float(held_qty) if held_qty is not None else None,
                                       "trail_pct": float(trail_pct) if trail_pct is not None else None,
                                       "replace_order_id": (str(replace_order_id) if replace_order_id else None),
                                       "replace_stop_id": (int(replace_stop_id) if replace_stop_id else None)})
    return OrderIntent(
        instrument=Instrument(symbol.upper()), direction=Direction.LONG, entry=entry,
        quantity=Quantity(qty=float(qty)), broker=broker, account_key=account_key,
        tif=TIF.GTC, session=SessionPolicy.NORMAL, meta=meta,
        intent_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
    )


def request_2fa(intent) -> dict:
    from brokers import approval_service
    return approval_service.request_approval(intent)


def route_after_2fa(account_key: str, intent) -> dict:
    """After 2FA satisfied: broker API submit OR arm monitored stop."""
    from brokers import approval_service
    from brokers.execution_guard import require
    require(intent, "submit")
    approval_service.consume(intent.intent_id)
    from brokers import snaptrade_trade as st
    from brokers.snaptrade_protective_stop_policy import BROKER_API_ENABLED
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    ot = ev.get("order_type") or "STOP"
    sym = intent.instrument.symbol
    qty = intent.quantity.qty if intent.quantity else 0
    if BROKER_API_ENABLED:
        ok, detail = st.broker_allows_trading()
        if ok and st.ENABLED:
            import snaptrade_transport
            spec = spec_from_intent(intent)
            return snaptrade_transport.place_order(account_key, spec, intent)
    import fidelity_monitored_stop as fms
    return fms.arm(sym, account_key, ev.get("stop_price") or getattr(intent.entry, "stop_price", 0), qty,
                   order_type=ot, trail_pct=ev.get("trail_pct"), limit_price=getattr(intent.entry, "limit_price", None),
                   note=f"armed via 2FA intent {intent.intent_id[:8]}", replace_of=ev.get("replace_stop_id"))


def load_intent(intent_id: str):
    from db_adapter import _get_conn
    from brokers.order_intent import OrderIntent
    cur = _get_conn().cursor()
    cur.execute("SELECT intent_json FROM broker_order_intents WHERE intent_id=%s", (str(intent_id),))
    r = cur.fetchone()
    if not r or not r[0]:
        return None
    payload = r[0] if isinstance(r[0], dict) else json.loads(r[0])
    intent = OrderIntent.from_dict(payload)
    sid = getattr(getattr(intent, "meta", None), "strategy_id", None)
    if sid not in (PROTECTIVE_STOP_MARKER, FIDELITY_PROTECTIVE_MARKER):
        return None
    return intent


def order_summary(symbol: str, qty, order_kind: str, *, stop_price=None, limit_price=None,
                  trail_pct=None, limit_offset=None, account_key: str | None = None) -> dict:
    from fidelity_monitored_stop import ticket_line, FIDELITY_TICKET_PLATFORM
    ot = normalize_kind(order_kind)
    ticket = ticket_line(symbol, qty, ot, stop_price=stop_price, limit_price=limit_price, trail_pct=trail_pct)
    platform = FIDELITY_TICKET_PLATFORM if (account_key or "").startswith("fidelity") else "SnapTrade"
    return {"symbol": symbol.upper(), "qty": qty, "order_type": ot, "stop_price": stop_price,
            "limit_price": limit_price, "trail_pct": trail_pct, "tif": "GTC", "ticket": ticket,
            "platform": platform}


def spec_from_intent(intent) -> dict:
    """SnapTrade preview payload fields from intent."""
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    ot = ev.get("order_type") or "STOP"
    from brokers.snaptrade_protective_stop_policy import SNAPTRADE_ORDER_MAP
    st_type = SNAPTRADE_ORDER_MAP.get(ot, "Stop")
    return {"action": "SELL", "order_type": st_type, "units": intent.quantity.qty,
            "stop": getattr(intent.entry, "stop_price", None),
            "price": getattr(intent.entry, "limit_price", None),
            "symbol": intent.instrument.symbol}
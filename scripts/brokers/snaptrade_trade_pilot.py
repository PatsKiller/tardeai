"""SnapTrade one-share test pilot — preview → 2FA → place (no sandbox).

Mirrors Schwab Stage 2b discipline for the FIRST live proof on a trade-capable SnapTrade brokerage:
exactly 1 share, capped notional, per-order 2FA. Fidelity remains read-only — this path only fires when
broker_allows_trading() is true (e.g. a future tradable connection).
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brokers.snaptrade_trade import (
    SNAPTRADE_ONE_SHARE_TEST_MARKER, ONE_SHARE_TEST_EXACT_UNITS,
    evaluate_envelope, preview, place, broker_allows_trading, is_one_share_test_unlocked,
)
from brokers.snaptrade_transport import account_key_to_snaptrade_id, resolve_and_preview


def build_intent(account_key: str, symbol: str, action: str, order_type: str, *,
                 units: float = 1.0, price: float | None = None, stop: float | None = None,
                 trade_id: str | None = None, preview_body: dict | None = None):
    from brokers.order_intent import (OrderIntent, Instrument, Direction, EntrySpec, EntryMethod,
                                       Quantity, TIF, SessionPolicy, IntentMeta)
    act = (action or "BUY").upper()
    direction = Direction.LONG  # BUY open or SELL-to-close a long — one-share proof only
    ot = (order_type or "Market").strip()
    if ot.lower() == "market":
        entry = EntrySpec(method=EntryMethod.MARKET)
    elif ot.lower() == "limit":
        entry = EntrySpec(method=EntryMethod.LIMIT, limit_price=float(price or 0))
    else:
        entry = EntrySpec(method=EntryMethod.LIMIT, limit_price=float(price or 0))
    meta = IntentMeta(
        strategy_id=SNAPTRADE_ONE_SHARE_TEST_MARKER,
        created_by="operator",
        thesis=f"SnapTrade one-share test {act} {symbol.upper()}",
        signal_evidence={
            "action": act, "order_type": ot, "units": float(units),
            "price": float(price) if price is not None else None,
            "stop": float(stop) if stop is not None else None,
            "trade_id": trade_id, "one_share_test": True,
            "preview": preview_body or {},
        },
    )
    return OrderIntent(
        instrument=Instrument(symbol.upper()), direction=direction, entry=entry,
        quantity=Quantity(qty=float(units)), broker="snaptrade", account_key=account_key,
        tif=TIF.DAY, session=SessionPolicy.NORMAL, meta=meta,
        intent_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
    )


def preflight(*, account_key: str, symbol: str, action: str = "BUY", order_type: str = "Market",
              price: float | None = None, stop: float | None = None, units: float | None = None,
              one_share_test: bool = True) -> dict:
    """Non-executing: envelope + broker capability + SnapTrade preview + 2FA request."""
    sym = (symbol or "").strip().upper()
    act = (action or "BUY").upper()
    ot = (order_type or "Market").strip()
    u = float(units if units is not None else ONE_SHARE_TEST_EXACT_UNITS)
    if one_share_test:
        u = ONE_SHARE_TEST_EXACT_UNITS
    if not is_one_share_test_unlocked():
        return {"ok": False, "error": "one-share test not armed — run: "
                "snaptrade_pilot_arm.py --arm-test --confirm \"ARM SNAPTRADE ONE SHARE TEST <date>\""}
    ok, reasons = evaluate_envelope(
        account_key=account_key, action=act, order_type=ot, units=u, price=price, one_share_test=True)
    if not ok:
        return {"ok": False, "error": "; ".join(reasons), "envelope": "one_share_test"}
    bok, bdetail = broker_allows_trading()
    if not bok:
        return {"ok": False, "error": f"broker not tradeable via SnapTrade: {bdetail}",
                "hint": "Fidelity is read-only on SnapTrade — connect a trade-capable brokerage first."}
    aid = account_key_to_snaptrade_id(account_key)
    if not aid:
        return {"ok": False, "error": f"account {account_key!r} not mapped in config/snaptrade_accounts.json"}
    try:
        prev = resolve_and_preview(
            account_id=aid, symbol=sym, action=act, order_type=ot, units=u, price=price, stop=stop)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "stage": "preview"}
    trade_id = prev.get("trade_id") or prev.get("id")
    if not trade_id:
        return {"ok": False, "error": "preview returned no trade_id", "preview": prev}
    intent = build_intent(account_key, sym, act, ot, units=u, price=price, stop=stop,
                          trade_id=str(trade_id), preview_body=prev)
    from brokers import approval_service
    req = approval_service.request_approval(intent)
    if not req.get("ok"):
        return {"ok": False, "error": req.get("reason") or "2FA request failed", "preview": prev}
    return {
        "ok": True,
        "mode": "one_share_test",
        "intent_id": intent.intent_id,
        "units": u,
        "symbol": sym,
        "account": account_key,
        "order_type": ot,
        "action": act,
        "preview": prev,
        "trade_id": trade_id,
        "channels": req.get("channels"),
        "ttl_min": req.get("ttl_min"),
        "note": f"ONE-SHARE TEST: exactly {u:g} share — approve 2FA then execute. No sandbox; this is live money.",
    }


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
    if getattr(getattr(intent, "meta", None), "strategy_id", None) != SNAPTRADE_ONE_SHARE_TEST_MARKER:
        return None
    return intent


def execute(intent_id: str) -> dict:
    """Place after full 2FA approval."""
    from brokers import approval_service
    intent = load_intent(intent_id)
    if intent is None:
        return {"ok": False, "error": "intent not found or expired"}
    if not approval_service.is_fully_approved(intent_id):
        return {"ok": False, "error": "2FA not complete"}
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    trade_id = ev.get("trade_id")
    if not trade_id:
        return {"ok": False, "error": "missing trade_id on intent"}
    u = float(ev.get("units") or ONE_SHARE_TEST_EXACT_UNITS)
    ok, reasons = evaluate_envelope(
        account_key=intent.account_key,
        action=ev.get("action", "BUY"),
        order_type=ev.get("order_type", "Market"),
        units=u, price=ev.get("price"), one_share_test=True, for_place=True)
    if not ok:
        return {"ok": False, "error": "; ".join(reasons)}
    approval_service.consume(intent_id)
    try:
        res = place(trade_id=str(trade_id), confirmed=True, one_share_test=True)
    except Exception as e:
        return {"ok": False, "error": str(e)[:240], "stage": "place"}
    _audit(intent, res)
    return {"ok": True, "status": "submitted", "result": res, "trade_id": trade_id,
            "units": u, "symbol": intent.instrument.symbol, "account": intent.account_key}


def _audit(intent, result: dict):
    try:
        from db_adapter import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS snaptrade_test_orders (
            id SERIAL PRIMARY KEY, intent_id TEXT, account_key TEXT, symbol TEXT, action TEXT,
            units NUMERIC, order_type TEXT, trade_id TEXT, status TEXT, detail JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW())""")
        ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
        cur.execute("""INSERT INTO snaptrade_test_orders
                       (intent_id, account_key, symbol, action, units, order_type, trade_id, status, detail)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (intent.intent_id, intent.account_key, intent.instrument.symbol,
                     ev.get("action"), ev.get("units"), ev.get("order_type"),
                     ev.get("trade_id"), result.get("status") or "submitted",
                     json.dumps(result, default=str)[:8000]))
        conn.commit()
    except Exception:
        pass
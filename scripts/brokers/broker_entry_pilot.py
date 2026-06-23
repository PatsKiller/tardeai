"""broker_entry_pilot.py — Schwab queue entry: LIMIT buy + protective STOP (OTOCO) with per-order 2FA.

Flow mirrors protective_stop_pilot:
  build_intent() → translate OTOCO → request_2fa() → operator approves → submit().

After fill, schwab_broker_trade_monitor.py tracks the open trade and proposes stop adjustments
(cancel + replace via protective_stop_pilot MODIFY path).
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brokers.execution_guard import QUEUE_ENTRY_MARKER


def _get_proposal(proposal_id: int) -> dict | None:
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    cur.execute(
        """SELECT id, symbol, strategy_id, status,
                  COALESCE(target_account, proposed_account, intended_broker) AS account,
                  intended_broker, proposed_entry, proposed_stop, proposed_target1,
                  proposed_shares, proposed_rr
           FROM paper_trade_proposals WHERE id=%s""",
        (proposal_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def build_intent(
    account_key: str,
    symbol: str,
    shares: int,
    entry: float,
    stop: float,
    *,
    target: float | None = None,
    strategy_id: str = "momentum_scalp",
    proposal_id: int | None = None,
):
    from brokers.order_intent import (
        OrderIntent, Instrument, Direction, EntrySpec, EntryMethod, Quantity,
        TIF, SessionPolicy, IntentMeta, ExitPolicy, StopSpec, TargetSpec,
    )
    exit_policy = ExitPolicy(
        stop=StopSpec(price=float(stop)),
        targets=[TargetSpec(price=float(target), qty_pct=100.0)] if target and target > 0 else [],
        oco=bool(target and target > 0),
    )
    meta = IntentMeta(
        strategy_id=QUEUE_ENTRY_MARKER,
        created_by="operator",
        thesis=f"Queue entry bracket {symbol.upper()} limit ${entry} stop ${stop}",
        signal_evidence={
            "proposal_id": proposal_id,
            "strategy_id": strategy_id,
            "entry": float(entry),
            "stop": float(stop),
            "target": float(target) if target else None,
            "shares": int(shares),
        },
    )
    return OrderIntent(
        instrument=Instrument(symbol.upper()),
        direction=Direction.LONG,
        entry=EntrySpec(method=EntryMethod.LIMIT, limit_price=float(entry)),
        exit_policy=exit_policy,
        quantity=Quantity(qty=float(int(shares))),
        broker="schwab",
        account_key=account_key,
        tif=TIF.DAY,
        session=SessionPolicy.NORMAL,
        meta=meta,
        intent_id=str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()),
    )


def translate_bracket(intent) -> dict:
    from brokers.translators import schwab as schwab_tr
    return schwab_tr.translate(intent)


def order_spec_from_intent(intent) -> dict:
    return spec_from_intent(intent)


def spec_from_intent(intent) -> dict:
    """Reconstruct Schwab OTOCO spec from persisted intent — never trust client between request/submit."""
    tr = translate_bracket(intent)
    orders = tr.get("orders") or []
    if not orders:
        raise ValueError("bracket translation produced no orders")
    return orders[0]


def request_2fa(intent) -> dict:
    from brokers import approval_service
    out = approval_service.request_approval(intent)
    out["mode"] = "awaiting_approval"
    return out


def submit(account_key: str, order_spec: dict, intent) -> dict:
    import schwab_transport
    return schwab_transport.place_order(account_key, order_spec, intent, kind="queue_entry")


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
    if getattr(getattr(intent, "meta", None), "strategy_id", None) != QUEUE_ENTRY_MARKER:
        return None
    return intent


def order_summary(intent) -> dict:
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    sym = (getattr(getattr(intent, "instrument", None), "symbol", None) or "").upper()
    entry = getattr(intent.entry, "limit_price", None)
    stop = (intent.exit_policy.stop.price if intent.exit_policy and intent.exit_policy.stop else None)
    tgt = (intent.exit_policy.targets[0].price if intent.exit_policy and intent.exit_policy.targets else None)
    qty = intent.quantity.qty if intent.quantity else None
    lines = [f"BUY {qty} {sym} LIMIT ${entry} DAY"]
    if stop:
        lines.append(f"child STOP ${stop} GTC")
    if tgt:
        lines.append(f"child TARGET LIMIT ${tgt} GTC (OCO)")
    return {
        "symbol": sym,
        "qty": qty,
        "entry": entry,
        "stop": stop,
        "target": tgt,
        "summary": " · ".join(lines),
        "proposal_id": ev.get("proposal_id"),
    }


def request_route(proposal_id: int) -> dict:
    """Step 1: build bracket from proposal + request per-order 2FA."""
    prop = _get_proposal(proposal_id)
    if not prop:
        return {"ok": False, "error": f"proposal #{proposal_id} not found"}
    acct = str(prop.get("account") or "").strip()
    if not acct.startswith("schwab"):
        return {"ok": False, "error": "proposal is not routed to a Schwab account"}
    sym = str(prop.get("symbol") or "").upper()
    shares = int(prop.get("proposed_shares") or 0)
    entry = float(prop.get("proposed_entry") or 0)
    stop = float(prop.get("proposed_stop") or 0)
    target = float(prop.get("proposed_target1") or 0) if prop.get("proposed_target1") else None
    if not (sym and shares > 0 and entry > 0 and stop > 0 and entry > stop):
        return {"ok": False, "error": "proposal missing valid entry/stop/shares for bracket entry"}

    intent = build_intent(
        acct, sym, shares, entry, stop,
        target=target,
        strategy_id=str(prop.get("strategy_id") or "momentum_scalp"),
        proposal_id=proposal_id,
    )
    spec = order_spec_from_intent(intent)
    try:
        req = request_2fa(intent)
    except Exception as e:
        return {"ok": False, "error": f"2FA request failed: {str(e)[:160]}"}

    return {
        "ok": True,
        "mode": "awaiting_approval",
        "intent_id": intent.intent_id,
        "proposal_id": proposal_id,
        "symbol": sym,
        "account": acct,
        "order_spec": spec,
        "bracket": True,
        "summary": order_summary(intent),
        "ttl_min": req.get("ttl_min"),
        "note": "Approve via web ticker or Telegram/email code, then POST route/confirm",
    }


def _extract_child_stop_id(readback: dict) -> str | None:
    """Best-effort parse of child STOP order id from Schwab readback."""
    if not isinstance(readback, dict):
        return None
    for child in readback.get("childOrderStrategies") or []:
        for sub in child.get("childOrderStrategies") or [child]:
            if str(sub.get("orderType") or "").upper() in ("STOP", "TRAILING_STOP"):
                return str(sub.get("orderId") or sub.get("order_id") or "") or None
            for leg in sub.get("orderLegCollection") or []:
                if leg:
                    pass
        if str(child.get("orderType") or "").upper() in ("STOP", "TRAILING_STOP"):
            return str(child.get("orderId") or "") or None
    return None


def persist_route_result(proposal_id: int, submit_res: dict, intent) -> None:
    """Link proposal → broker orders + seed paper_trade row for Schwab monitoring."""
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    broker_oid = submit_res.get("broker_order_id")
    readback = submit_res.get("readback") or {}
    stop_oid = _extract_child_stop_id(readback)
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    sym = (getattr(getattr(intent, "instrument", None), "symbol", None) or "").upper()
    acct = intent.account_key
    entry = float(ev.get("entry") or getattr(intent.entry, "limit_price", 0) or 0)
    stop = float(ev.get("stop") or 0)
    target = float(ev.get("target")) if ev.get("target") else None
    shares = int(ev.get("shares") or intent.quantity.qty or 0)
    strat = str(ev.get("strategy_id") or "momentum_scalp")
    route_meta = {
        "queue_entry_bracket": True,
        "broker_order_id": broker_oid,
        "stop_order_id": stop_oid,
        "submitted_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }

    cur.execute(
        """UPDATE paper_trade_proposals
           SET routing_state='routed',
               paper_broker_order_id=%s,
               sizing_basis=COALESCE(sizing_basis, '{}'::jsonb) || %s::jsonb,
               updated_at=NOW()
           WHERE id=%s""",
        (broker_oid, json.dumps(route_meta), proposal_id),
    )

    cur.execute(
        """SELECT id FROM paper_trades
           WHERE proposal_id=%s AND status IN ('pending','open')
           ORDER BY id DESC LIMIT 1""",
        (proposal_id,),
    )
    existing = cur.fetchone()
    dollar_risk = round(abs(entry - stop) * shares, 2) if entry and stop and shares else None
    dollar_size = round(entry * shares, 2) if entry and shares else None
    if existing:
        cur.execute(
            """UPDATE paper_trades
               SET broker_order_id=%s, stop_order_id=%s, bracket_order=true, order_type='bracket',
                   stop_loss=%s, planned_stop=%s, current_stop=%s, target_1=%s,
                   shares=%s, entry_price=%s, planned_entry=%s, dollar_risk=%s, dollar_size=%s,
                   account=%s, target_account=%s, broker='schwab', execution_broker='schwab',
                   execution_account=%s, opened_via='broker_entry_bracket', status='open',
                   broker_submitted_at=NOW(), updated_at=NOW()
               WHERE id=%s""",
            (broker_oid, stop_oid, stop, stop, stop, target, shares, entry, entry,
             dollar_risk, dollar_size, acct, acct, acct, existing[0]),
        )
    else:
        cur.execute(
            """INSERT INTO paper_trades
                   (symbol, strategy_id, status, shares, entry_price, entry_time, planned_entry,
                    stop_loss, planned_stop, current_stop, target_1, dollar_risk, dollar_size,
                    account, target_account, broker, execution_broker, execution_account,
                    proposal_id, order_type, bracket_order, stop_order_id, broker_order_id,
                    opened_via, logged_by, broker_submitted_at)
               VALUES (%s,%s,'open',%s,%s,NOW(),%s,%s,%s,%s,%s,%s,%s,%s,%s,'schwab','schwab',%s,
                       %s,'bracket',true,%s,%s,'broker_entry_bracket','broker_entry_pilot',NOW())""",
            (sym, strat, shares, entry, entry, stop, stop, stop, target, dollar_risk, dollar_size,
             acct, acct, acct, proposal_id, stop_oid, broker_oid),
        )
    conn.commit()


def confirm_and_submit(intent_id: str) -> dict:
    """Step 2 after 2FA: submit bracket + persist linkage. Caller must verify approval first."""
    intent = load_intent(intent_id)
    if intent is None:
        return {"ok": False, "error": "no queue-entry intent for that id (expired?)"}
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    proposal_id = ev.get("proposal_id")
    spec = spec_from_intent(intent)
    try:
        res = submit(intent.account_key, spec, intent)
    except Exception as e:
        return {"ok": False, "stage": "submit", "error": str(e)[:240]}
    ok = res.get("status") in ("submitted", "filled")
    if ok and proposal_id:
        try:
            persist_route_result(int(proposal_id), res, intent)
        except Exception as pe:
            return {"ok": True, "stage": "submit", "result": res, "persist_warning": str(pe)[:160]}
    return {"ok": ok, "stage": "submit", "result": res,
            "broker_order_id": res.get("broker_order_id"), "status": res.get("status"),
            "account": intent.account_key, "proposal_id": proposal_id}
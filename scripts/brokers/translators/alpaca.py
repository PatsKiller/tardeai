"""Alpaca order translator — PURE: OrderIntent -> the exact bracket/market payload our paper pipeline uses
(parity with alpaca_paper_adapter.py:504-523 / proposal_paper_submitter bracket shape). No I/O."""
from __future__ import annotations

from ..order_intent import OrderIntent, Direction, EntryMethod


def translate(intent: OrderIntent) -> dict:
    notes, unverified = [], []
    qty = intent.quantity.qty or 0
    side = "buy" if intent.direction == Direction.LONG else "sell"
    p: dict = {"symbol": intent.instrument.symbol, "qty": str(qty), "side": side,
               "type": intent.entry.method.value.lower() if intent.entry.method in
                       (EntryMethod.MARKET, EntryMethod.LIMIT) else "limit",
               "time_in_force": "day" if intent.tif.value == "DAY" else "gtc"}
    if intent.entry.limit_price:
        p["limit_price"] = str(intent.entry.limit_price)
    xp = intent.exit_policy
    if xp.stop and xp.targets and xp.oco and len(xp.targets) == 1 and not xp.stop.trail:
        p["order_class"] = "bracket"
        p["take_profit"] = {"limit_price": str(xp.targets[0].price)}
        p["stop_loss"] = {"stop_price": str(xp.stop.price)}
    elif xp.stop and xp.stop.trail:
        notes.append("DEGRADED: trailing -> monitor-synthetic replace_stop (Alpaca paper pattern)")
        if xp.stop.price:
            p["_separate_stop"] = {"type": "stop", "stop_price": str(xp.stop.price),
                                   "time_in_force": "gtc"}
    elif xp.stop:
        p["_separate_stop"] = {"type": "stop", "stop_price": str(xp.stop.price), "time_in_force": "gtc"}
    if len(xp.targets) > 1:
        notes.append("COMPOSED: multi-target via monitor partial closes (not broker-native)")
    if intent.session.value != "NORMAL":
        p["extended_hours"] = True
        notes.append("extended hours: limit-only on Alpaca")
    return {"orders": [p], "notes": notes, "unverified": unverified}

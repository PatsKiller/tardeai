"""Pure projection of broker account/working-order evidence into available resources."""
from __future__ import annotations

import re

from scripts.lib.options_workflow import number

_OCC = re.compile(r"^([A-Z0-9.]+)\s*(\d{6})([CP])(\d{8})$")
_TERMINAL = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED", "REPLACED"}


def project(raw, orders, *, as_of):
    acct = (raw or {}).get("securitiesAccount") or {}
    balance = acct.get("currentBalances") or {}
    cash = number(balance.get("cashAvailableForTrading"))
    if cash is None:
        cash = number(balance.get("cashBalance"))
    bp = number(balance.get("buyingPower"))
    if bp is None and acct.get("type") == "CASH":
        bp = cash
    shares, reserved_shares = {}, {}
    reserved_cash = 0.0
    complete = "positions" in acct and isinstance(orders, list)

    def reserve(symbol, qty, *, option=False, multiplier=None):
        nonlocal reserved_cash, complete
        if not option:
            reserved_shares[symbol] = reserved_shares.get(symbol, 0) + qty
            return
        match = _OCC.fullmatch(str(symbol))
        mult = number(multiplier)
        # Existing short positions do not always supply a multiplier. A listed,
        # standard OCC identity alone does not prove its deliverable.
        if not match or mult is None or mult <= 0 or qty < 0:
            complete = False
            return
        underlying, _, right, strike = match.groups()
        if right == "C":
            reserved_shares[underlying] = reserved_shares.get(underlying, 0) + qty * mult
        else:
            reserved_cash += qty * mult * int(strike) / 1000

    for p in acct.get("positions") or []:
        ins = p.get("instrument") or {}
        long, short = number(p.get("longQuantity")), number(p.get("shortQuantity"))
        if long is None or short is None or min(long, short) < 0:
            complete = False
            continue
        if ins.get("assetType") == "EQUITY":
            shares[ins.get("symbol")] = shares.get(ins.get("symbol"), 0) + long - short
        elif ins.get("assetType") == "OPTION" and short > 0:
            if ins.get("nonStandard") or ins.get("optionDeliverablesList"):
                complete = False
            reserve(ins.get("symbol"), short, option=True, multiplier=ins.get("multiplier"))
    def flatten(items):
        for order in items:
            yield order
            yield from flatten(order.get("childOrderStrategies") or [])

    for order in flatten(orders if isinstance(orders, list) else []):
        if str(order.get("status") or "").upper() in _TERMINAL:
            continue
        remaining = number(order.get("remainingQuantity"))
        if remaining is None or remaining < 0:
            complete = False
            continue
        total = number(order.get("quantity"))
        for leg in order.get("orderLegCollection") or []:
            ins = leg.get("instrument") or {}
            qty = number(leg.get("quantity"))
            if qty is None or qty < 0 or total is None or total <= 0 or remaining > total:
                complete = False
                continue
            qty = qty * remaining / total
            instruction = leg.get("instruction")
            if instruction in {"SELL", "SELL_TO_OPEN"}:
                reserve(ins.get("symbol"), qty, option=ins.get("assetType") == "OPTION", multiplier=ins.get("multiplier"))
            elif instruction in {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"}:
                price = number(order.get("price"))
                mult = number(ins.get("multiplier")) if ins.get("assetType") == "OPTION" else 1
                if price is None or price <= 0 or mult is None or mult <= 0:
                    complete = False
                else:
                    reserved_cash += price * qty * mult
            elif instruction != "SELL_TO_CLOSE":
                complete = False
            if ins.get("nonStandard") or ins.get("optionDeliverablesList"):
                complete = False  # Adjusted coverage requires verified deliverable allocation.
    return {"as_of": as_of, "positions_complete": "positions" in acct,
            "commitments_complete": complete,
            "uncommitted_shares": {s: max(0, q - reserved_shares.get(s, 0)) for s, q in shares.items()},
            "available_cash": max(0, cash - reserved_cash) if cash is not None else None,
            "buying_power": max(0, bp - reserved_cash) if bp is not None else None,
            "reserved_cash": reserved_cash, "reserved_shares": reserved_shares,
            "basis": "Broker balances minus identified positions and pending commitments; conservative reserve"}

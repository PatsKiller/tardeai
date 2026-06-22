"""Schwab order translator — PURE function: OrderIntent -> Schwab order payload dict(s).

ADR-B1 rule 1: NO I/O here, no schwab-py import, no transport import — the payload shape follows the
official SDK schema (VERIFIED-SDK; runtime acceptance UNVERIFIED). This module can never violate the write
fence because it cannot reach the network by construction.

Output shape per Schwab order spec: {session, duration, orderType, orderStrategyType, orderLegCollection,
price?, stopPrice?, stopPriceLinkBasis?, stopPriceLinkType?, stopPriceOffset?, childOrderStrategies?}
"""
from __future__ import annotations

from ..order_intent import (OrderIntent, Direction, EntryMethod, TIF, SessionPolicy,
                            StopSpec, TargetSpec, AssetType, SpreadType)

_TIF = {"DAY": "DAY", "GTC": "GOOD_TILL_CANCEL", "FOK": "FILL_OR_KILL",
        "IOC": "IMMEDIATE_OR_CANCEL", "EOW": "END_OF_WEEK", "EOM": "END_OF_MONTH"}
_ENTRY_TYPE = {"MARKET": "MARKET", "LIMIT": "LIMIT", "STOP": "STOP", "STOP_LIMIT": "STOP_LIMIT",
               "MARKET_ON_CLOSE": "MARKET_ON_CLOSE", "LIMIT_ON_CLOSE": "LIMIT_ON_CLOSE"}


def _leg(intent: OrderIntent, instruction: str, qty: float) -> dict:
    return {"instruction": instruction, "quantity": qty,
            "instrument": {"symbol": intent.instrument.symbol, "assetType": "EQUITY"}}


def _entry_instruction(d: Direction) -> str:
    return "BUY" if d == Direction.LONG else "SELL_SHORT"


def _exit_instruction(d: Direction) -> str:
    return "SELL" if d == Direction.LONG else "BUY_TO_COVER"


def _stop_order(intent: OrderIntent, stop: StopSpec, qty: float) -> dict:
    o = {"session": intent.session.value, "duration": "GOOD_TILL_CANCEL",
         "orderStrategyType": "SINGLE",
         "orderLegCollection": [_leg(intent, _exit_instruction(intent.direction), qty)]}
    if stop.trail:
        o["orderType"] = "TRAILING_STOP"
        o["stopPriceLinkBasis"] = stop.trail.basis.value
        o["stopPriceLinkType"] = stop.trail.type.value
        o["stopPriceOffset"] = stop.trail.offset
    else:
        o["orderType"] = "STOP"
        o["stopPrice"] = str(stop.price)
    return o


def _target_order(intent: OrderIntent, t: TargetSpec, qty: float) -> dict:
    return {"session": intent.session.value, "duration": "GOOD_TILL_CANCEL", "orderType": "LIMIT",
            "price": str(t.price), "orderStrategyType": "SINGLE",
            "orderLegCollection": [_leg(intent, _exit_instruction(intent.direction), qty)]}


def _occ_symbol(underlying: str, expiration: str, option_type: str, strike: float) -> str:
    from datetime import datetime
    exp = (expiration or "")[:10]
    dt = datetime.strptime(exp, "%Y-%m-%d")
    yymmdd = dt.strftime("%y%m%d")
    cp = "C" if (option_type or "call").lower() == "call" else "P"
    strike_int = int(round(float(strike) * 1000))
    return f"{underlying.upper().strip()}{yymmdd}{cp}{strike_int:08d}"


def _option_leg(leg: dict) -> dict:
    occ = _occ_symbol(
        leg["underlying"], leg["expiration"], leg.get("option_type", "call"), float(leg["strike"]),
    )
    side = (leg.get("side") or "BUY").upper()
    instr = "BUY_TO_OPEN" if side == "BUY" else "SELL_TO_OPEN"
    return {
        "instruction": instr,
        "quantity": int(leg.get("quantity") or 1),
        "instrument": {"symbol": occ, "assetType": "OPTION"},
    }


def _translate_options(intent: OrderIntent) -> dict:
    notes, unverified = [], []
    legs = intent.instrument.option_legs or []
    contracts = int(intent.quantity.contracts or 1)
    if intent.instrument.spread_type == SpreadType.CREDIT_SPREAD and len(legs) == 2:
        order = {
            "session": intent.session.value,
            "duration": "DAY",
            "orderType": "NET_CREDIT",
            "orderStrategyType": "SINGLE",
            "orderLegCollection": [_option_leg(legs[0]), _option_leg(legs[1])],
        }
        if intent.entry.limit_price:
            order["price"] = str(intent.entry.limit_price)
        unverified.append("NET_CREDIT vertical spread: runtime acceptance UNVERIFIED")
        return {"orders": [order], "notes": notes, "unverified": unverified}
    leg = _option_leg(legs[0])
    leg["quantity"] = contracts
    order = {
        "session": intent.session.value,
        "duration": "DAY",
        "orderType": "LIMIT" if intent.entry.limit_price else "MARKET",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [leg],
    }
    if intent.entry.limit_price:
        order["price"] = str(intent.entry.limit_price)
    unverified.append("single-leg option: runtime acceptance UNVERIFIED")
    return {"orders": [order], "notes": notes, "unverified": unverified}


def translate(intent: OrderIntent) -> dict:
    """Returns {"orders": [payload, ...], "notes": [...], "unverified": [...]}.
    Ladders expand into N orders; everything else is one (possibly TRIGGER/OCO) order."""
    if intent.instrument.asset_type == AssetType.OPTION or intent.instrument.option_legs:
        return _translate_options(intent)
    notes, unverified = [], []
    qty = float(intent.quantity.qty or 0)
    if intent.ladder:
        orders = []
        for leg in intent.ladder.legs:
            sub = OrderIntent.from_dict({**intent.to_dict(),
                                         "ladder": None,
                                         "entry": {**intent.to_dict()["entry"],
                                                   "method": "LIMIT", "limit_price": leg.entry_price},
                                         "quantity": {"qty": round(qty * leg.qty_pct / 100, 4)}})
            r = translate(sub)
            orders += r["orders"]
        notes.append(f"ladder expanded to {len(orders)} orders; cancel_policy="
                     f"{intent.ladder.cancel_policy} is coordinated by US, not the broker")
        return {"orders": orders, "notes": notes, "unverified": unverified}

    entry: dict = {"session": intent.session.value, "duration": _TIF[intent.tif.value],
                   "orderType": _ENTRY_TYPE[intent.entry.method.value],
                   "orderStrategyType": "SINGLE",
                   "orderLegCollection": [_leg(intent, _entry_instruction(intent.direction), qty)]}
    if intent.entry.limit_price:
        entry["price"] = str(intent.entry.limit_price)
    elif intent.entry.entry_range:
        entry["price"] = str(intent.entry.entry_range["high"] if intent.direction == Direction.LONG
                             else intent.entry.entry_range["low"])
        notes.append("entry_range mapped to its protective bound (LIMIT at range edge); "
                     "range working is a product concept, not a broker structure")
    if intent.entry.stop_price:
        entry["stopPrice"] = str(intent.entry.stop_price)
    if intent.entry.price_link:
        entry["priceLinkBasis"] = intent.entry.price_link.basis.value
        entry["priceLinkType"] = intent.entry.price_link.type.value
        entry["priceLinkOffset"] = intent.entry.price_link.offset
        unverified.append("priceLink* fields: VERIFIED-SDK shape; runtime acceptance UNVERIFIED")

    xp = intent.exit_policy
    children = []
    if xp.stop and xp.targets and xp.oco:
        # OTOCO: TRIGGER entry -> child OCO {targets..., stop}
        oco_children = [_target_order(intent, t, round(qty * t.qty_pct / 100, 4)) for t in xp.targets]
        oco_children.append(_stop_order(intent, xp.stop, qty))
        children = [{"orderStrategyType": "OCO", "childOrderStrategies": oco_children}]
        if len(xp.targets) > 1:
            unverified.append("multi-target OCO qty split: runtime acceptance UNVERIFIED")
    elif xp.stop:
        children = [_stop_order(intent, xp.stop, qty)]
    elif xp.targets:
        children = [_target_order(intent, t, round(qty * t.qty_pct / 100, 4)) for t in xp.targets]

    if children:
        entry["orderStrategyType"] = "TRIGGER"
        entry["childOrderStrategies"] = children

    return {"orders": [entry], "notes": notes, "unverified": unverified}

"""Options order pilot — build + 2FA + submit Schwab option orders (Stage Options-1).

Routes through OPTIONS_EXECUTION_MARKER → options_execution_policy envelope.
kind='options' on schwab_pilot_orders — does not consume canary order cap.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

OPTIONS_EXECUTION_MARKER = "OPTIONS_EXECUTION_1"

_INSTRUCTION = {
    "covered_call": "SELL_TO_OPEN",
    "cash_secured_put": "SELL_TO_OPEN",
    "long_call": "BUY_TO_OPEN",
    "long_put": "BUY_TO_OPEN",
    "credit_spread_short": "SELL_TO_OPEN",
    "credit_spread_long": "BUY_TO_OPEN",
}


def _occ_symbol(underlying: str, expiration: str, option_type: str, strike: float) -> str:
    """Build Schwab OCC symbol (simplified)."""
    from datetime import datetime
    exp = expiration[:10]
    dt = datetime.strptime(exp, "%Y-%m-%d")
    yymmdd = dt.strftime("%y%m%d")
    cp = "C" if option_type.lower() == "call" else "P"
    strike_int = int(round(strike * 1000))
    root = underlying.upper().ljust(6)[:6]
    return f"{root.strip()}{yymmdd}{cp}{strike_int:08d}"


def build_single_leg_spec(
    underlying: str,
    expiration: str,
    option_type: str,
    strike: float,
    contracts: int,
    strategy: str,
    *,
    limit_price: float | None = None,
    order_type: str = "LIMIT",
) -> dict:
    instr = _occ_symbol(underlying, expiration, option_type, strike)
    instr_side = "call" if option_type.lower() == "call" else "put"
    instruction = _INSTRUCTION.get(strategy, "SELL_TO_OPEN")
    leg = {
        "instruction": instruction,
        "quantity": int(contracts),
        "instrument": {"symbol": instr, "assetType": "OPTION"},
    }
    spec = {
        "session": "NORMAL",
        "duration": "DAY",
        "orderType": order_type,
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [leg],
    }
    if limit_price is not None and order_type == "LIMIT":
        spec["price"] = str(Decimal(str(limit_price)).quantize(Decimal("0.01")))
    return spec


def build_credit_spread_spec(
    underlying: str,
    expiration: str,
    option_type: str,
    short_strike: float,
    long_strike: float,
    contracts: int,
    *,
    net_credit: float,
) -> dict:
    short_occ = _occ_symbol(underlying, expiration, option_type, short_strike)
    long_occ = _occ_symbol(underlying, expiration, option_type, long_strike)
    legs = [
        {"instruction": "SELL_TO_OPEN", "quantity": int(contracts),
         "instrument": {"symbol": short_occ, "assetType": "OPTION"}},
        {"instruction": "BUY_TO_OPEN", "quantity": int(contracts),
         "instrument": {"symbol": long_occ, "assetType": "OPTION"}},
    ]
    return {
        "session": "NORMAL",
        "duration": "DAY",
        "orderType": "NET_CREDIT",
        "price": str(Decimal(str(net_credit)).quantize(Decimal("0.01"))),
        "orderStrategyType": "SINGLE",
        "orderLegCollection": legs,
    }


def build_intent(
    account_key: str,
    proposal: dict,
    *,
    held_qty: float | None = None,
) -> "OrderIntent":
    from brokers.order_intent import (
        OrderIntent, Instrument, Direction, EntrySpec, EntryMethod,
        Quantity, TIF, SessionPolicy, IntentMeta, AssetType, OptionLeg, SpreadType,
    )
    strategy = proposal.get("strategy") or "covered_call"
    sym = proposal.get("underlying") or proposal.get("symbol")
    contracts = int(proposal.get("contracts") or 1)
    premium = float(proposal.get("premium") or 0)
    legs = []
    if strategy == "credit_spread":
        legs = [
            OptionLeg(sym, proposal.get("option_type", "put"), proposal.get("short_strike"),
                      proposal.get("expiration"), "SELL", contracts).to_dict(),
            OptionLeg(sym, proposal.get("option_type", "put"), proposal.get("long_strike"),
                      proposal.get("expiration"), "BUY", contracts).to_dict(),
        ]
    else:
        legs = [OptionLeg(sym, proposal.get("option_type", "call"), proposal.get("strike"),
                          proposal.get("expiration"), "SELL" if "sell" in strategy or strategy == "covered_call" else "BUY",
                          contracts).to_dict()]
    notional = premium * 100 * contracts
    spread_w = None
    if strategy == "credit_spread" and proposal.get("short_strike") and proposal.get("long_strike"):
        spread_w = abs(float(proposal["short_strike"]) - float(proposal["long_strike"])) / max(float(proposal["short_strike"]), 1) * 100
    meta = IntentMeta(
        strategy_id=OPTIONS_EXECUTION_MARKER,
        created_by="operator",
        thesis=f"Options {strategy} on {sym}",
        signal_evidence={
            "strategy": strategy,
            "order_type": "NET_CREDIT" if strategy == "credit_spread" else "LIMIT",
            "contracts": contracts,
            "notional_usd": notional,
            "spread_width_pct": spread_w,
            "held_qty": held_qty,
            "proposal_id": proposal.get("id"),
            "short_strike": proposal.get("short_strike"),
            "long_strike": proposal.get("long_strike"),
        },
    )
    direction = Direction.SHORT if strategy in ("covered_call", "cash_secured_put", "credit_spread") else Direction.LONG
    return OrderIntent(
        instrument=Instrument(
            symbol=sym.upper(),
            asset_type=AssetType.OPTION,
            option_legs=legs,
            spread_type=SpreadType.CREDIT_SPREAD if strategy == "credit_spread" else SpreadType.SINGLE,
        ),
        direction=direction,
        entry=EntrySpec(method=EntryMethod.LIMIT, limit_price=premium),
        quantity=Quantity(contracts=contracts),
        broker="schwab",
        account_key=account_key,
        tif=TIF.DAY,
        session=SessionPolicy.NORMAL,
        meta=meta,
        intent_id=str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()),
    )


def build_order_spec(proposal: dict) -> dict:
    strategy = proposal.get("strategy")
    if strategy == "credit_spread":
        return build_credit_spread_spec(
            proposal["underlying"], proposal["expiration"], proposal.get("option_type", "put"),
            float(proposal["short_strike"]), float(proposal["long_strike"]),
            int(proposal.get("contracts") or 1),
            net_credit=float(proposal.get("premium") or 0),
        )
    side = "SELL" if strategy in ("covered_call", "cash_secured_put") else "BUY"
    strat_key = strategy
    return build_single_leg_spec(
        proposal["underlying"], proposal["expiration"], proposal.get("option_type", "call"),
        float(proposal["strike"]), int(proposal.get("contracts") or 1), strat_key,
        limit_price=float(proposal.get("premium") or 0),
    )


def request_2fa(intent) -> dict:
    from brokers import approval_service
    return approval_service.request_approval(intent)


def submit(account_key: str, order_spec: dict, intent) -> dict:
    import schwab_transport
    return schwab_transport.place_order(account_key, order_spec, intent, kind="options")


def load_intent(intent_id: str):
    from db_adapter import _get_conn
    from brokers.order_intent import OrderIntent
    cur = _get_conn().cursor()
    cur.execute("SELECT intent_json FROM broker_order_intents WHERE intent_id=%s", (str(intent_id),))
    r = cur.fetchone()
    if not r or not r[0]:
        return None
    import json
    payload = r[0] if isinstance(r[0], dict) else json.loads(r[0])
    intent = OrderIntent.from_dict(payload)
    if getattr(getattr(intent, "meta", None), "strategy_id", None) != OPTIONS_EXECUTION_MARKER:
        return None
    return intent


def spec_from_intent(intent) -> dict:
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    proposal = {
        "strategy": ev.get("strategy"),
        "underlying": intent.instrument.symbol,
        "symbol": intent.instrument.symbol,
        "expiration": (intent.instrument.option_legs or [{}])[0].get("expiration"),
        "option_type": (intent.instrument.option_legs or [{}])[0].get("option_type", "call"),
        "strike": (intent.instrument.option_legs or [{}])[0].get("strike"),
        "short_strike": ev.get("short_strike") or (intent.instrument.option_legs or [{}])[0].get("strike"),
        "long_strike": (intent.instrument.option_legs or [{}, {}])[1].get("strike") if len(intent.instrument.option_legs or []) > 1 else None,
        "contracts": int(intent.quantity.contracts or 1),
        "premium": float(intent.entry.limit_price or 0),
    }
    if ev.get("proposal_id"):
        try:
            import options_engine as oe
            cached = oe._load_json(oe.PROPOSALS_CACHE)
            for p in cached.get("proposals") or []:
                if p.get("id") == ev.get("proposal_id"):
                    proposal.update(p)
                    break
        except Exception:
            pass
    return build_order_spec(proposal)
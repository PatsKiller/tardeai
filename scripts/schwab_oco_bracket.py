#!/usr/bin/env python3
"""Schwab API OCO bracket (P3) — builder + guards + 2FA-gated submit (DISABLED until canary-proven).

Builds the Schwab Trader API complex order for a SELL OCO (take-profit LIMIT + stop-loss STOP) on an
existing long, and routes a live submit through the SAME execution-guard + per-order 2FA stack as every
other live Schwab order (schwab_transport.place_order, kind='oco_bracket').

SAFETY: this is a LIVE broker order surface. The builder / validate / preview paths are PURE and safe.
The live submit (submit_oco) is FAIL-CLOSED: disabled unless OCO_BRACKETS_SCHWAB=1 AND the qty is within
the canary envelope. P3 live OCO is operator-ARM-gated, canary-bounded, and read-back verified — it is NOT
enabled by default and nothing here places a live order while the flag is off.

Design: docs/design/OCO_ATM_UNIFICATION_DESIGN.md (P3).
"""
from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP

OCO_FLAG = "OCO_BRACKETS_SCHWAB"
# Canary envelope for the FIRST live proof (mirrors the Stage 2c protective 1-share POC): tiny, whole-share.
OCO_CANARY_MAX_QTY = int(os.getenv("OCO_CANARY_MAX_QTY", "1"))


class OcoAbort(Exception):
    """Raised on any guard violation or a disabled/over-cap live submit. Fail-closed by construction."""


def _money(v) -> str:
    return str(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def flag_enabled() -> bool:
    return os.getenv(OCO_FLAG, "0") == "1"


def _is_whole_shares(qty) -> bool:
    try:
        f = float(qty)
        return f > 0 and f == int(f)
    except Exception:
        return False


def validate_oco(symbol, qty, take_profit_price, stop_price) -> bool:
    """Pure guards — raise OcoAbort on any violation.

    Fractional-share guard: Schwab REJECTS a fractional STOP leg, so a fractional position must use the
    synthetic-stop monitor (see project_fee_and_fractional_stops), never an OCO.
    """
    if not symbol or not str(symbol).strip():
        raise OcoAbort("symbol required")
    if not _is_whole_shares(qty):
        raise OcoAbort(f"fractional/zero qty {qty!r} — Schwab rejects fractional STOP legs; route to the "
                       "synthetic-stop monitor instead of an OCO")
    tp = float(take_profit_price)
    sp = float(stop_price)
    if not (tp > 0 and sp > 0):
        raise OcoAbort("take_profit and stop must both be > 0")
    if not (tp > sp):
        raise OcoAbort(f"take_profit {tp} must be above stop {sp} (long OCO: limit above, stop below)")
    return True


def _sell_single(symbol, qty, *, order_type, duration, price=None, stop_price=None) -> dict:
    """One SINGLE SELL child of the OCO — LIMIT (take-profit) or STOP (stop-loss). Same shape the proven
    Stage 2b/2c single-leg builder uses."""
    leg = {"instruction": "SELL", "quantity": int(qty),
           "instrument": {"symbol": symbol, "assetType": "EQUITY"}}
    spec = {"session": "NORMAL", "duration": duration, "orderType": order_type,
            "orderStrategyType": "SINGLE", "orderLegCollection": [leg]}
    if order_type == "LIMIT":
        spec["price"] = _money(price)
    elif order_type == "STOP":
        spec["stopPrice"] = _money(stop_price)
    return spec


def make_oco_order_spec(symbol, qty, take_profit_price, stop_price) -> dict:
    """Schwab Trader API SELL OCO: a take-profit LIMIT and a stop-loss STOP as two SINGLE children, GTC.
    Validates first (fractional guard, tp>stop). Pure — never submits."""
    validate_oco(symbol, qty, take_profit_price, stop_price)
    symbol = str(symbol).upper()
    qty = int(qty)
    return {
        "orderStrategyType": "OCO",
        "childOrderStrategies": [
            _sell_single(symbol, qty, order_type="LIMIT", duration="GOOD_TILL_CANCEL", price=take_profit_price),
            _sell_single(symbol, qty, order_type="STOP", duration="GOOD_TILL_CANCEL", stop_price=stop_price),
        ],
    }


def preview_oco_ticket(symbol, qty, take_profit_price, stop_price, account_key=None) -> dict:
    """Build the OCO spec + a human-readable ticket for the 2FA proposal UI. PURE — never submits."""
    spec = make_oco_order_spec(symbol, qty, take_profit_price, stop_price)
    return {
        "account_key": account_key, "symbol": str(symbol).upper(), "qty": int(qty),
        "take_profit": _money(take_profit_price), "stop": _money(stop_price),
        "order_strategy": "OCO", "order_spec": spec,
        "requires_2fa": True, "live_enabled": flag_enabled(),
        "note": ("Schwab OCO bracket — take-profit LIMIT + stop-loss STOP on the same shares. Operator "
                 "approval + per-order 2FA required before live submit; whole-share only."),
    }


def submit_oco(account_key, symbol, qty, take_profit_price, stop_price, intent, *, canary=True):
    """LIVE submit via the existing guard + 2FA stack (schwab_transport.place_order, kind='oco_bracket').

    FAIL-CLOSED: raises unless OCO_BRACKETS_SCHWAB=1 AND (canary) qty <= OCO_CANARY_MAX_QTY. Until the
    canary proof, P3 live OCO stays disabled — this never reaches place_order while the flag is off.
    """
    validate_oco(symbol, qty, take_profit_price, stop_price)
    if not flag_enabled():
        raise OcoAbort(f"{OCO_FLAG} is OFF — live Schwab OCO submit disabled (canary proof required first)")
    if canary and int(qty) > OCO_CANARY_MAX_QTY:
        raise OcoAbort(f"canary cap: qty {qty} exceeds OCO_CANARY_MAX_QTY={OCO_CANARY_MAX_QTY}")
    spec = make_oco_order_spec(symbol, qty, take_profit_price, stop_price)
    from schwab_transport import place_order   # full stack: readiness -> evidence -> 2FA -> idempotency -> POST
    return place_order(account_key, spec, intent, kind="oco_bracket")


if __name__ == "__main__":
    import json
    import sys
    # Safe CLI: build + preview only (never submits). Usage: schwab_oco_bracket.py SYMBOL QTY TP STOP
    if len(sys.argv) == 5:
        sym, q, tp, sp = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
        print(json.dumps(preview_oco_ticket(sym, q, tp, sp), indent=2, default=str))
    else:
        print("usage: schwab_oco_bracket.py SYMBOL QTY TAKE_PROFIT STOP   (preview only — never submits)")

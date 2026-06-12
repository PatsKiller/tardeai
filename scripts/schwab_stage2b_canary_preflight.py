#!/usr/bin/env python3
"""schwab_stage2b_canary_preflight.py — Stage 2b canary preflight, payload, and audit.

This script intentionally does NOT send, submit, cancel, replace, or modify any
Schwab order. It prepares the smallest possible Stage 2b test artifact for an
operator-run/manual Schwab test while preserving the repo's no-write invariant.

It verifies:
  - Long-only US equity shape.
  - LIMIT BUY only; no market orders.
  - Existing committed brokers.canary_gate allowlist/date envelope.
  - Stricter Stage 2b quantity cap: qty <= 3 shares.
  - price <= $4 and notional <= $40.
  - live quote confirms the symbol is still <= $4 and spread is sane.
  - verified Schwab account hash exists, without printing/logging the hash.
  - token freshness is green enough for read-back.

It outputs:
  - Exact Schwab order JSON payload for operator review.
  - A local audit JSON under logs/schwab_stage2b_canary/.
  - A typed manual confirmation phrase for the operator's own workflow.

Hard boundary:
  This file is preflight/read-only. Do not add Schwab write calls here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

LOG_DIR = PROJECT_ROOT / "logs" / "schwab_stage2b_canary"

STAGE2B_MAX_QTY_SHARES = 3
STAGE2B_MAX_PRICE_USD = Decimal("4.00")
STAGE2B_MAX_NOTIONAL_USD = Decimal("40.00")
DEFAULT_MAX_SPREAD_PCT = Decimal("1.50")
CONFIRM_TEMPLATE = "OPERATOR CONFIRMS SCHWAB CANARY {symbol} {qty}"


class CanaryAbort(RuntimeError):
    """Raised for any fail-closed precondition failure."""


@dataclass(frozen=True)
class CanaryPlan:
    account_key: str
    symbol: str
    qty: int
    limit_price: Decimal
    correlation_id: str

    @property
    def notional(self) -> Decimal:
        return self.limit_price * Decimal(self.qty)

    @property
    def operator_phrase(self) -> str:
        return CONFIRM_TEMPLATE.format(symbol=self.symbol, qty=self.qty)


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _parse_money(raw: str) -> Decimal:
    try:
        val = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise CanaryAbort(f"invalid decimal value: {raw!r}") from exc
    if val <= 0:
        raise CanaryAbort("price/spread values must be > 0")
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _clean_symbol(raw: str) -> str:
    sym = (raw or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{1,5}", sym):
        raise CanaryAbort(f"symbol {raw!r} rejected — Stage 2b allows simple US equity tickers only")
    return sym


def make_plan(account_key: str, symbol: str, qty: int, limit_price: str) -> CanaryPlan:
    if not account_key or not account_key.strip():
        raise CanaryAbort("account_key is required")
    try:
        qty_i = int(qty)
    except Exception as exc:
        raise CanaryAbort(f"qty must be an integer share count, got {qty!r}") from exc
    plan = CanaryPlan(
        account_key=account_key.strip(),
        symbol=_clean_symbol(symbol),
        qty=qty_i,
        limit_price=_parse_money(limit_price),
        correlation_id=str(uuid.uuid4()),
    )
    validate_static_envelope(plan)
    return plan


def validate_static_envelope(plan: CanaryPlan) -> None:
    if plan.qty <= 0:
        raise CanaryAbort("qty must be positive")
    if plan.qty > STAGE2B_MAX_QTY_SHARES:
        raise CanaryAbort(f"qty {plan.qty} exceeds Stage 2b cap of {STAGE2B_MAX_QTY_SHARES} shares")
    if plan.limit_price > STAGE2B_MAX_PRICE_USD:
        raise CanaryAbort(f"limit price ${_money(plan.limit_price)} exceeds ${STAGE2B_MAX_PRICE_USD}")
    if plan.notional > STAGE2B_MAX_NOTIONAL_USD:
        raise CanaryAbort(f"notional ${_money(plan.notional)} exceeds ${STAGE2B_MAX_NOTIONAL_USD}")


def make_order_spec(plan: CanaryPlan) -> dict[str, Any]:
    """Exact Schwab order JSON shape for the first Stage 2b proof: SINGLE LIMIT BUY."""
    return {
        "session": "NORMAL",
        "duration": "DAY",
        "orderType": "LIMIT",
        "price": _money(plan.limit_price),
        "orderLegCollection": [
            {
                "instruction": "BUY",
                "quantity": plan.qty,
                "instrument": {"symbol": plan.symbol, "assetType": "EQUITY"},
            }
        ],
        "orderStrategyType": "SINGLE",
    }


def make_order_intent(plan: CanaryPlan):
    from brokers.order_intent import (
        OrderIntent,
        Instrument,
        Direction,
        EntrySpec,
        EntryMethod,
        Quantity,
        TIF,
        SessionPolicy,
    )

    return OrderIntent(
        instrument=Instrument(plan.symbol),
        direction=Direction.LONG,
        entry=EntrySpec(method=EntryMethod.LIMIT, limit_price=float(plan.limit_price)),
        quantity=Quantity(qty=plan.qty),
        broker="schwab",
        account_key=plan.account_key,
        tif=TIF.DAY,
        session=SessionPolicy.NORMAL,
        correlation_id=plan.correlation_id,
    )


def require_model_and_gate(plan: CanaryPlan) -> dict[str, Any]:
    from brokers.order_intent import validate
    from brokers import canary_gate

    intent = make_order_intent(plan)
    vr = validate(intent)
    if not vr.ok:
        raise CanaryAbort(f"canonical validation failed: {vr.errors}")
    gd = canary_gate.evaluate(intent)
    if not gd.allowed:
        raise CanaryAbort(f"CANARY_GATE BLOCK: {'; '.join(gd.reasons)}")
    return {"validation_warnings": vr.warnings, "canary_gate": "allowed"}


def require_token_health(account_key: str) -> dict[str, Any]:
    import schwab_token_manager as tm

    token_key = tm.canonical_token_key("schwab", "live") or account_key
    h = tm.health(token_key, "schwab", "live")
    if h.get("degraded") or not h.get("refresh_valid"):
        raise CanaryAbort(f"Schwab token health not green for {token_key}: {h.get('last_error') or h}")
    return {
        "token_key": token_key,
        "has_token": bool(h.get("has_token")),
        "refresh_valid": bool(h.get("refresh_valid")),
        "access_fresh": bool(h.get("access_fresh")),
        "days_to_reauth": h.get("days_to_reauth"),
        "next_reauth_due_at": h.get("next_reauth_due_at"),
    }


def require_account_hash(account_key: str) -> None:
    import schwab_transport as st

    account_hash = st._get_hash(account_key)
    if not account_hash:
        raise CanaryAbort(f"no verified Schwab account hash for {account_key}; run resolve_account_hashes first")


def require_live_quote(plan: CanaryPlan, max_spread_pct: Decimal) -> dict[str, Any]:
    import schwab_transport as st

    qres = st.get_quotes([plan.symbol], account_key=plan.account_key)
    if not isinstance(qres, dict) or qres.get("status") != "ok":
        raise CanaryAbort(f"live quote check failed for {plan.symbol}: {qres}")
    q = (qres.get("quotes") or {}).get(plan.symbol) or {}
    bid = _to_decimal(q.get("bid"))
    ask = _to_decimal(q.get("ask"))
    last = _to_decimal(q.get("last"))
    ref = ask or last or bid
    if ref is None:
        raise CanaryAbort(f"live quote missing bid/ask/last for {plan.symbol}: {q}")
    if ref > STAGE2B_MAX_PRICE_USD:
        raise CanaryAbort(f"{plan.symbol} live ref ${_money(ref)} exceeds ${STAGE2B_MAX_PRICE_USD} cap")
    spread_pct = None
    if bid and ask and bid > 0 and ask >= bid:
        mid = (bid + ask) / Decimal("2")
        spread_pct = ((ask - bid) / mid * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if spread_pct > max_spread_pct:
            raise CanaryAbort(f"{plan.symbol} spread {spread_pct}% exceeds {max_spread_pct}% cap")
    return {
        "symbol": plan.symbol,
        "bid": _money(bid) if bid else None,
        "ask": _money(ask) if ask else None,
        "last": _money(last) if last else None,
        "spread_pct": str(spread_pct) if spread_pct is not None else None,
        "quote_updated": q.get("updated"),
    }


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return None


def write_audit(stage: str, plan: CanaryPlan, payload: dict[str, Any]) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = LOG_DIR / f"{ts}_{plan.symbol}_{plan.qty}sh_{plan.correlation_id[:8]}_{stage}.json"
    safe_payload = {
        "stage": stage,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "account_key": plan.account_key,
        "symbol": plan.symbol,
        "qty": plan.qty,
        "limit_price": _money(plan.limit_price),
        "notional": _money(plan.notional),
        "correlation_id": plan.correlation_id,
        **payload,
    }
    path.write_text(json.dumps(safe_payload, indent=2, sort_keys=True, default=str) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage 2b Schwab canary preflight and exact payload builder")
    ap.add_argument("--account-key", required=True, help="verified account key, e.g. schwab_taxable")
    ap.add_argument("--symbol", required=True, help="must be in committed CANARY_SYMBOL_ALLOWLIST")
    ap.add_argument("--qty", type=int, default=2, help="integer shares; Stage 2b cap is 3")
    ap.add_argument("--limit-price", required=True, help="limit price <= 4.00; first test should be far below market")
    ap.add_argument("--max-spread-pct", default=str(DEFAULT_MAX_SPREAD_PCT), help="abort if bid/ask spread wider than this percent")
    args = ap.parse_args(argv)

    try:
        plan = make_plan(args.account_key, args.symbol, args.qty, args.limit_price)
        max_spread = _parse_money(args.max_spread_pct)
        gate_info = require_model_and_gate(plan)
        token_info = require_token_health(plan.account_key)
        require_account_hash(plan.account_key)
        quote_info = require_live_quote(plan, max_spread)
        order_spec = make_order_spec(plan)
        output = {
            "ok": True,
            "mode": "PREFLIGHT_ONLY_NO_BROKER_WRITE",
            "gate": gate_info,
            "token_health": token_info,
            "quote": quote_info,
            "order_spec": order_spec,
            "operator_phrase": plan.operator_phrase,
            "account_hash_verified": True,
            "account_hash_logged": False,
            "safety_note": "This script did not send an order. Use the payload for manual/operator-approved Stage 2b review only.",
        }
        audit_path = write_audit("preflight", plan, output)
        output["audit"] = str(audit_path)
        print(json.dumps(output, indent=2, default=str))
        return 0
    except CanaryAbort as exc:
        print(json.dumps({"ok": False, "blocked": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

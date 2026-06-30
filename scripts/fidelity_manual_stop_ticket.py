#!/usr/bin/env python3
"""Fidelity manual protective-stop tickets.

Fidelity stays manual-only: this helper creates copyable ticket text and local
ledger payloads. It contains no broker-write client and no submit path.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from typing import Any

MANUAL_STATUSES = {"MANUAL_PENDING", "MANUAL_PLACED", "MANUAL_SKIPPED", "MANUAL_NOT_APPLICABLE"}
SUPPORTED_ORDER_TYPES = {"STOP", "STOP_LIMIT", "TRAILING_STOP"}
UNSUPPORTED_INSTRUMENTS = {"mutual_fund", "money_market", "money_market_fund", "cash", "unsupported_fund"}


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def build_ticket(
    *,
    account: str,
    symbol: str,
    shares: float,
    order_type: str,
    current_price: float | None = None,
    stop_price: float | None = None,
    trail_pct: float | None = None,
    limit_price: float | None = None,
    tif: str = "GTC",
    rationale: str = "",
    source_timestamp: str | None = None,
    instrument_type: str = "equity",
) -> dict[str, Any]:
    broker = "Fidelity"
    sym = symbol.upper().strip()
    inst = instrument_type.lower().strip()
    whole_qty = int(_f(shares))
    residual = round(_f(shares) - whole_qty, 6)
    ot = order_type.upper().strip()
    if inst in UNSUPPORTED_INSTRUMENTS or sym in {"FCNTX", "SPAXX"}:
        return {
            "ok": True,
            "status": "MANUAL_NOT_APPLICABLE",
            "broker": broker,
            "account": account,
            "symbol": sym,
            "note": "NOT APPLICABLE — mutual fund / money-market; review allocation/rebalance instead.",
            "controls_hidden": True,
        }
    if ot not in SUPPORTED_ORDER_TYPES:
        return {"ok": False, "error": f"unsupported Fidelity manual order type {order_type!r}"}
    lines = [
        "Manual Fidelity ticket only — no API submit from Trade AI.",
        f"Account: {account}",
        f"Broker: {broker}",
        f"Action: SELL",
        f"Symbol: {sym}",
        f"Quantity: {whole_qty} whole shares",
    ]
    if residual > 0:
        lines.append(f"Residual: {residual:.6f} shares remain monitored/manual.")
    lines.append(f"Order type: {ot}")
    if ot in {"STOP", "STOP_LIMIT"}:
        lines.append(f"Stop price: ${_f(stop_price):.2f}")
    if ot == "STOP_LIMIT":
        lines.append(f"Limit price: ${_f(limit_price if limit_price is not None else stop_price):.2f}")
    if ot == "TRAILING_STOP":
        lines.append(f"Trailing percent: {_f(trail_pct):.2f}%")
    if current_price is not None:
        lines.append(f"Current price: ${_f(current_price):.2f}")
    lines.append(f"TIF: {tif}")
    if source_timestamp:
        lines.append(f"Source timestamp: {source_timestamp}")
    if rationale:
        lines.append(f"Rationale: {rationale}")
    return {
        "ok": True,
        "status": "MANUAL_PENDING",
        "broker": broker,
        "account": account,
        "symbol": sym,
        "whole_qty": whole_qty,
        "residual_qty": residual,
        "order_type": ot,
        "stop_price": stop_price,
        "trail_pct": trail_pct,
        "tif": tif,
        "copy_text": "\n".join(lines),
        "open_url": "https://digital.fidelity.com/ftgw/digital/portfolio/summary",
    }


def transition_status(ticket: dict[str, Any], status: str, *, operator: str, note: str = "") -> dict[str, Any]:
    st = status.upper().strip()
    if st not in MANUAL_STATUSES:
        return {"ok": False, "error": f"unknown manual status {status!r}"}
    out = dict(ticket)
    out.update({
        "ok": True,
        "status": st,
        "operator": operator,
        "note": note,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "audit_event": "fidelity_manual_stop_status",
    })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Create a copyable Fidelity manual stop ticket.")
    ap.add_argument("--account", required=True)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--shares", type=float, required=True)
    ap.add_argument("--order-type", default="STOP")
    ap.add_argument("--current-price", type=float)
    ap.add_argument("--stop-price", type=float)
    ap.add_argument("--trail-pct", type=float)
    ap.add_argument("--limit-price", type=float)
    ap.add_argument("--rationale", default="")
    args = ap.parse_args()
    print(json.dumps(build_ticket(
        account=args.account,
        symbol=args.symbol,
        shares=args.shares,
        order_type=args.order_type,
        current_price=args.current_price,
        stop_price=args.stop_price,
        trail_pct=args.trail_pct,
        limit_price=args.limit_price,
        rationale=args.rationale,
    ), indent=2))


if __name__ == "__main__":
    main()

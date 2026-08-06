#!/usr/bin/env python3
"""Stop-out review and re-entry watch helpers.

Advisory only: this module creates review/watch data from journal lifecycle
facts. It never routes orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def build_stop_out_reviews(lifecycle: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for sym, rec in sorted(lifecycle.items()):
        for trade in rec.get("round_trips") or []:
            pnl = float(trade.get("realized_pnl") or 0.0)
            if pnl >= 0:
                continue
            cost = float(trade.get("cost_basis") or 0.0)
            proceeds = float(trade.get("proceeds") or 0.0)
            qty = float(trade.get("qty") or 0.0)
            avg_cost = cost / qty if qty else 0.0
            exit_price = proceeds / qty if qty else 0.0
            loss_pct = (pnl / cost * 100.0) if cost else 0.0
            reviews.append({
                "symbol": sym,
                "account": rec.get("account"),
                "avg_cost": round(avg_cost, 4),
                "exit_price": round(exit_price, 4),
                "realized_pnl": round(pnl, 2),
                "realized_pnl_pct": round(loss_pct, 2),
                "stop_type": "unknown_or_manual",
                "stop_price": round(exit_price, 4),
                "advisor_stop_at_time": None,
                "live_stop_at_time": None,
                "policy_quality": (
                    "Stop was more than 10% below avg cost; review whether initial-risk cap was too loose."
                    if loss_pct <= -10 else
                    "Stopped-out loss; compare stop distance to initial-risk cap and current support/ATR."
                ),
                "reason_for_exit": "stopped_out_or_sold_loss",
                "timestamp": trade.get("date"),
                "decision": "STOPPED_OUT_REVIEW",
                "reentry_watch": True,
            })
    return reviews


def build_reentry_watch(reviews: list[dict[str, Any]],
                        thesis_map: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Build advisory re-entry watch rows from stop-out reviews.

    thesis_map: optional {symbol: thesis_text} — injected by the API layer from
    watchlist entry plans, CIO synthesis, or deterministic thesis engine so the
    watch desk surfaces a concrete re-entry rationale per symbol instead of
    leaving the thesis field blank.
    """
    _thesis = thesis_map or {}
    watch: list[dict[str, Any]] = []
    for r in reviews:
        sym = r["symbol"]
        thesis = _thesis.get(sym, "")
        # Symbol-specific triggers: start with the universal checklist, then
        # append thesis-specific conditions when a thesis is available.
        triggers = [
            "reclaim stop level",
            "reclaim 20d/50d moving average",
            "volume confirmation",
            "Finviz setup hit",
            "positive catalyst/news",
            "sector confirmation",
            "RSI recovery",
            "spread/liquidity ok",
            "no conflicting thesis break",
        ]
        if thesis:
            # When we know the re-entry thesis, add symbol-specific gates
            triggers.append("thesis intact — re-entry premise still holds")
            triggers.append("entry zone hit — price in or below planned zone")
        watch.append({
            "symbol": sym,
            "exit_price": r["exit_price"],
            "realized_pnl": r["realized_pnl"],
            "why_stopped": r["policy_quality"],
            "thesis": thesis,
            "triggers": triggers,
            "status": "WAIT",
            "decision": "REENTRY_WATCH",
            "advisory_only": True,
        })
    return watch


def main() -> None:
    ap = argparse.ArgumentParser(description="Build advisory stop-out reviews and re-entry watch rows.")
    ap.add_argument("--account")
    ap.add_argument("--days", type=int, default=365)
    args = ap.parse_args()
    from journal_ticker_lifecycle import aggregate_ticker_activity, load_from_db
    lifecycle = aggregate_ticker_activity(load_from_db(args.account, args.days))
    reviews = build_stop_out_reviews(lifecycle)
    print(json.dumps({"reviews": reviews, "reentry_watch": build_reentry_watch(reviews)}, indent=2, default=str))


if __name__ == "__main__":
    main()

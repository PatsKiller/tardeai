#!/usr/bin/env python3
"""Populate catalyst_symbol_impact for the names Trade-AI tracks.

2026-09-15 audit: the table existed with 0 rows ever, so no surface could say what a catalyst meant
for a tracked name. For recent catalyst_events on active watchlist names, pending proposals and
holdings this writes one row per (event, symbol):

  price_at_event        last close on or before the event day (ticker_prices)
  expected_direction    UP / DOWN / NEUTRAL from the catalyst type
  expected_magnitude    impact_score when present
  portfolio_impact_pct  the holding's weight in the portfolio (0 when not held)

Deterministic, no model calls. Default is a dry run that prints counts and samples; --apply writes.
Idempotent: an (event, symbol) pair already present is skipped.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Same holdings file the strategy-card materializer reads.
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

UP_TYPES = {"analyst_upgrade", "earnings_beat", "contract_win", "contract", "insider_buy", "guidance_raise",
            "merger_acquisition", "fda_approval", "buyback", "dividend_increase", "short_squeeze", "bullish",
            "partnership", "product_launch", "patent", "institutional_build", "institutional_buying",
            "institutional_investment", "stock_price_increase", "earnings_momentum"}
DOWN_TYPES = {"analyst_downgrade", "earnings_miss", "insider_sell", "guidance_cut", "guidance_lower", "offering",
              "offering_dilution", "private_placement", "capital_raise", "dividend_cut", "fda_rejection", "lawsuit",
              "legal_action", "class_action", "bankruptcy", "delisting", "bearish", "negative_news",
              "negative_news_momentum", "margin_pressure", "reverse_stock_split"}


def expected_direction(catalyst_type: str | None) -> str:
    t = str(catalyst_type or "").lower()
    if t in UP_TYPES:
        return "UP"
    if t in DOWN_TYPES:
        return "DOWN"
    return "NEUTRAL"


def portfolio_weights(holdings: dict) -> dict[str, float]:
    """Symbol → percent of total market value, from holdings.json (`holdings`, legacy `positions`)."""
    positions = None
    if isinstance(holdings, dict):
        positions = holdings.get("holdings") if isinstance(holdings.get("holdings"), list) else holdings.get("positions")
    if not isinstance(positions, list):
        return {}
    values: dict[str, float] = {}
    for p in positions:
        if not isinstance(p, dict) or p.get("is_cash"):
            continue
        sym = str(p.get("symbol") or "").upper()
        try:
            mv = float(p.get("market_value") or p.get("value") or 0)
        except (TypeError, ValueError):
            mv = 0.0
        if sym and mv > 0:
            values[sym] = values.get(sym, 0.0) + mv
    total = sum(values.values())
    return {s: round(100.0 * v / total, 3) for s, v in values.items()} if total > 0 else {}


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def plan_rows(cur, days: int, weights: dict[str, float]) -> list[dict]:
    cur.execute(
        """WITH tracked AS (
               SELECT upper(symbol) s FROM watchlist_items WHERE status = 'active'
               UNION SELECT upper(symbol) FROM paper_trade_proposals WHERE status IN ('PENDING','APPROVED_FOR_PAPER_TEST')
               UNION SELECT unnest(%s::text[])
           )
           SELECT ce.id, upper(ce.symbol) AS symbol, ce.strategy_type, ce.catalyst_type, ce.impact_score,
                  COALESCE(ce.published_at, ce.created_at) AS ts,
                  (SELECT tp.close_price FROM ticker_prices tp
                    WHERE tp.symbol = upper(ce.symbol) AND tp.price_date <= COALESCE(ce.published_at, ce.created_at)::date
                    ORDER BY tp.price_date DESC LIMIT 1) AS price_at_event
             FROM catalyst_events ce
             JOIN tracked t ON t.s = upper(ce.symbol)
            WHERE COALESCE(ce.published_at, ce.created_at) > now() - make_interval(days => %s)
              AND COALESCE(ce.identity_status, 'CONFIRMED') <> 'UNRESOLVABLE'
              AND NOT EXISTS (SELECT 1 FROM catalyst_symbol_impact csi
                               WHERE csi.catalyst_event_id = ce.id AND upper(csi.symbol) = upper(ce.symbol))
            ORDER BY ts DESC""",
        (sorted(weights), int(days)),
    )
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        row = dict(zip(cols, r))
        out.append({
            "catalyst_event_id": row["id"], "symbol": row["symbol"], "strategy_type": row["strategy_type"],
            "price_at_event": row["price_at_event"],
            "expected_direction": expected_direction(row["catalyst_type"]),
            "expected_magnitude": row["impact_score"],
            "portfolio_impact_pct": weights.get(row["symbol"], 0.0),
            "_type": row["catalyst_type"], "_ts": str(row["ts"])[:16],
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    try:
        holdings = json.loads((STATE_DIR / "holdings.json").read_text())
    except Exception:
        holdings = {}
    weights = portfolio_weights(holdings)
    conn = _conn()
    cur = conn.cursor()
    rows = plan_rows(cur, a.days, weights)
    written = 0
    if a.apply and rows:
        for r in rows:
            cur.execute(
                """INSERT INTO catalyst_symbol_impact
                       (catalyst_event_id, symbol, strategy_type, price_at_event, expected_direction,
                        expected_magnitude, portfolio_impact_pct, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s, now())""",
                (r["catalyst_event_id"], r["symbol"], r["strategy_type"], r["price_at_event"],
                 r["expected_direction"], r["expected_magnitude"], r["portfolio_impact_pct"]))
            written += 1
        conn.commit()
    else:
        conn.rollback()
    if a.apply:
        receipt = PROJECT_ROOT / "data" / "runtime" / "catalyst_symbol_impact_last_run.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        receipt.write_text(json.dumps({"as_of": datetime.now(timezone.utc).isoformat(), "days": a.days,
                                       "candidates": len(rows), "written": written}, indent=2))
    by_dir: dict[str, int] = {}
    for r in rows:
        by_dir[r["expected_direction"]] = by_dir.get(r["expected_direction"], 0) + 1
    print(json.dumps({"mode": "apply" if a.apply else "dry_run", "days": a.days, "candidates": len(rows),
                      "written": written, "by_direction": by_dir,
                      "with_price_at_event": sum(1 for r in rows if r["price_at_event"] is not None),
                      "held_symbols_touched": len({r["symbol"] for r in rows if r["portfolio_impact_pct"]}),
                      "sample": [{k: v for k, v in r.items() if k in ("symbol", "_type", "_ts", "price_at_event", "expected_direction")}
                                 for r in rows[:5]]}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

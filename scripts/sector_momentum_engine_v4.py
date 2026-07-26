#!/usr/bin/env python3
"""Sector momentum v4 launcher with deterministic uncapped covered breadth.

This additive launcher replaces only the breadth producer in ``sector_momentum_engine``.
It preserves the established date-aligned RS, state, debounce, alert and snapshot logic.
The result is explicitly a covered screener-membership measure, not official ETF
constituent breadth.

The launcher remains inactive until an operator explicitly changes the host invocation.
"""
from __future__ import annotations

import json
from pathlib import Path

import sector_momentum_engine as base

ROOT = Path(__file__).resolve().parent.parent
POLICY = json.loads((ROOT / "config" / "defense_breadth_policy.json").read_text())


def breadth_v4(cur, sector_name: str):
    """Return exact-20-session breadth with deterministic uncapped membership."""
    try:
        cur.execute(
            """SELECT DISTINCT upper(m.symbol) AS symbol
                 FROM screener_symbol_membership m
                 JOIN trade_ai_scans t ON upper(t.symbol) = upper(m.symbol)
                WHERE t.sector = ANY(%s)
                ORDER BY upper(m.symbol)""",
            (base._aliases(sector_name),),
        )
        members = [row[0] for row in cur.fetchall()]
        membership_n = len(members)
        minimum_members = int(POLICY["minimum_covered_members"])
        if membership_n < minimum_members:
            return None, 0, membership_n, "insufficient_membership"

        cur.execute(
            """WITH daily AS (
                   SELECT upper(symbol) AS symbol, price_date,
                          max(close_price) AS close_price
                     FROM ticker_prices
                    WHERE upper(symbol) = ANY(%s)
                      AND price_date > CURRENT_DATE - 90
                    GROUP BY upper(symbol), price_date
               ), ranked AS (
                   SELECT symbol, price_date, close_price,
                          row_number() OVER (
                              PARTITION BY symbol ORDER BY price_date DESC
                          ) AS rn
                     FROM daily
               ), exact20 AS (
                   SELECT symbol,
                          max(close_price) FILTER (WHERE rn = 1) AS last,
                          avg(close_price) FILTER (WHERE rn <= 20) AS dma20,
                          count(*) FILTER (WHERE rn <= 20) AS session_n
                     FROM ranked
                    GROUP BY symbol
               )
               SELECT symbol, last, dma20, session_n
                 FROM exact20
                WHERE session_n = 20
                ORDER BY symbol""",
            (members,),
        )
        rows = cur.fetchall()
        covered_n = len(rows)
        coverage_pct = round(covered_n / membership_n * 100, 1) if membership_n else 0.0
        if covered_n < minimum_members:
            quality = "insufficient_price_coverage"
        elif coverage_pct < float(POLICY["minimum_price_coverage_pct"]):
            quality = "insufficient_membership_coverage"
        else:
            quality = "ok"

        above = sum(
            1 for _symbol, last, dma20, _session_n in rows
            if last is not None and dma20 is not None and float(last) > float(dma20)
        )
        percentage = round(above / covered_n * 100) if quality == "ok" else None
        return percentage, covered_n, membership_n, quality
    except Exception:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        return None, 0, 0, "query_error"


def install() -> None:
    """Install only the v4 breadth implementation into the established engine."""
    base._breadth = breadth_v4


def main() -> int:
    install()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())

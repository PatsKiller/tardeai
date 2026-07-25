#!/usr/bin/env python3
"""Sector momentum v4 launcher with deterministic uncapped covered breadth.

This additive launcher replaces only the breadth producer in
``sector_momentum_engine``. It preserves the established date-aligned RS,
state, debounce, alert and snapshot logic, then attaches the shared specialized
research due-diligence packet to every sector row.

The result is explicitly a covered screener-membership measure, not official
ETF constituent breadth. The launcher remains inactive until an operator
explicitly changes the host invocation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import sector_momentum_engine as base
from defense_data_quality import snapshot_hash
from research_due_diligence_adapters import sector_due_diligence

ROOT = Path(__file__).resolve().parent.parent
POLICY = json.loads((ROOT / "config" / "defense_breadth_policy.json").read_text())
SNAPSHOT = ROOT / "data" / "runtime" / "sector_momentum_latest.json"


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


def attach_due_diligence(snapshot_path: Path = SNAPSHOT) -> dict:
    """Attach immutable sector research packets after the established producer.

    This does not change RS, state, breadth or alerts. It only makes the evidence
    maturity and downstream eligibility explicit for Defense/proposal consumers.
    """
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["policy_version"] = POLICY.get("version") or "defense-breadth-policy-v1"
    states = {"PASS": 0, "REVIEW_REQUIRED": 0, "BLOCKED": 0}
    for row in snapshot.get("rows") or []:
        packet = sector_due_diligence(
            row,
            snapshot,
            benchmark=(base.CFG or {}).get("benchmark", "SPY"),
        )
        row["due_diligence"] = packet
        state = packet.get("deterministic_state") or "BLOCKED"
        states[state] = states.get(state, 0) + 1
    snapshot["due_diligence"] = {
        "contract": "research-due-diligence-v1",
        "adapter": "specialized-research-adapters-v1",
        "domain": "sector",
        "states": states,
        "authority": "deterministic research only; models cannot alter row state or arithmetic",
    }
    snapshot.pop("snapshot_hash", None)
    snapshot["snapshot_hash"] = snapshot_hash(snapshot)
    snapshot_path.write_text(json.dumps(snapshot, default=str))
    return snapshot["due_diligence"]


def install() -> None:
    """Install only the v4 breadth implementation into the established engine."""
    base._breadth = breadth_v4


def main() -> int:
    install()
    result = base.main()
    if result == 0 and "--backfill" not in sys.argv and SNAPSHOT.exists():
        summary = attach_due_diligence()
        print(f"[momentum] due diligence {summary['states']}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())

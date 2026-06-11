#!/usr/bin/env python3
"""compute_source_weights.py — the arbitration layer's compute job.

Builds per-source (per-screener-list) performance from ATTRIBUTED flow:
  candidates (scans) -> GOs -> proposals -> trades -> wins/pnl
and derives a BOUNDED weight (0.9..1.1) that scoring consumes (like the outcome scar — gentle, evidence-
gated). Sources without enough data stay at weight 1.0 (neutral, honest).

Attribution started 2026-06-11 (screener_label), so early windows will be thin: hit_rate falls back to
GO-rate when trade counts are insufficient; weights only move with >=20 candidates AND >=3 GOs.

Cron: daily 18:10 weekdays.   .venv/bin/python scripts/compute_source_weights.py [--apply]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

WINDOW_DAYS = 30
MIN_CANDIDATES = 20
MIN_GOS = 3


def run(apply=False):
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    cur.execute(f"""
        WITH scans AS (
            SELECT COALESCE(screener_label, '(unattributed)') src, symbol,
                   scanned_at::date d, decision
            FROM trade_ai_scans WHERE scanned_at > NOW() - INTERVAL '{WINDOW_DAYS} days'
        ),
        agg AS (
            SELECT src, count(*) candidates, count(*) FILTER (WHERE decision='GO') gos,
                   count(DISTINCT symbol) syms
            FROM scans GROUP BY src
        ),
        props AS (
            SELECT s.src, count(DISTINCT p.id) proposals
            FROM scans s JOIN paper_trade_proposals p
              ON p.symbol = s.symbol AND p.created_at::date = s.d
            GROUP BY s.src
        ),
        trades AS (
            SELECT s.src, count(DISTINCT t.id) trades,
                   count(DISTINCT t.id) FILTER (WHERE t.pnl > 0) wins,
                   COALESCE(sum(t.pnl), 0) pnl
            FROM scans s JOIN paper_trades t
              ON t.symbol = s.symbol AND t.created_at::date = s.d AND t.status = 'closed'
            GROUP BY s.src
        )
        SELECT a.src, a.candidates, a.gos, COALESCE(p.proposals,0), COALESCE(t.trades,0),
               COALESCE(t.wins,0), COALESCE(t.pnl,0)
        FROM agg a LEFT JOIN props p ON p.src=a.src LEFT JOIN trades t ON t.src=a.src
        ORDER BY a.candidates DESC""")
    rows = cur.fetchall()
    out = []
    for src, cand, gos, props, trades, wins, pnl in rows:
        if trades >= 5:
            hit = wins / trades
            weight = 0.9 if hit < 0.35 else 0.95 if hit < 0.45 else 1.1 if hit > 0.65 else 1.05 if hit > 0.55 else 1.0
            basis = "trade_winrate"
        elif cand >= MIN_CANDIDATES and gos >= MIN_GOS:
            hit = gos / cand
            weight = 1.0   # GO-rate informs reporting, not weighting (a list that GOes a lot isn't proven better)
            basis = "go_rate_reporting_only"
        else:
            hit, weight, basis = None, 1.0, "insufficient"
        out.append({"source_key": src, "candidates": cand, "gos": gos, "proposals": props,
                    "trades": trades, "wins": wins, "pnl": float(pnl), "hit_rate": (round(hit, 3) if hit is not None else None),
                    "weight": weight, "basis": basis})
        if apply:
            cur.execute("""INSERT INTO source_weights (source_key, window_days, candidates, gos, proposals,
                              trades, wins, realized_pnl, hit_rate, weight, computed_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                           ON CONFLICT (source_key, window_days) DO UPDATE SET
                              candidates=EXCLUDED.candidates, gos=EXCLUDED.gos, proposals=EXCLUDED.proposals,
                              trades=EXCLUDED.trades, wins=EXCLUDED.wins, realized_pnl=EXCLUDED.realized_pnl,
                              hit_rate=EXCLUDED.hit_rate, weight=EXCLUDED.weight, computed_at=NOW()""",
                        (src, WINDOW_DAYS, cand, gos, props, trades, wins, pnl,
                         out[-1]["hit_rate"], weight))
    if apply:
        conn.commit()
    print(json.dumps({"window_days": WINDOW_DAYS, "sources": out,
                      "applied": apply}, indent=2, default=str))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    run(ap.parse_args().apply)

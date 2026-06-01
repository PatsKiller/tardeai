#!/usr/bin/env python3
"""
Read TradeAI momentum/scalp candidates for Hermes catalyst research.
Outputs symbol list from trade_ai_scans where RVOL >= 5 and price $2-$20.
"""
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Load .env
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v


def get_momentum_candidates(max_tickers=10, min_rvol=5.0, min_score=30):
    """Read current momentum candidates from trade_ai_scans."""
    import psycopg2
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ON (symbol)
            symbol, score, decision, rvol, gap_pct, float_m, price, run_label, run_date
        FROM trade_ai_scans
        WHERE rvol >= %s AND score >= %s
          AND price BETWEEN 1 AND 50
          AND run_date >= CURRENT_DATE - 1
        ORDER BY symbol, rvol DESC
        LIMIT %s
    """, [min_rvol, min_score, max_tickers])
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=10)
    ap.add_argument("--min-rvol", type=float, default=5.0)
    ap.add_argument("--min-score", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    candidates = get_momentum_candidates(args.max, args.min_rvol, args.min_score)
    if args.json:
        print(json.dumps(candidates, default=str, indent=2))
    else:
        print(f"Momentum candidates: {len(candidates)}")
        for c in candidates:
            print(f"  {c['symbol']:8s} score={c['score']} rvol={c['rvol']:.1f} gap={c.get('gap_pct',0):.1f}% ${c['price']:.2f}")

#!/usr/bin/env python3
"""add_winning_strategy_screeners.py — targeted Finviz screens for the LIVE-WINNING strategies that had
NO dedicated candidate source (operator 2026-06-19: feed the winners). Filters mirror each strategy's
committed config criteria so the screen surfaces that exact setup. Idempotent (ON CONFLICT). Does NOT
touch momentum_scalp / day-scalp screeners (operator exclusion). Run with --apply (default dry-run).

  swing_breakout (config: price $5-150, float<500M, RVOL>1.5, breakout from base, above 20/50 SMA):
      near-52w-high + above 20/50 SMA + RVOL expansion + liquid.
  fib_retracement_bounce (config: pullback to fib in a confirmed uptrend, RSI not extended):
      above 50/200 SMA (uptrend) + pulled back below 20 SMA + RSI not overbought + liquid.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn

EXPORT = "https://elite.finviz.com/export?v=152&f={f}&ft=3&c=0,1,2,3,4,5,6,7,25,61,63,64,65,66,67"

SCREENERS = [
    {
        "screener_id": "swing_breakout_targeted",
        "display_name": "Swing Breakout — base breakout (targeted)",
        "strategy_type": "swing_breakout",
        "finviz_url": EXPORT.format(f="sh_price_o5,sh_price_u150,sh_float_u100,sh_relvol_o1.5,"
                                      "sh_avgvol_o500,ta_sma20_pa,ta_sma50_pa,ta_highlow52w_b0to10h"),
        "description": "Near 52w high, above 20/50 SMA, RVOL>1.5, float<100M, $5+ — matches swing_breakout config. Float cap 100M (operator, 2026-09-01): Finviz has no 500M step, and uncapped this screen returned bond ETFs.",
        "schedule": "weekly_mon_1000",
        "keywords": "breakout, 52w high, base, volume expansion",
        "sources": "[\"finviz_elite\"]",
    },
    {
        "screener_id": "fib_retracement_targeted",
        "display_name": "Fib Retracement Bounce — pullback in uptrend (targeted)",
        "strategy_type": "fib_retracement_bounce",
        "finviz_url": EXPORT.format(f="sh_price_o5,sh_avgvol_o500,ta_sma20_pb,ta_sma50_pa,"
                                      "ta_sma200_pa,ta_rsi_nob60"),
        "description": "Uptrend (above 50/200 SMA) pulled back below 20 SMA, RSI not overbought — matches fib_retracement_bounce config (buy weakness in strength).",
        "schedule": "weekly_mon_1000",
        "keywords": "pullback, fibonacci, uptrend, retracement",
        "sources": "[\"finviz_elite\"]",
    },
]


def main():
    apply = "--apply" in sys.argv
    conn = _get_conn(); cur = conn.cursor()
    for s in SCREENERS:
        print(f"  {s['screener_id']} ({s['strategy_type']})\n      {s['finviz_url']}")
        if apply:
            cur.execute("""
                INSERT INTO finviz_screeners
                    (screener_id, display_name, strategy_type, finviz_url, description, schedule,
                     keywords, sources, active, added_by, created_at, updated_at)
                VALUES (%(screener_id)s,%(display_name)s,%(strategy_type)s,%(finviz_url)s,%(description)s,
                        %(schedule)s,%(keywords)s,%(sources)s, TRUE, 'operator_2026-06-19_winner_targeting',
                        now(), now())
                ON CONFLICT (screener_id) DO UPDATE SET
                    finviz_url=EXCLUDED.finviz_url, strategy_type=EXCLUDED.strategy_type,
                    description=EXCLUDED.description, schedule=EXCLUDED.schedule, active=TRUE,
                    updated_at=now()""", s)
    if apply:
        conn.commit()
    print(f"{'APPLIED' if apply else 'DRY-RUN'}: {len(SCREENERS)} targeted screeners "
          f"(swing_breakout, fib_retracement_bounce). momentum_scalp untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""step3_true_winrate.py — TRUE broker-proven win rate, reconciled to the live-gate formula.

READ-ONLY. No order placement, no paper_trades mutation. For every closed trade it runs the
RIGOROUS per-order broker check (get_order_status → confirmed-filled + qty/price match — the
same check that caught #29), NOT the loose DB proxy. It then recomputes the gate's win rate
(wins/closed, where losses include pnl<=0) over only the broker-proven subset.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_adapter import get_connection
from trade_fill_verifier import trade_ai_verify


def main():
    from broker_config import get_account_broker
    get_account_broker("tradeai_automated")           # warm cache before opening our cursor
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, account, shares, entry_price, broker_order_id, pnl
        FROM paper_trades WHERE status='closed' ORDER BY id
    """)
    cols = [d[0] for d in cur.description]
    closed = [dict(zip(cols, r)) for r in cur.fetchall()]

    proven = []
    for t in closed:
        v = trade_ai_verify(t)              # rigorous: get_order_status + qty/price match
        t["_proven"] = bool(v.get("verified"))
        t["_verdict"] = v.get("verdict")
        proven.append(t)

    def winrate(rows):
        # EXACT gate formula: win_rate = wins / closed; losses = pnl<=0
        n = len(rows)
        wins = sum(1 for r in rows if (r["pnl"] or 0) > 0)
        losses = sum(1 for r in rows if (r["pnl"] or 0) <= 0)
        return n, wins, losses, round(100 * wins / max(n, 1), 1)

    n_all, w_all, l_all, pct_all = winrate(closed)
    bp = [r for r in closed if r["_proven"]]
    n_bp, w_bp, l_bp, pct_bp = winrate(bp)

    print("="*72)
    print("TRUE broker-proven win rate (rigorous confirm_fill, gate formula wins/closed)")
    print("="*72)
    print(f"GATE CURRENT (all closed)     : {pct_all}%   closed={n_all}  wins={w_all}  losses={l_all}")
    print(f"  (losses include {sum(1 for r in closed if (r['pnl'] or 0)==0)} pnl=0 voided phantoms counted as losses)")
    print(f"BROKER-PROVEN (rigorous)      : {pct_bp}%   closed={n_bp}  wins={w_bp}  losses={l_bp}")
    print(f"  excluded {n_all-n_bp} unproven closed rows (no order id / unconfirmed at broker / mismatch)")
    print()
    print("Excluded rows (not broker-proven) — why:")
    for r in closed:
        if not r["_proven"]:
            why = "no_order_id" if not r["broker_order_id"] else r["_verdict"]
            print(f"  #{r['id']:<3} {r['symbol']:<6} pnl={float(r['pnl'] or 0):>8.2f}  {why}")
    print()
    print(f"Δ win rate: {pct_all}% (gate today) -> {pct_bp}% (broker-proven). "
          f"This is the number the gate's counting logic would read AFTER STEP 3(b).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

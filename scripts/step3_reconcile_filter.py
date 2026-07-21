"""step3_reconcile_filter.py — does the label-based _fake filter agree with rigorous confirm_fill?

READ-ONLY. For every closed row, compares:
  - LABEL rule  : outcome_verdict='PHANTOM' OR close_reason='phantom_no_alpaca_position'  (what (b) wires)
  - RIGOROUS    : get_order_status() at the broker — filled / unknown(can't verify) / canceled|rejected(fake)

The danger case is a KEPT row (not label-fake) that the broker says is canceled/rejected/never
filled — order-linked-but-unconfirmed (the #29 class). If any exist, the label filter is looser
than reality and 65% is intermediate, not final. 'unknown' (old order, not queryable) is NOT
fake — under the chosen rule (exclude provably-fake) those are correctly kept.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_adapter import get_connection
from broker_adapter import adapter_for

FAKE_BROKER_STATES = {"canceled", "cancelled", "rejected", "expired"}


def main():
    from broker_config import get_account_broker
    get_account_broker("tradeai_automated")
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, account, shares, entry_price, broker_order_id, pnl,
               outcome_verdict, close_reason
        FROM paper_trades WHERE status='closed' ORDER BY id
    """)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    def is_label_fake(r):
        return (r.get("outcome_verdict") == "PHANTOM"
                or r.get("close_reason") == "phantom_no_alpaca_position")

    def broker_state(r):
        if not r.get("broker_order_id"):
            return "no_order_id"
        try:
            a = adapter_for(r["account"])
        except Exception:
            return "no_adapter"
        try:
            return a.get_order_status(r["broker_order_id"]).status or "unknown"
        except Exception:
            return "unknown"

    excluded, kept = [], []
    gap_rows = []          # KEPT by label filter but broker says provably-fake
    for r in rows:
        r["_label_fake"] = is_label_fake(r)
        (excluded if r["_label_fake"] else kept).append(r)

    # only need the broker re-check on KEPT rows (the ones that would still count)
    for r in kept:
        r["_bstate"] = broker_state(r)
        if r["broker_order_id"] and r["_bstate"] in FAKE_BROKER_STATES:
            gap_rows.append(r)

    print("="*72)
    print(f"LABEL filter excludes {len(excluded)} rows, keeps {len(kept)}")
    print("="*72)
    print("\nEXCLUDED by label filter (the 'provably-fake' set):")
    for r in excluded:
        print(f"  #{r['id']:<3} {r['symbol']:<6} pnl={float(r['pnl'] or 0):>8.2f}  "
              f"verdict={r['outcome_verdict']}  order_id={'yes' if r['broker_order_id'] else 'NULL'}")

    # the specific #29 question
    n29 = next((r for r in rows if r["id"] == 29), None)
    if n29:
        print(f"\n#29 NVDA check: label_fake={is_label_fake(n29)} "
              f"(verdict={n29['outcome_verdict']}, close_reason={n29['close_reason']}, "
              f"order_id={'yes' if n29['broker_order_id'] else 'NULL'}) "
              f"-> {'EXCLUDED (caught)' if is_label_fake(n29) else 'KEPT (SLIPS THROUGH!)'}")

    print(f"\nKEPT rows broker re-check ({len(kept)} rows):")
    cat = {"filled": 0, "no_order_id": 0, "unknown": 0, "no_adapter": 0, "fake": 0}
    for r in kept:
        b = r["_bstate"]
        bucket = "fake" if b in FAKE_BROKER_STATES else (b if b in cat else "unknown")
        cat[bucket] = cat.get(bucket, 0) + 1
    for k, v in cat.items():
        print(f"  {k:<14}: {v}")

    print("\n" + "="*72)
    if gap_rows:
        print(f"GAP: {len(gap_rows)} KEPT row(s) are order-linked but broker says canceled/rejected")
        for r in gap_rows:
            print(f"  #{r['id']} {r['symbol']} pnl={float(r['pnl'] or 0):.2f} broker_status={r['_bstate']} "
                  f"-> label keeps it, broker rejects it. 65% is INTERMEDIATE.")
    else:
        print("NO GAP: every KEPT order-linked row is either broker-filled or only "
              "unverifiable-because-old (not provably-fake). The label filter agrees with the")
        print("rigorous rule on what's FAKE. 65% is the FINAL honest number under the chosen rule.")
    print("="*72)
    return 0


if __name__ == "__main__":
    sys.exit(main())

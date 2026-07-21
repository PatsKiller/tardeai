#!/usr/bin/env python3
"""INTELLIGENCE-FLOW-2 — Canonical closed trade adapter.

Produces account-agnostic closed trade records for backtesting from
paper_trades (Alpaca) and trade_closed (Schwab/Fidelity/future).
Does NOT create orders or trades.
"""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Account capability policy
BACKTEST_ENABLED = {
    "tradeai_automated", "ALPACA_PAPER", "TOS_PAPER",
    "schwab_rollover_ira", "schwab_roth_ira", "schwab_roth", "schwab_taxable",
}
EXECUTION_ENABLED = {"tradeai_automated"}  # only paper execution


def _get_conn():
    from db_adapter import get_connection
    return get_connection()


def can_backtest(account_label):
    return (account_label or "").lower().replace("_", "_") in {a.lower() for a in BACKTEST_ENABLED}


def can_execute(account_label):
    return (account_label or "").lower() in {a.lower() for a in EXECUTION_ENABLED}


def extract_canonical(account_label=None, broker=None, verbose=False):
    conn = _get_conn()
    if not conn:
        return []

    cur = conn.cursor()

    # Paper trades (Alpaca + TOS)
    cur.execute("""
        SELECT id as source_trade_id, 'paper_trades' as source_table,
               account as account_label,
               COALESCE(broker, 'alpaca') as broker,
               symbol, strategy_id,
               filled_at as entry_time, closed_at as exit_time,
               entry_price, exit_price, shares as quantity,
               pnl as realized_pnl, r_multiple as realized_r,
               planned_stop, target_1 as planned_target,
               proposal_id
        FROM paper_trades
        WHERE status = 'closed'
    """)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Trade_closed table (Schwab/Fidelity imports)
    try:
        cur.execute("""
            SELECT id as source_trade_id, 'trade_closed' as source_table,
                   account as account_label,
                   CASE WHEN account ILIKE '%schwab%' THEN 'schwab'
                        WHEN account ILIKE '%fidelity%' THEN 'fidelity'
                        ELSE 'unknown' END as broker,
                   symbol, NULL as strategy_id,
                   open_date::timestamptz as entry_time, close_date::timestamptz as exit_time,
                   buy_price as entry_price, sell_price as exit_price, shares as quantity,
                   pnl as realized_pnl, r_multiple as realized_r,
                   stop_used as planned_stop, NULL::numeric as planned_target,
                   NULL::int as proposal_id
            FROM trade_closed
        """)
        cols2 = [d[0] for d in cur.description]
        rows += [dict(zip(cols2, r)) for r in cur.fetchall()]
    except Exception:
        pass  # table may not exist yet

    # Filter by account/broker if specified
    if account_label:
        rows = [r for r in rows if (r.get("account_label") or "").upper() == account_label.upper()]
    if broker:
        rows = [r for r in rows if (r.get("broker") or "").lower() == broker.lower()]

    # Filter to backtest-enabled accounts only
    result = []
    for r in rows:
        acct = r.get("account_label", "")
        r["backtest_eligible"] = can_backtest(acct)
        r["execution_eligible"] = can_execute(acct)
        r["source_system"] = "trade_ai_v12"
        if r["backtest_eligible"]:
            result.append(r)
        elif verbose:
            print(f"  SKIP {r['symbol']} account={acct} — not backtest-eligible")

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-label", type=str)
    ap.add_argument("--broker", type=str)
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--output-json", type=str)
    ap.add_argument("--output-md", type=str)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    rows = extract_canonical(args.account_label, args.broker, args.verbose)

    by_account = {}
    for r in rows:
        a = r.get("account_label", "?")
        by_account.setdefault(a, []).append(r)

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump({"total": len(rows), "by_account": {k: len(v) for k, v in by_account.items()}, "trades": rows}, f, indent=2, default=str)

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_md, "w") as f:
            f.write(f"# Canonical Closed Trades\n\nTotal: {len(rows)}\n\n")
            f.write("| Account | Broker | Count |\n|---|---|---|\n")
            for a, trades in by_account.items():
                b = trades[0].get("broker", "?") if trades else "?"
                f.write(f"| {a} | {b} | {len(trades)} |\n")
            f.write(f"\n## Detail\n\n")
            for r in rows:
                f.write(f"- #{r['source_trade_id']} {r['symbol']} ({r['account_label']}/{r['broker']}) "
                        f"PnL=${r.get('realized_pnl') or 0} backtest={r['backtest_eligible']}\n")

    print(f"\nCanonical closed trades: {len(rows)} | Accounts: {list(by_account.keys())}")


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()

#!/usr/bin/env python3
"""INTELLIGENCE-FLOW-1 — Dataflow health report."""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _q(sql):
    from db_adapter import get_connection
    conn = get_connection()
    if not conn: return []
    cur = conn.cursor()
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def report(verbose=False):
    r = {"generated_at": datetime.now(timezone.utc).isoformat()}

    # Accounts
    accts = _q("SELECT account_label, broker, mode, enabled FROM accounts ORDER BY id")
    r["accounts"] = accts
    r["account_count"] = len(accts)

    # Trades by account
    trades = _q("""
        SELECT account, COUNT(*) as total,
               COUNT(*) FILTER (WHERE status='open') as open,
               COUNT(*) FILTER (WHERE status='closed') as closed
        FROM paper_trades GROUP BY account ORDER BY total DESC
    """)
    r["trades_by_account"] = trades

    # Proposals by strategy
    proposals = _q("""
        SELECT strategy_id, COUNT(*) as total,
               COUNT(*) FILTER (WHERE status IN ('APPROVED','APPROVED_FOR_PAPER_TEST')) as approved
        FROM paper_trade_proposals WHERE created_at > NOW()-INTERVAL '30 days'
        GROUP BY strategy_id ORDER BY total DESC
    """)
    r["proposals_by_strategy"] = proposals

    # Enrichment coverage
    r["enrichment"] = {
        "screener_symbols": _q("SELECT COUNT(DISTINCT symbol) as n FROM screener_symbol_membership")[0]["n"],
        "classified_symbols": _q("SELECT COUNT(DISTINCT symbol) as n FROM ticker_strategy_classifications")[0]["n"],
        "content_embeddings": _q("SELECT COUNT(*) as n FROM content_embeddings")[0]["n"],
        "quote_snapshots": _q("SELECT COUNT(DISTINCT symbol) as n FROM market_quote_snapshots")[0]["n"],
        "news_articles": _q("SELECT COUNT(*) as n FROM news_articles")[0]["n"],
    }

    # RAG source types
    r["rag_sources"] = _q("SELECT source_type, COUNT(*) as n FROM content_embeddings GROUP BY 1 ORDER BY 2 DESC LIMIT 15")

    # Backtest coverage
    bt = _q("SELECT COUNT(*) as runs FROM strategy_backtest_runs")
    r["backtest_runs"] = bt[0]["runs"] if bt else 0
    bt_trades = _q("SELECT COUNT(*) as n FROM strategy_backtest_trades")
    r["backtest_trades"] = bt_trades[0]["n"] if bt_trades else 0

    # Agent events
    ae = _q("SELECT COUNT(*) as n FROM agent_curation_events WHERE created_at > NOW()-INTERVAL '30 days'")
    r["agent_events_30d"] = ae[0]["n"] if ae else 0

    # Closed trades missing backtests (no direct FK — check by symbol+strategy)
    r["closed_missing_backtest"] = _q("""
        SELECT pt.id, pt.symbol, pt.strategy_id, pt.account
        FROM paper_trades pt
        WHERE pt.status='closed'
          AND NOT EXISTS (
            SELECT 1 FROM strategy_backtest_trades sbt
            WHERE sbt.symbol = pt.symbol AND sbt.strategy_id = pt.strategy_id
          )
    """)

    # Hardcoding warnings
    r["hardcoding_warnings"] = [
        "atm_auto_approver.py:255 defaults to 'tradeai_automated' if target_account NULL",
        "paper_trade_proposals.proposed_account defaults to 'TOS_PAPER' in schema",
    ]

    # Summary
    total_closed = sum(t.get("closed", 0) for t in trades)
    r["summary"] = {
        "total_accounts": len(accts),
        "enabled_accounts": sum(1 for a in accts if a.get("enabled")),
        "total_trades": sum(t.get("total", 0) for t in trades),
        "total_closed": total_closed,
        "total_open": sum(t.get("open", 0) for t in trades),
        "enrichment_symbols": r["enrichment"]["screener_symbols"],
        "rag_documents": r["enrichment"]["content_embeddings"],
        "backtest_runs": r["backtest_runs"],
        "closed_missing_backtest": len(r["closed_missing_backtest"]),
        "hardcoding_warnings": len(r["hardcoding_warnings"]),
    }

    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-md", type=str)
    ap.add_argument("--output-json", type=str)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    r = report(verbose=args.verbose)

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump(r, f, indent=2, default=str)

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        s = r["summary"]
        with open(args.output_md, "w") as f:
            f.write(f"# Intelligence Flow Health Report\n\n")
            f.write(f"Generated: {r['generated_at']}\n\n")
            f.write(f"## Summary\n")
            f.write(f"- Accounts: {s['total_accounts']} ({s['enabled_accounts']} enabled)\n")
            f.write(f"- Trades: {s['total_trades']} ({s['total_open']} open, {s['total_closed']} closed)\n")
            f.write(f"- Enrichment symbols: {s['enrichment_symbols']}\n")
            f.write(f"- RAG documents: {s['rag_documents']}\n")
            f.write(f"- Backtest runs: {s['backtest_runs']}\n")
            f.write(f"- Closed trades missing backtest: {s['closed_missing_backtest']}\n")
            f.write(f"- Hardcoding warnings: {s['hardcoding_warnings']}\n\n")
            f.write(f"## Accounts\n\n| Label | Broker | Mode | Enabled |\n|---|---|---|---|\n")
            for a in r["accounts"]:
                f.write(f"| {a['account_label']} | {a['broker']} | {a['mode']} | {a['enabled']} |\n")
            f.write(f"\n## Trades by Account\n\n| Account | Total | Open | Closed |\n|---|---|---|---|\n")
            for t in r["trades_by_account"]:
                f.write(f"| {t['account']} | {t['total']} | {t['open']} | {t['closed']} |\n")
            if r["closed_missing_backtest"]:
                f.write(f"\n## Closed Trades Missing Backtest\n\n")
                for t in r["closed_missing_backtest"]:
                    f.write(f"- #{t['id']} {t['symbol']} ({t['strategy_id']}) account={t['account']}\n")
            f.write(f"\n## Hardcoding Warnings\n\n")
            for w in r["hardcoding_warnings"]:
                f.write(f"- {w}\n")

    s = r["summary"]
    print(f"\nAccounts: {s['total_accounts']} | Trades: {s['total_trades']} | "
          f"RAG: {s['rag_documents']} | Backtests: {s['backtest_runs']} | "
          f"Warnings: {s['hardcoding_warnings']}")


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()

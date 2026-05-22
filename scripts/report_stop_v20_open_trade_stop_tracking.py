#!/usr/bin/env python3
"""Report open paper trade stop tracking state for STOP-V2.0."""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    from db_adapter import get_connection
    return get_connection()


def _get_broker_stops():
    """Fetch open stop orders from Alpaca paper."""
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass
    from alpaca_paper_adapter import AlpacaPaperAdapter
    a = AlpacaPaperAdapter()
    import requests
    resp = requests.get(f'{a.base_url}/v2/orders?status=open&limit=100', headers=a.headers, timeout=10)
    if resp.status_code != 200:
        return []
    return [o for o in resp.json() if o.get("type") == "stop"]


def report(verbose=False):
    conn = _get_conn()
    if not conn:
        return {"error": "no_db"}

    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, strategy_id, shares, entry_price, stop_loss,
               planned_stop, target_1, stop_order_id, bracket_order, order_type,
               broker_order_id, target_account
        FROM paper_trades WHERE status='open' ORDER BY id
    """)
    cols = [d[0] for d in cur.description]
    trades = [dict(zip(cols, r)) for r in cur.fetchall()]

    broker_stops = _get_broker_stops()
    broker_by_symbol = {}
    for o in broker_stops:
        sym = o["symbol"]
        broker_by_symbol.setdefault(sym, []).append(o)

    results = []
    for t in trades:
        sym = t["symbol"]
        tid = t["id"]
        bs_list = broker_by_symbol.get(sym, [])

        # Find matching broker stop
        broker_match = None
        match_count = 0
        for bs in bs_list:
            bq = int(bs.get("qty", 0))
            if bq == t["shares"]:
                broker_match = bs
                match_count += 1

        rec = {
            "trade_id": tid,
            "symbol": sym,
            "strategy_id": t["strategy_id"],
            "account_label": t.get("target_account", ""),
            "qty": t["shares"],
            "entry_price": float(t["entry_price"]) if t["entry_price"] else None,
            "stop_loss": float(t["stop_loss"]) if t["stop_loss"] else None,
            "planned_stop": float(t["planned_stop"]) if t["planned_stop"] else None,
            "stop_order_id": t["stop_order_id"],
            "planned_stop_missing": t["planned_stop"] is None,
            "stop_order_id_missing": t["stop_order_id"] is None,
        }

        if match_count == 1 and broker_match:
            rec["broker_stop_order_id"] = broker_match["id"]
            rec["broker_stop_price"] = float(broker_match.get("stop_price", 0))
            rec["broker_stop_qty"] = int(broker_match.get("qty", 0))
            rec["broker_stop_status"] = broker_match.get("status", "?")
            rec["broker_time_in_force"] = broker_match.get("time_in_force", "?")
            rec["stop_matches_db"] = abs(rec["broker_stop_price"] - (rec["stop_loss"] or 0)) < 0.02
        elif match_count > 1:
            rec["broker_stop_order_id"] = "MULTIPLE"
            rec["broker_stop_price"] = None
            rec["broker_stop_qty"] = None
            rec["broker_stop_status"] = "MULTIPLE"
            rec["stop_matches_db"] = False
        else:
            rec["broker_stop_order_id"] = None
            rec["broker_stop_price"] = None
            rec["broker_stop_qty"] = None
            rec["broker_stop_status"] = "NOT_FOUND"
            rec["stop_matches_db"] = False

        # Reconciliation status
        if rec["broker_stop_status"] == "NOT_FOUND":
            rec["reconciliation_status"] = "BROKER_STOP_NOT_FOUND"
        elif rec["broker_stop_status"] == "MULTIPLE":
            rec["reconciliation_status"] = "REVIEW_REQUIRED"
        elif not rec["stop_matches_db"]:
            rec["reconciliation_status"] = "PRICE_MISMATCH"
        elif rec["planned_stop_missing"] and rec["stop_order_id_missing"]:
            rec["reconciliation_status"] = "MISSING_PLANNED_STOP"
        elif rec["stop_order_id_missing"]:
            rec["reconciliation_status"] = "MISSING_STOP_ORDER_ID"
        elif rec["planned_stop_missing"]:
            rec["reconciliation_status"] = "MISSING_PLANNED_STOP"
        else:
            rec["reconciliation_status"] = "TRACKED"

        results.append(rec)
        if verbose:
            print(f"  #{tid} {sym}: {rec['reconciliation_status']} "
                  f"planned={rec['planned_stop']} broker_stop={rec.get('broker_stop_price')} "
                  f"db_stop={rec['stop_loss']} match={rec['stop_matches_db']}")

    summary = {
        "total": len(results),
        "tracked": sum(1 for r in results if r["reconciliation_status"] == "TRACKED"),
        "missing_planned_stop": sum(1 for r in results if r["planned_stop_missing"]),
        "missing_stop_order_id": sum(1 for r in results if r["stop_order_id_missing"]),
        "broker_stop_not_found": sum(1 for r in results if r["reconciliation_status"] == "BROKER_STOP_NOT_FOUND"),
        "review_required": sum(1 for r in results if r["reconciliation_status"] == "REVIEW_REQUIRED"),
        "price_mismatch": sum(1 for r in results if r["reconciliation_status"] == "PRICE_MISMATCH"),
    }

    return {"generated_at": datetime.now(timezone.utc).isoformat(), "summary": summary, "trades": results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-json", type=str)
    ap.add_argument("--output-md", type=str)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    result = report(verbose=args.verbose)

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"JSON: {args.output_json}")

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        s = result.get("summary", {})
        lines = [
            f"# Stop V2.0 — Open Trade Stop Tracking\n",
            f"Generated: {result.get('generated_at')}\n",
            f"## Summary\n",
            f"- Total open: {s.get('total')}\n",
            f"- Tracked: {s.get('tracked')}\n",
            f"- Missing planned_stop: {s.get('missing_planned_stop')}\n",
            f"- Missing stop_order_id: {s.get('missing_stop_order_id')}\n",
            f"- Broker stop not found: {s.get('broker_stop_not_found')}\n",
            f"- Review required: {s.get('review_required')}\n\n",
            f"## Per-Trade Detail\n\n",
            f"| ID | Symbol | Stop | Planned | Broker Stop | Match | Status |\n",
            f"|---|---|---|---|---|---|---|\n",
        ]
        for t in result.get("trades", []):
            lines.append(f"| #{t['trade_id']} | {t['symbol']} | {t['stop_loss']} | "
                         f"{t['planned_stop'] or 'NULL'} | {t.get('broker_stop_price') or '—'} | "
                         f"{'Y' if t.get('stop_matches_db') else 'N'} | {t['reconciliation_status']} |\n")
        with open(args.output_md, "w") as f:
            f.writelines(lines)
        print(f"MD: {args.output_md}")

    print(f"\nSummary: {json.dumps(result.get('summary', {}))}")


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()

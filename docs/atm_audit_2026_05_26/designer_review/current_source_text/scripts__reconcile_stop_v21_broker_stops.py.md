# Source Export: scripts/reconcile_stop_v21_broker_stops.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/reconcile_stop_v21_broker_stops.py` |
| **Git Branch** | `main` |
| **Git Commit** | `c1286d314deb377df49713e1646f139db7f43643` |
| **Export Timestamp** | `2026-05-26T15:48:59Z` |
| **SHA256** | `b1079a6e692816c09f23dafae67c8dcc3f1c9202e08ad4aea57c269193d3a8c3` |
| **File Size** | 12246 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""STOP-V2.1 — Broker stop reconciliation engine.

Reads open paper trades and broker stop orders. Reports mismatches.
Does NOT create, cancel, move, or replace any broker orders.
"""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

AUDIT_FALLBACK = PROJECT_ROOT / "docs" / "risk_management" / "stop_management_v2_1_reconciliation_engine" / "audit_fallback"

SEVERITIES = {
    "RECONCILED": "INFO",
    "MISSING_BROKER_STOP": "CRITICAL",
    "MISSING_DB_STOP": "WARN",
    "STOP_PRICE_MISMATCH": "CRITICAL",
    "STOP_QTY_MISMATCH": "CRITICAL",
    "STOP_ORDER_ID_STALE": "CRITICAL",
    "BROKER_STOP_CANCELED": "CRITICAL",
    "BROKER_STOP_REJECTED": "CRITICAL",
    "ORPHANED_BROKER_STOP": "WARN",
    "MULTIPLE_BROKER_STOPS": "WARN",
    "ACCOUNT_MISMATCH": "WARN",
    "RECONCILIATION_ERROR": "CRITICAL",
    "REVIEW_REQUIRED": "WARN",
}


def _safety_checks():
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass
    assert os.environ.get("ALPACA_MODE") == "paper", "ALPACA_MODE must be paper"
    assert os.environ.get("LLM_DISABLE_LIVE_EXECUTION") == "true", "LLM_DISABLE must be true"


def _get_conn():
    from db_adapter import get_connection
    return get_connection()


def _get_broker_orders():
    from alpaca_paper_adapter import AlpacaPaperAdapter
    a = AlpacaPaperAdapter()
    import requests
    # Get all open orders (stops)
    resp = requests.get(f'{a.base_url}/v2/orders?status=open&limit=500', headers=a.headers, timeout=10)
    open_orders = resp.json() if resp.status_code == 200 else []
    # Also check closed/canceled orders for stale stop_order_id detection
    resp2 = requests.get(f'{a.base_url}/v2/orders?status=closed&limit=100&after=2026-05-20T00:00:00Z',
                         headers=a.headers, timeout=10)
    closed_orders = resp2.json() if resp2.status_code == 200 else []
    resp3 = requests.get(f'{a.base_url}/v2/orders?status=canceled&limit=100&after=2026-05-20T00:00:00Z',
                         headers=a.headers, timeout=10)
    canceled_orders = resp3.json() if resp3.status_code == 200 else []
    return open_orders, closed_orders, canceled_orders


def _write_audit(conn, event_type, details):
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO audit_log (event_type, input_snapshot, actor) VALUES (%s, %s, 'stop_v21_recon')",
                    [event_type, json.dumps(details, default=str)])
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        AUDIT_FALLBACK.mkdir(parents=True, exist_ok=True)
        fb = AUDIT_FALLBACK / f"recon_{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
        with open(fb, "w") as f:
            json.dump({"event": event_type, "details": details}, f, default=str)


def reconcile(verbose=False):
    _safety_checks()
    conn = _get_conn()
    if not conn:
        return {"error": "no_db"}

    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, strategy_id, shares, entry_price, stop_loss, planned_stop,
               stop_order_id, stop_updated_at, target_account, bracket_order
        FROM paper_trades WHERE status='open' ORDER BY id
    """)
    cols = [d[0] for d in cur.description]
    trades = [dict(zip(cols, r)) for r in cur.fetchall()]

    open_orders, closed_orders, canceled_orders = _get_broker_orders()

    # Index broker orders
    open_stops = [o for o in open_orders if o.get("type") == "stop"]
    open_by_id = {o["id"]: o for o in open_stops}
    open_by_symbol = {}
    for o in open_stops:
        open_by_symbol.setdefault(o["symbol"], []).append(o)

    closed_by_id = {o["id"]: o for o in closed_orders}
    canceled_by_id = {o["id"]: o for o in canceled_orders}
    all_by_id = {**open_by_id, **closed_by_id, **canceled_by_id}

    # Track which broker stops are matched
    matched_broker_ids = set()
    findings = []

    for t in trades:
        tid = t["id"]
        sym = t["symbol"]
        db_stop = float(t["stop_loss"]) if t["stop_loss"] else None
        soid = t["stop_order_id"]
        shares = t["shares"]

        finding = {
            "trade_id": tid, "symbol": sym, "strategy_id": t["strategy_id"],
            "db_stop_loss": db_stop, "planned_stop": float(t["planned_stop"]) if t["planned_stop"] else None,
            "stop_order_id": soid, "shares": shares,
        }

        # 1. Try exact stop_order_id match
        if soid:
            if soid in open_by_id:
                bo = open_by_id[soid]
                matched_broker_ids.add(soid)
                bp = float(bo.get("stop_price", 0))
                bq = int(bo.get("qty", 0))
                finding["broker_stop_price"] = bp
                finding["broker_stop_qty"] = bq
                finding["broker_stop_status"] = bo.get("status")
                finding["broker_tif"] = bo.get("time_in_force")

                if bq != shares:
                    finding["status"] = "STOP_QTY_MISMATCH"
                    finding["detail"] = f"DB shares={shares} broker qty={bq}"
                elif db_stop and abs(bp - db_stop) > 0.02:
                    finding["status"] = "STOP_PRICE_MISMATCH"
                    finding["detail"] = f"DB stop={db_stop} broker={bp}"
                else:
                    finding["status"] = "RECONCILED"
                    finding["detail"] = f"stop=${bp} qty={bq} tif={bo.get('time_in_force')}"

            elif soid in canceled_by_id:
                finding["status"] = "BROKER_STOP_CANCELED"
                finding["broker_stop_status"] = canceled_by_id[soid].get("status")
                finding["detail"] = f"stop_order_id {soid[:12]} was canceled at broker"

            elif soid in closed_by_id:
                finding["status"] = "STOP_ORDER_ID_STALE"
                finding["broker_stop_status"] = closed_by_id[soid].get("status")
                finding["detail"] = f"stop_order_id {soid[:12]} is closed/filled at broker"

            else:
                finding["status"] = "STOP_ORDER_ID_STALE"
                finding["detail"] = f"stop_order_id {soid[:12]} not found at broker"
        else:
            finding["status"] = "MISSING_DB_STOP"
            finding["detail"] = "No stop_order_id tracked in DB"

        # If not reconciled via ID, try symbol match
        if finding["status"] not in ("RECONCILED",):
            sym_stops = open_by_symbol.get(sym, [])
            if len(sym_stops) == 1:
                bo = sym_stops[0]
                bp = float(bo.get("stop_price", 0))
                bq = int(bo.get("qty", 0))
                finding["fallback_broker_stop_price"] = bp
                finding["fallback_broker_stop_qty"] = bq
                finding["fallback_broker_order_id"] = bo["id"]
                if finding["status"] in ("STOP_ORDER_ID_STALE", "MISSING_DB_STOP"):
                    finding["detail"] += f" (fallback match found: ${bp}, qty={bq})"
            elif len(sym_stops) > 1:
                finding["detail"] += f" (MULTIPLE broker stops for {sym}: {len(sym_stops)})"
            elif len(sym_stops) == 0 and finding["status"] != "RECONCILED":
                finding["status"] = "MISSING_BROKER_STOP"
                finding["detail"] = f"No broker stop order found for {sym}"

        finding["severity"] = SEVERITIES.get(finding["status"], "WARN")
        findings.append(finding)

        if verbose:
            sev = finding["severity"]
            print(f"  [{sev}] #{tid} {sym}: {finding['status']} — {finding.get('detail','')}")

    # Detect orphaned broker stops
    for o in open_stops:
        if o["id"] not in matched_broker_ids:
            sym = o["symbol"]
            # Check if there's a DB trade for this symbol
            has_db = any(t["symbol"] == sym for t in trades)
            if not has_db:
                findings.append({
                    "trade_id": None, "symbol": sym,
                    "status": "ORPHANED_BROKER_STOP",
                    "severity": "WARN",
                    "broker_order_id": o["id"],
                    "broker_stop_price": float(o.get("stop_price", 0)),
                    "broker_stop_qty": int(o.get("qty", 0)),
                    "detail": f"Broker stop {o['id'][:12]} for {sym} has no matching open DB trade",
                })
                if verbose:
                    print(f"  [WARN] ORPHAN {sym}: broker stop {o['id'][:12]} no DB trade")

    summary = {
        "total_trades": len(trades),
        "total_broker_stops": len(open_stops),
        "reconciled": sum(1 for f in findings if f["status"] == "RECONCILED"),
        "critical": sum(1 for f in findings if f.get("severity") == "CRITICAL"),
        "warning": sum(1 for f in findings if f.get("severity") == "WARN"),
        "info": sum(1 for f in findings if f.get("severity") == "INFO"),
        "missing_broker_stop": sum(1 for f in findings if f["status"] == "MISSING_BROKER_STOP"),
        "price_mismatch": sum(1 for f in findings if f["status"] == "STOP_PRICE_MISMATCH"),
        "qty_mismatch": sum(1 for f in findings if f["status"] == "STOP_QTY_MISMATCH"),
        "stale_order_id": sum(1 for f in findings if f["status"] == "STOP_ORDER_ID_STALE"),
        "canceled": sum(1 for f in findings if f["status"] == "BROKER_STOP_CANCELED"),
        "orphaned": sum(1 for f in findings if f["status"] == "ORPHANED_BROKER_STOP"),
        "all_protected": sum(1 for f in findings if f["status"] == "RECONCILED") == len(trades),
    }

    return {"generated_at": datetime.now(timezone.utc).isoformat(), "summary": summary, "findings": findings}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--output-json", type=str)
    ap.add_argument("--output-md", type=str)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    result = reconcile(verbose=args.verbose)

    # Write audit log if apply
    if args.apply:
        conn = _get_conn()
        if conn:
            _write_audit(conn, "stop_v21_reconciliation_run", result.get("summary", {}))

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump(result, f, indent=2, default=str)

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        s = result.get("summary", {})
        lines = [
            f"# STOP-V2.1 Reconciliation Report\n\n",
            f"Generated: {result.get('generated_at')}\n\n",
            f"## Summary\n",
            f"- Trades: {s.get('total_trades')} | Broker stops: {s.get('total_broker_stops')}\n",
            f"- Reconciled: {s.get('reconciled')} | Critical: {s.get('critical')} | Warning: {s.get('warning')}\n",
            f"- Missing broker: {s.get('missing_broker_stop')} | Price mismatch: {s.get('price_mismatch')}\n",
            f"- Qty mismatch: {s.get('qty_mismatch')} | Stale ID: {s.get('stale_order_id')}\n",
            f"- Canceled: {s.get('canceled')} | Orphaned: {s.get('orphaned')}\n",
            f"- **All protected: {'YES' if s.get('all_protected') else 'NO'}**\n\n",
            f"## Findings\n\n",
            f"| ID | Symbol | Status | Severity | Detail |\n",
            f"|---|---|---|---|---|\n",
        ]
        for f_ in result.get("findings", []):
            tid = f"#{f_['trade_id']}" if f_.get('trade_id') else "—"
            lines.append(f"| {tid} | {f_.get('symbol','')} | {f_['status']} | {f_.get('severity','')} | {f_.get('detail','')} |\n")
        with open(args.output_md, "w") as f:
            f.writelines(lines)

    s = result.get("summary", {})
    print(f"\nReconciled: {s.get('reconciled')}/{s.get('total_trades')} | "
          f"Critical: {s.get('critical')} | Warning: {s.get('warning')} | "
          f"All protected: {'YES' if s.get('all_protected') else 'NO'}")


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
```

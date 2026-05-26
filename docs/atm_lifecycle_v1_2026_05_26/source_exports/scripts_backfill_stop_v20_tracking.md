# Source Export: scripts/backfill_stop_v20_tracking.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/backfill_stop_v20_tracking.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `70f9850dd4ab619b738b7b55c5b3c71fcdd3eefbdb8eeb0303359904fed53631` |
| **File Size** | 8619 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""Backfill planned_stop and stop_order_id for STOP-V2.0.

SAFETY: Does NOT create, cancel, or move stop orders.
Only updates DB tracking fields where the source is deterministic.
"""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

AUDIT_FALLBACK_DIR = PROJECT_ROOT / "docs" / "risk_management" / "stop_management_v2_0_backfill_tracking" / "audit_fallback"


def _get_conn():
    from db_adapter import get_connection
    return get_connection()


def _safety_checks():
    """Assert paper mode and ATM frozen."""
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass
    mode = os.environ.get("ALPACA_MODE", "")
    assert mode == "paper", f"ALPACA_MODE must be paper, got {mode}"
    disable = os.environ.get("LLM_DISABLE_LIVE_EXECUTION", "")
    assert disable == "true", f"LLM_DISABLE_LIVE_EXECUTION must be true, got {disable}"


def _get_broker_stops():
    from alpaca_paper_adapter import AlpacaPaperAdapter
    a = AlpacaPaperAdapter()
    import requests
    resp = requests.get(f'{a.base_url}/v2/orders?status=open&limit=100', headers=a.headers, timeout=10)
    if resp.status_code != 200:
        return []
    return [o for o in resp.json() if o.get("type") == "stop"]


def _write_audit(conn, trade_id, field, old_val, new_val):
    """Write audit event for backfill."""
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO audit_log (event_type, symbol, input_snapshot, actor, reason_text)
            VALUES ('stop_v20_backfill', (SELECT symbol FROM paper_trades WHERE id=%s), %s,
                    'stop_v20_backfill', %s)
        """, [trade_id,
              json.dumps({"trade_id": trade_id, "field": field, "old": str(old_val), "new": str(new_val)}),
              f"Backfill {field}: {old_val} -> {new_val}"])
        conn.commit()
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        # Fallback file
        AUDIT_FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
        fb = AUDIT_FALLBACK_DIR / f"backfill_{trade_id}_{field}_{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
        with open(fb, "w") as f:
            json.dump({"trade_id": trade_id, "field": field, "old": str(old_val),
                        "new": str(new_val), "error": str(e)}, f)
        return False


def backfill(dry_run=True, verbose=False):
    _safety_checks()

    conn = _get_conn()
    if not conn:
        return {"error": "no_db"}

    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, shares, stop_loss, planned_stop, stop_order_id
        FROM paper_trades WHERE status='open' ORDER BY id
    """)
    cols = [d[0] for d in cur.description]
    trades = [dict(zip(cols, r)) for r in cur.fetchall()]

    broker_stops = _get_broker_stops()
    broker_by_symbol = {}
    for o in broker_stops:
        broker_by_symbol.setdefault(o["symbol"], []).append(o)

    actions = []

    for t in trades:
        tid = t["id"]
        sym = t["symbol"]

        # Backfill planned_stop
        if t["planned_stop"] is None and t["stop_loss"] is not None:
            action = {
                "trade_id": tid, "symbol": sym, "field": "planned_stop",
                "old": None, "new": float(t["stop_loss"]),
                "source": "stop_loss (current DB value)",
                "applied": False,
            }
            if not dry_run:
                cur.execute("UPDATE paper_trades SET planned_stop = stop_loss WHERE id = %s", [tid])
                conn.commit()
                _write_audit(conn, tid, "planned_stop", None, float(t["stop_loss"]))
                action["applied"] = True
            actions.append(action)
            if verbose:
                print(f"  #{tid} {sym}: planned_stop NULL -> {t['stop_loss']} {'(applied)' if action['applied'] else '(dry-run)'}")

        # Backfill stop_order_id
        if t["stop_order_id"] is None:
            matches = [o for o in broker_by_symbol.get(sym, []) if int(o.get("qty", 0)) == t["shares"]]
            if len(matches) == 1:
                oid = matches[0]["id"]
                action = {
                    "trade_id": tid, "symbol": sym, "field": "stop_order_id",
                    "old": None, "new": oid,
                    "source": "exact broker match (symbol + qty)",
                    "applied": False,
                }
                if not dry_run:
                    cur.execute("UPDATE paper_trades SET stop_order_id = %s, stop_updated_at = NOW() WHERE id = %s", [oid, tid])
                    conn.commit()
                    _write_audit(conn, tid, "stop_order_id", None, oid)
                    action["applied"] = True
                actions.append(action)
                if verbose:
                    print(f"  #{tid} {sym}: stop_order_id NULL -> {oid[:12]}... {'(applied)' if action['applied'] else '(dry-run)'}")
            elif len(matches) > 1:
                actions.append({
                    "trade_id": tid, "symbol": sym, "field": "stop_order_id",
                    "old": None, "new": "REVIEW_REQUIRED",
                    "source": f"{len(matches)} broker matches — ambiguous",
                    "applied": False,
                })
                if verbose:
                    print(f"  #{tid} {sym}: stop_order_id REVIEW_REQUIRED ({len(matches)} broker matches)")
            else:
                actions.append({
                    "trade_id": tid, "symbol": sym, "field": "stop_order_id",
                    "old": None, "new": "BROKER_STOP_NOT_FOUND",
                    "source": "no broker stop order found",
                    "applied": False,
                })
                if verbose:
                    print(f"  #{tid} {sym}: stop_order_id BROKER_STOP_NOT_FOUND")

    summary = {
        "total_trades": len(trades),
        "actions": len(actions),
        "applied": sum(1 for a in actions if a.get("applied")),
        "dry_run": dry_run,
        "planned_stop_backfilled": sum(1 for a in actions if a["field"] == "planned_stop" and a.get("applied")),
        "stop_order_id_backfilled": sum(1 for a in actions if a["field"] == "stop_order_id" and a.get("applied")),
        "review_required": sum(1 for a in actions if a.get("new") == "REVIEW_REQUIRED"),
    }

    return {"generated_at": datetime.now(timezone.utc).isoformat(), "summary": summary, "actions": actions}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--output-json", type=str)
    ap.add_argument("--output-md", type=str)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    is_dry = not args.apply
    result = backfill(dry_run=is_dry, verbose=args.verbose)

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"JSON: {args.output_json}")

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        s = result.get("summary", {})
        lines = [
            f"# Stop V2.0 — Backfill {'Apply' if not is_dry else 'Dry Run'}\n\n",
            f"Generated: {result.get('generated_at')}\n\n",
            f"## Summary\n",
            f"- Mode: {'APPLY' if not is_dry else 'DRY RUN'}\n",
            f"- Trades checked: {s.get('total_trades')}\n",
            f"- Actions: {s.get('actions')}\n",
            f"- Applied: {s.get('applied')}\n",
            f"- planned_stop backfilled: {s.get('planned_stop_backfilled')}\n",
            f"- stop_order_id backfilled: {s.get('stop_order_id_backfilled')}\n",
            f"- Review required: {s.get('review_required')}\n\n",
            f"## Actions\n\n",
        ]
        for a in result.get("actions", []):
            lines.append(f"- #{a['trade_id']} {a['symbol']}: {a['field']} "
                         f"{'APPLIED' if a.get('applied') else 'DRY-RUN'} "
                         f"({a.get('source','')})\n")
        with open(args.output_md, "w") as f:
            f.writelines(lines)
        print(f"MD: {args.output_md}")

    print(f"\nSummary: {json.dumps(result.get('summary', {}))}")


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
```

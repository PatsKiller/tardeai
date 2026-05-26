# Source Export: scripts/backfill_trade_plans_for_signals.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/backfill_trade_plans_for_signals.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `0e912ba8ef91b803fb0915d0cc8e5c6413a9588c32e799ae238f3325a62be794` |
| **File Size** | 10524 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""backfill_trade_plans_for_signals.py — Ensure proposal-worthy signals have trade plans.

For every current-day GO/A-grade strategy_signal without complete plan fields,
generates or backfills entry/stop/target/shares from:
  1. Existing trade_plans table
  2. Confluence cache (conf_stop / conf_target)
  3. ATR-based fallback
  4. Conservative default

Usage:
    .venv/bin/python scripts/backfill_trade_plans_for_signals.py --run-label 1000
    .venv/bin/python scripts/backfill_trade_plans_for_signals.py --today
    .venv/bin/python scripts/backfill_trade_plans_for_signals.py --dry-run --today
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("plan_backfill")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

RISK_PER_TRADE = 150  # default dollar risk


def get_conn():
    import psycopg2
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD missing from .env")
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=password,
    )


def get_unplanned_signals(conn, run_label=None):
    """Get current-day proposal-worthy signals missing complete trade plans."""
    cur = conn.cursor()
    sql = """
        SELECT id, symbol, strategy_id, signal_grade, signal_score, price,
               entry_high, entry_low, stop_loss, target_1, target_2, shares,
               dollar_risk, risk_reward, rvol, float_m, gap_pct, sector
        FROM strategy_signals
        WHERE fired_at::date = CURRENT_DATE
        AND (signal_grade IN ('A','A+') OR signal_score >= 40)
        AND (entry_high IS NULL OR stop_loss IS NULL OR target_1 IS NULL OR shares IS NULL OR shares = 0)
    """
    if run_label:
        sql += " AND scan_run_label = %s"
        cur.execute(sql, [run_label])
    else:
        cur.execute(sql)

    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def find_existing_plan(conn, symbol: str) -> dict | None:
    """Look for existing trade_plans entry."""
    cur = conn.cursor()
    cur.execute("""
        SELECT entry_high, entry_low, stop_loss, target_1, target_2,
               shares, dollar_risk, risk_reward_1, atr_value
        FROM trade_plans
        WHERE symbol = %s AND NOT COALESCE(disqualified, false)
        ORDER BY generated_at DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if row:
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    return None


def find_confluence(conn, symbol: str) -> dict | None:
    """Look for confluence cache entry."""
    cur = conn.cursor()
    cur.execute("""
        SELECT stop_price, target_price, entry_quality, atr, confluence_score
        FROM indicator_confluence_cache
        WHERE symbol = %s AND profile = 'scalp'
        ORDER BY computed_at DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if row:
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    return None


def compute_plan(signal: dict, existing_plan: dict | None, confluence: dict | None) -> dict:
    """Compute trade plan from available sources. Returns plan dict."""
    price = float(signal.get("price") or 0)
    if price <= 0:
        return {"quality": "INVALID", "reason": "no_price"}

    entry = price
    stop = None
    target = None
    shares = 0
    atr = None
    quality = "FALLBACK"

    # Priority 1: Existing trade plan
    if existing_plan:
        e = float(existing_plan.get("entry_high") or existing_plan.get("entry_low") or 0)
        s = existing_plan.get("stop_loss")
        t = existing_plan.get("target_1")
        sh = existing_plan.get("shares")
        if e > 0 and s and float(s) > 0 and t and float(t) > 0:
            entry = e
            stop = float(s)
            target = float(t)
            shares = int(sh) if sh else 0
            atr = float(existing_plan["atr_value"]) if existing_plan.get("atr_value") else None
            quality = "PLAN"

    # Priority 2: Confluence cache
    if not stop and confluence:
        cs = confluence.get("stop_price")
        ct = confluence.get("target_price")
        ca = confluence.get("atr")
        if cs and float(cs) > 0:
            stop = float(cs)
        if ct and float(ct) > 0:
            target = float(ct)
        if ca and float(ca) > 0:
            atr = float(ca)
        if stop and target:
            quality = "CONFLUENCE"

    # Priority 3: ATR-based fallback
    if not stop or not target:
        if not atr:
            atr = price * 0.05  # Rough 5% ATR estimate
        stop = stop or round(price - atr, 2)
        target = target or round(price + atr * 1.5, 2)
        if quality not in ("PLAN", "CONFLUENCE"):
            quality = "FALLBACK"

    # Validate long trade constraints
    if stop >= entry:
        stop = round(entry - max(entry * 0.05, 0.20), 2)
    if target <= entry:
        target = round(entry + (entry - stop) * 1.5, 2)

    # Calculate position size from risk
    risk_per_share = abs(entry - stop)
    if risk_per_share > 0:
        shares = shares or max(1, int(RISK_PER_TRADE / risk_per_share))
    else:
        shares = shares or max(1, int(2000 / price)) if price > 0 else 0

    dollar_risk = round(risk_per_share * shares, 2)
    rr = round((target - entry) / risk_per_share, 2) if risk_per_share > 0 else 0
    target_2 = round(entry + (entry - stop) * 3, 2)

    return {
        "entry_high": round(entry, 2),
        "entry_low": round(entry * 0.98, 2),
        "stop_loss": round(stop, 2),
        "target_1": round(target, 2),
        "target_2": round(target_2, 2),
        "shares": shares,
        "dollar_risk": dollar_risk,
        "risk_reward": rr,
        "quality": quality,
        "atr": round(atr, 4) if atr else None,
    }


def backfill_plans(conn, run_label=None, dry_run=False):
    """Main backfill function."""
    signals = get_unplanned_signals(conn, run_label)
    log.info(f"Found {len(signals)} unplanned proposal-worthy signals")

    results = {"total": len(signals), "updated": 0, "skipped": 0, "errors": 0, "details": []}

    for sig in signals:
        symbol = sig["symbol"]
        sig_id = sig["id"]
        try:
            existing_plan = find_existing_plan(conn, symbol)
            confluence = find_confluence(conn, symbol)
            plan = compute_plan(sig, existing_plan, confluence)

            if plan.get("quality") == "INVALID":
                results["skipped"] += 1
                results["details"].append({"symbol": symbol, "status": "skipped", "reason": plan.get("reason")})
                continue

            if dry_run:
                log.info(f"  [dry-run] {symbol}: entry=${plan['entry_high']:.2f} stop=${plan['stop_loss']:.2f} "
                         f"target=${plan['target_1']:.2f} shares={plan['shares']} rr={plan['risk_reward']:.1f} "
                         f"quality={plan['quality']}")
                results["details"].append({"symbol": symbol, "status": "dry_run", **plan})
                continue

            cur = conn.cursor()
            cur.execute("""
                UPDATE strategy_signals
                SET entry_high = %s, entry_low = %s, stop_loss = %s,
                    target_1 = %s, target_2 = %s, shares = %s,
                    dollar_risk = %s, risk_reward = %s
                WHERE id = %s
            """, [
                plan["entry_high"], plan["entry_low"], plan["stop_loss"],
                plan["target_1"], plan["target_2"], plan["shares"],
                plan["dollar_risk"], plan["risk_reward"],
                sig_id,
            ])

            # Also upsert into trade_plans
            cur.execute("""
                INSERT INTO trade_plans
                    (signal_id, strategy_id, symbol, entry_low, entry_high,
                     stop_loss, target_1, target_2, risk_reward_1,
                     shares, dollar_risk, atr_value, generated_by, generated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT DO NOTHING
            """, [
                sig_id, sig.get("strategy_id", "momentum_scalp"), symbol,
                plan["entry_low"], plan["entry_high"],
                plan["stop_loss"], plan["target_1"], plan["target_2"],
                plan["risk_reward"],
                plan["shares"], plan["dollar_risk"],
                plan.get("atr"), f"backfill_{plan['quality'].lower()}",
            ])

            conn.commit()
            results["updated"] += 1
            results["details"].append({"symbol": symbol, "status": "updated", "quality": plan["quality"]})
            log.info(f"  {symbol}: updated ({plan['quality']}) entry=${plan['entry_high']:.2f} "
                     f"stop=${plan['stop_loss']:.2f} target=${plan['target_1']:.2f} shares={plan['shares']}")

        except Exception as e:
            results["errors"] += 1
            results["details"].append({"symbol": symbol, "status": "error", "error": str(e)})
            log.error(f"  {symbol}: error — {e}")
            try:
                conn.rollback()
            except Exception:
                pass

    log.info(f"Backfill complete: {results['updated']} updated, {results['skipped']} skipped, {results['errors']} errors")
    return results


def main():
    parser = argparse.ArgumentParser(description="Backfill trade plans for unplanned strategy signals")
    parser.add_argument("--today", action="store_true", help="Process today's signals")
    parser.add_argument("--run-label", type=str, help="Filter by run label")
    parser.add_argument("--dry-run", action="store_true", help="Preview without updating")
    args = parser.parse_args()

    if not args.today and not args.run_label:
        print("Usage: --today or --run-label 0700")
        sys.exit(1)

    conn = get_conn()
    try:
        result = backfill_plans(conn, run_label=args.run_label, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

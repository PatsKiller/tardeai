#!/usr/bin/env python3
"""cleanup_stale_proposals.py — Reject stale/blocked paper proposals during market hours.

Rejects proposals that are:
- PENDING/APPROVED older than 24 hours
- BLOCKED for more than 4 hours
- MISSING_DATA for more than 48 hours

PAPER ONLY. Does not touch broker, execution, or holdings.

Usage:
    .venv/bin/python scripts/cleanup_stale_proposals.py --dry-run
    .venv/bin/python scripts/cleanup_stale_proposals.py --apply
"""
import argparse, json, sys
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

def get_conn():
    import psycopg2
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""))

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [cleanup] {msg}", flush=True)


def drift_pass(cur, conn, apply: bool) -> int:
    """PRICE DRIFT (2026-07-03, mirrors the watchlist plan-drift rule): a PENDING proposal whose
    live price is >PROPOSAL_DRIFT_PCT from proposed_entry has stale levels — filling it would be
    far from the analyzed setup. Age floor 4h so normal intraday movement doesn't churn fresh
    proposals. Quote source: finviz_quote_cache.json (the cache the repricer maintains)."""
    import json as _json
    import os as _os
    drift_pct = float(_os.environ.get("PROPOSAL_DRIFT_PCT", "15"))
    try:
        qc = _json.loads((PROJ / "data" / "portfolios" / "state" / "finviz_quote_cache.json").read_text())
        quotes = {k.upper(): v.get("price") for k, v in qc.items()
                  if isinstance(v, dict) and not str(k).startswith("_")}
    except Exception:
        return 0
    if not quotes:
        return 0
    cur.execute("""
        SELECT id, symbol, proposed_entry, created_at
        FROM paper_trade_proposals
        WHERE status = 'PENDING' AND paper_trade_id IS NULL
          AND created_at < NOW() - INTERVAL '4 hours'
          AND proposed_entry IS NOT NULL AND proposed_entry > 0
    """)
    drifted = []
    for pid, sym, entry, created in cur.fetchall():
        try:
            px = float(quotes.get(str(sym).upper()) or 0)
            entry_f = float(entry)
        except (TypeError, ValueError):
            continue
        if px <= 0 or entry_f <= 0:
            continue
        pct = abs(px - entry_f) / entry_f * 100
        if pct > drift_pct:
            drifted.append((pid, sym, entry_f, px, pct))
    if not drifted:
        return 0
    log(f"Price-drift pass ({drift_pct:.0f}% threshold): {len(drifted)} PENDING proposal(s)")
    for pid, sym, entry_f, px, pct in drifted:
        log(f"  #{pid} {sym} entry {entry_f:.2f} vs live {px:.2f} ({pct:.0f}%) → price_drift")
    if not apply:
        return len(drifted)
    cur.execute("""
        UPDATE paper_trade_proposals
        SET status = 'REJECTED', action_state = 'REJECTED',
            action_label = 'Auto-rejected: price drifted from proposed entry',
            updated_at = NOW()
        WHERE id = ANY(%s) AND status = 'PENDING' AND paper_trade_id IS NULL
    """, ([d[0] for d in drifted],))
    conn.commit()
    return len(drifted)

def main():
    p = argparse.ArgumentParser(description="Reject stale/blocked paper proposals")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    # Find stale proposals. Never sweep an APPROVED row that already produced a paper trade
    # (it would flip an executed proposal to REJECTED while its paper_trades row stays open).
    cur.execute("""
        SELECT id, symbol, status, action_state, created_at, NOW() - created_at AS age
        FROM paper_trade_proposals
        WHERE status IN ('PENDING', 'APPROVED', 'APPROVED_FOR_PAPER_TEST')
          AND paper_trade_id IS NULL
          AND (
            created_at < NOW() - INTERVAL '24 hours'
            OR (action_state = 'BLOCKED' AND created_at < NOW() - INTERVAL '4 hours')
            OR (action_state = 'MISSING_DATA' AND created_at < NOW() - INTERVAL '48 hours')
          )
        ORDER BY created_at
    """)
    stale = cur.fetchall()

    drift_n = drift_pass(cur, conn, apply=args.apply)
    if drift_n and args.dry_run:
        log(f"DRY RUN — {drift_n} drift rejection(s) not applied.")

    if not stale:
        log("No stale paper proposals to clean up.")
        conn.close()
        try:
            sys.path.insert(0, str(PROJ / "scripts"))
            import broker_queue_hygiene as bqh
            sweep = bqh.sweep_broker_queue(dry_run=False, refresh_quotes=True)
            log(
                f"Broker queue hygiene: checked={sweep.get('checked')} "
                f"expired={sweep.get('expired', sweep.get('would_expire', 0))} "
                f"rejected={sweep.get('rejected', sweep.get('would_reject', 0))}"
            )
        except Exception as e:
            log(f"Broker queue hygiene skipped: {e}")
        return

    log(f"Found {len(stale)} stale proposals:")
    for row in stale:
        pid, sym, status, action, created, age = row
        reason = "blocked" if action == "BLOCKED" else ("missing_data" if action == "MISSING_DATA" else "stale_24h")
        log(f"  #{pid} {sym} [{status}/{action}] age={age} → {reason}")

    if args.dry_run:
        log("DRY RUN — no changes made.")
        conn.close()
        return

    cur.execute("""
        UPDATE paper_trade_proposals
        SET status = 'REJECTED',
            action_state = 'REJECTED',
            action_label = CASE
              WHEN action_state = 'BLOCKED' THEN 'Auto-rejected: blocked and stale'
              WHEN action_state = 'MISSING_DATA' THEN 'Auto-rejected: missing data and stale'
              ELSE 'Auto-rejected: older than 24h'
            END,
            updated_at = NOW()
        WHERE status IN ('PENDING', 'APPROVED', 'APPROVED_FOR_PAPER_TEST')
          AND paper_trade_id IS NULL
          AND (
            created_at < NOW() - INTERVAL '24 hours'
            OR (action_state = 'BLOCKED' AND created_at < NOW() - INTERVAL '4 hours')
            OR (action_state = 'MISSING_DATA' AND created_at < NOW() - INTERVAL '48 hours')
          )
        RETURNING id, symbol
    """)
    rejected = cur.fetchall()
    conn.commit()
    conn.close()

    log(f"Rejected {len(rejected)} stale proposals.")
    for pid, sym in rejected:
        log(f"  #{pid} {sym}")

    try:
        sys.path.insert(0, str(PROJ / "scripts"))
        import broker_queue_hygiene as bqh
        sweep = bqh.sweep_broker_queue(dry_run=False, refresh_quotes=True)
        log(
            f"Broker queue hygiene: checked={sweep.get('checked')} "
            f"expired={sweep.get('expired', sweep.get('would_expire', 0))} "
            f"rejected={sweep.get('rejected', sweep.get('would_reject', 0))}"
        )
    except Exception as e:
        log(f"Broker queue hygiene skipped: {e}")

if __name__ == "__main__":
    main()

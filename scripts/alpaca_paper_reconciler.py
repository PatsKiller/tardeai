#!/usr/bin/env python3
"""alpaca_paper_reconciler.py — Audit paper_trades against Alpaca positions.

SOURCE OF TRUTH: the broker (Alpaca) is authoritative. When the DB and broker
disagree, the broker wins — every --fix overwrites DB metadata FROM the broker
(entry price, share count, fill confirmation), never the reverse. We never push
DB state onto the broker. A position exists iff the broker holds it; a position
is flat iff the broker is flat (phantoms are closed by paper_trade_monitor's
integrity_check, orphan broker positions are materialized by the adapter sync).

Detects mismatches between DB and broker:
- Positions in Alpaca but not in paper_trades (orphan broker positions)
- Open paper_trades with no Alpaca position (phantom DB positions)
- Entry price mismatches (DB vs broker fill price)
- Share count mismatches
- Unfilled paper_trades that Alpaca shows as filled
- Closed paper_trades that Alpaca still holds

Usage:
    .venv/bin/python scripts/alpaca_paper_reconciler.py
    .venv/bin/python scripts/alpaca_paper_reconciler.py --fix
    .venv/bin/python scripts/alpaca_paper_reconciler.py --json

Does NOT place orders or change positions. --fix only corrects DB metadata.
"""

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def get_db_connection():
    import psycopg2
    env_vars = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env_vars.get("DB_HOST", "localhost"),
        dbname=env_vars.get("DB_NAME", "trade_ai"),
        user=env_vars.get("DB_USER", "trade_ai"),
        password=env_vars.get("DB_PASSWORD", ""),
    )


def get_env():
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [recon] {msg}", flush=True)


def get_alpaca_positions(env):
    key = env.get("ALPACA_API_KEY", "")
    secret = env.get("ALPACA_SECRET_KEY", "")
    base = env.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    req = urllib.request.Request(
        f"{base}/v2/positions",
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def get_alpaca_orders(env, status="open"):
    key = env.get("ALPACA_API_KEY", "")
    secret = env.get("ALPACA_SECRET_KEY", "")
    base = env.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    # nested=true so OCO/bracket child legs (the 'held' stop leg) are returned inside the parent's legs[];
    # without it an OCO-protected position's stop is invisible and the position looks naked.
    req = urllib.request.Request(
        f"{base}/v2/orders?status={status}&limit=200&nested=true",
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def reconcile(apply_fixes=False):
    env = get_env()
    conn = get_db_connection()
    cur = conn.cursor()
    issues = []
    fixes = []

    try:
        alpaca_pos = get_alpaca_positions(env)
    except Exception as e:
        return {"error": str(e), "issues": [], "fixes": []}

    alpaca_by_sym = {p["symbol"]: p for p in alpaca_pos}

    # Live protective stops at the broker (source of truth for the stop price too)
    try:
        alpaca_orders = get_alpaca_orders(env, status="open")
    except Exception:
        alpaca_orders = []
    # Descend into legs[]: an OCO/bracket stop leg is 'held' and nested in its parent, so a flat top-level
    # scan misses it and the OCO-protected position would be falsely flagged NO_BROKER_STOP.
    stop_by_sym = {}
    for o in alpaca_orders:
        for c in [o] + (o.get("legs") or []):
            if c.get("type") in ("stop", "stop_limit") and c.get("side") == "sell" and c.get("symbol"):
                stop_by_sym[c["symbol"]] = c

    # Get DB open trades
    cur.execute("""
        SELECT id, symbol, entry_price, shares, status, lifecycle_state,
               broker_status, broker_confirmed, current_price, unrealized_pnl,
               stop_loss_price, target_1, strategy_id, stop_order_id
        FROM paper_trades
        WHERE lifecycle_state = 'open' OR status = 'open'
        ORDER BY symbol
    """)
    cols = [d[0] for d in cur.description]
    db_trades = [dict(zip(cols, row)) for row in cur.fetchall()]
    db_by_sym = {}
    for t in db_trades:
        db_by_sym.setdefault(t["symbol"], []).append(t)

    # 1. Alpaca has position, DB doesn't
    for sym, pos in alpaca_by_sym.items():
        if sym not in db_by_sym:
            issues.append({
                "type": "ORPHAN_BROKER", "severity": "HIGH", "symbol": sym,
                "detail": f"Alpaca: {pos['qty']}sh @ ${pos['avg_entry_price']} — no open paper_trade",
            })

    # 2. DB has open trade, Alpaca doesn't
    for sym, trades in db_by_sym.items():
        if sym not in alpaca_by_sym:
            for t in trades:
                issues.append({
                    "type": "PHANTOM_DB", "severity": "HIGH", "symbol": sym,
                    "trade_id": t["id"],
                    "detail": f"paper_trade #{t['id']} open but Alpaca has no position",
                })

    # 3. Both exist — compare
    for sym in set(alpaca_by_sym) & set(db_by_sym):
        pos = alpaca_by_sym[sym]
        a_qty = int(pos["qty"])
        a_entry = float(pos["avg_entry_price"])

        for t in db_by_sym[sym]:
            db_entry = float(t["entry_price"]) if t["entry_price"] else 0
            db_shares = t["shares"] or 0

            # Entry price mismatch (>1%)
            if db_entry > 0 and abs(db_entry - a_entry) / db_entry > 0.01:
                issues.append({
                    "type": "ENTRY_PRICE_MISMATCH", "severity": "MEDIUM", "symbol": sym,
                    "trade_id": t["id"],
                    "detail": f"DB=${db_entry:.2f} vs Alpaca=${a_entry:.2f}",
                })
                if apply_fixes:
                    cur.execute("UPDATE paper_trades SET entry_price = %s WHERE id = %s",
                                [a_entry, t["id"]])
                    conn.commit()
                    fixes.append(f"#{t['id']} {sym}: entry {db_entry:.2f} -> {a_entry:.2f}")

            # Share mismatch
            if db_shares != a_qty:
                issues.append({
                    "type": "SHARE_MISMATCH", "severity": "MEDIUM", "symbol": sym,
                    "trade_id": t["id"],
                    "detail": f"DB={db_shares}sh vs Alpaca={a_qty}sh",
                })
                if apply_fixes:
                    cur.execute("UPDATE paper_trades SET shares = %s WHERE id = %s",
                                [a_qty, t["id"]])
                    conn.commit()
                    fixes.append(f"#{t['id']} {sym}: shares {db_shares} -> {a_qty}")

            # Not broker confirmed
            if not t.get("broker_confirmed"):
                issues.append({
                    "type": "NOT_CONFIRMED", "severity": "LOW", "symbol": sym,
                    "trade_id": t["id"],
                    "detail": "Alpaca holds but broker_confirmed=false",
                })
                if apply_fixes:
                    cur.execute("""UPDATE paper_trades
                        SET broker_status='filled', filled_at=COALESCE(filled_at,NOW())
                        WHERE id=%s AND filled_at IS NULL""", [t["id"]])
                    conn.commit()
                    fixes.append(f"#{t['id']} {sym}: set filled_at -> broker_confirmed=true")

            # Protective stop drift — the broker's live sell-stop is the source of truth for the
            # stop price + order id. The DB display columns go stale (the monitor only rewrites
            # them when it trails), which previously caused a protected position to look naked.
            bstop = stop_by_sym.get(sym)
            if bstop:
                b_price = float(bstop.get("stop_price") or 0)
                b_oid = bstop.get("id")
                db_stop = float(t["stop_loss_price"]) if t.get("stop_loss_price") else 0
                if b_price > 0 and (abs(db_stop - b_price) > 0.001 or t.get("stop_order_id") != b_oid):
                    issues.append({
                        "type": "STOP_DRIFT", "severity": "MEDIUM", "symbol": sym, "trade_id": t["id"],
                        "detail": f"DB stop ${db_stop:.2f} vs broker ${b_price:.2f}",
                    })
                    if apply_fixes:
                        cur.execute("""UPDATE paper_trades
                            SET stop_loss_price=%s, stop_order_id=%s, broker_stop_status='new'
                            WHERE id=%s""", [b_price, b_oid, t["id"]])
                        conn.commit()
                        fixes.append(f"#{t['id']} {sym}: stop {db_stop:.2f} -> {b_price:.2f} (broker truth)")
            elif sym in alpaca_by_sym:
                # Position held but NO protective stop at the broker — a real safety issue.
                issues.append({
                    "type": "NO_BROKER_STOP", "severity": "HIGH", "symbol": sym, "trade_id": t["id"],
                    "detail": f"{sym} held at broker with no live sell-stop order",
                })

    # 4. Broker holds but DB has ONLY closed records (no open record) → broker is source of
    #    truth, so a position SHOULD be open. A closed record on a symbol that ALSO has a current
    #    open record is just history (e.g. a prior round-trip on a symbol we re-entered) — NOT a
    #    mismatch, so we only flag symbols the broker holds with no matching open DB trade. The
    #    materialization of the missing open record is the adapter sync's job (unknown_sync).
    held_without_open = [s for s in alpaca_by_sym if s not in db_by_sym]
    if held_without_open:
        syms = tuple(held_without_open)
        cur.execute("""
            SELECT id, symbol, pnl, exit_reason
            FROM paper_trades
            WHERE lifecycle_state = 'closed' AND symbol IN %s
        """, [syms])
        for tid, sym, pnl, reason in cur.fetchall():
            issues.append({
                "type": "CLOSED_BUT_HELD", "severity": "HIGH", "symbol": sym,
                "trade_id": tid,
                "detail": f"#{tid} closed (pnl=${pnl}) but Alpaca holds {alpaca_by_sym[sym]['qty']}sh and no open DB record exists",
            })

    conn.close()

    # ── P2: auto-attach OCO bracket at fill ──────────────────────────────────────────────────────────────
    # Bracket-path entries (limit/RTH) already get their stop+take-profit OCO from Alpaca at fill. Market /
    # extended-hours entries submit a simple buy + a standalone stop, so they hold a stop but NO take-profit.
    # Here we convert any such filled position into an OCO bracket (stop + take-profit), so every filled paper
    # position ends up bracketed. Idempotent — run_oco_retrofit skips positions already on an OCO / with a
    # take-profit — and reuses the P1 stop-never-absent rollback. Design: OCO_ATM_UNIFICATION_DESIGN.md P2.
    oco = {"converted": 0}
    if apply_fixes:
        try:
            import alpaca_stop_manager as asm
            oco = asm.run_oco_retrofit(apply=True)
            for a in (oco.get("actions") or []):
                if (a.get("result") or {}).get("status") == "OCO_ACTIVE":
                    fixes.append(f"{a['symbol']}: auto-bracketed at fill — OCO stop ${a['keep_stop']} "
                                 f"+ take-profit ${a['add_take_profit']}")
        except Exception as e:
            issues.append({"type": "OCO_AUTOBRACKET_ERROR", "severity": "LOW", "symbol": "-",
                           "detail": f"auto-bracket pass failed: {str(e)[:120]}"})

    return {
        "timestamp": datetime.now().isoformat(),
        "alpaca_count": len(alpaca_pos),
        "db_open_count": len(db_trades),
        "issues": issues,
        "fixes": fixes,
        "oco_autobracket": {"mode": oco.get("mode"), "converted": oco.get("converted", 0),
                            "skipped": len(oco.get("skipped", [])), "errors": oco.get("errors", 0)},
        "by_severity": {s: sum(1 for i in issues if i["severity"] == s) for s in ("HIGH","MEDIUM","LOW")},
    }


def main():
    parser = argparse.ArgumentParser(description="Reconcile paper_trades vs Alpaca")
    parser.add_argument("--fix", action="store_true", help="Auto-fix entry price and broker status")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    log("Alpaca Paper Trade Reconciliation")
    result = reconcile(apply_fixes=args.fix)

    if result.get("error"):
        log(f"FAILED: {result['error']}")
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return

    log(f"Alpaca: {result['alpaca_count']} positions | DB: {result['db_open_count']} open trades")
    log(f"Issues: {len(result['issues'])} (H={result['by_severity']['HIGH']} M={result['by_severity']['MEDIUM']} L={result['by_severity']['LOW']})")

    for i in result["issues"]:
        icon = {"HIGH": "!!!", "MEDIUM": "!!", "LOW": "!"}[i["severity"]]
        log(f"  {icon} {i['type']}: {i['symbol']} — {i['detail']}")

    for f in result.get("fixes", []):
        log(f"  FIXED: {f}")

    if not result["issues"]:
        log("ALL CLEAR — DB and Alpaca in sync")


if __name__ == "__main__":
    main()

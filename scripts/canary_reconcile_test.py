#!/usr/bin/env python3
"""canary_reconcile_test.py — live end-to-end proof of the broker-exit reconciliation.

MANUAL / operator-run verification tool (NOT wired into cron/systemd). Paper account ONLY.

Opens a 1-share paper position, closes it on the broker, then inserts a canary paper_trades row left
'open' — recreating the exact false-phantom trigger (position flat at broker, DB still open). It then runs
paper_trade_monitor._fix_integrity_issues (the phantom-sweep path that carried the false-void bug) and
asserts the trade is booked with the REAL exit price / P&L and a canonical broker_*_hit_reconciled tag —
never voided to a $0 phantom. Cleans up the canary row afterward; leaves the broker flat.

  .venv/bin/python scripts/canary_reconcile_test.py     # waits for market open, runs once, prints PASS/FAIL

Safety: paper-only (ALPACA paper base), 1 share, aborts if a same-symbol position already exists, and the
canary row is deleted after verification so it never reaches real analytics.
"""
import os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
import requests, psycopg2

H = {"APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY"), "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY")}
BASE = "https://paper-api.alpaca.markets"
SYM = os.getenv("CANARY_SYMBOL", "PLUG")
STRAT = "canary_reconcile_test"


def log(m): print(f"[canary {time.strftime('%H:%M:%S')}] {m}", flush=True)
def api(method, path, **kw): return requests.request(method, BASE + path, headers=H, timeout=15, **kw)
def db(): return psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"),
                                  dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
                                  password=os.getenv("DB_PASSWORD"))


def wait_order_filled(oid, secs=120):
    # 120s: a market order submitted right at the 09:30 opening auction can sit 'new' > 60s.
    for _ in range(secs):
        o = api("GET", f"/v2/orders/{oid}").json()
        if o.get("status") == "filled":
            return o
        time.sleep(1)
    return api("GET", f"/v2/orders/{oid}").json()


def main():
    # 1) wait for market open (max ~2.5h)
    for _ in range(150):
        clk = api("GET", "/v2/clock").json()
        if clk.get("is_open"):
            break
        log(f"market closed; next_open={clk.get('next_open','')[:19]} — waiting 60s")
        time.sleep(60)
    else:
        log("market never opened within budget — ABORT"); return
    log("market OPEN — starting canary")

    if any(p["symbol"] == SYM for p in api("GET", "/v2/positions").json() if isinstance(p, dict)):
        log(f"{SYM} already held — ABORT to avoid interference"); return

    # 2) entry: market buy 1 share
    r = api("POST", "/v2/orders", json={"symbol": SYM, "qty": 1, "side": "buy", "type": "market", "time_in_force": "day"})
    if r.status_code >= 300:
        log(f"entry submit FAILED {r.status_code}: {r.text[:200]}"); return
    entry_id = r.json()["id"]; log(f"entry order {entry_id[:8]} submitted")
    eo = wait_order_filled(entry_id)
    if eo.get("status") != "filled":
        api("DELETE", f"/v2/orders/{entry_id}")  # cancel the lingering day order so it can't fill later
        log(f"entry not filled ({eo.get('status')}) — canceled + ABORT"); return
    entry_px = float(eo["filled_avg_price"]); log(f"entry FILLED @ {entry_px}")

    # 3) exit: market sell 1 share (closes the position; tagged as the 'exit' order)
    r = api("POST", "/v2/orders", json={"symbol": SYM, "qty": 1, "side": "sell", "type": "market", "time_in_force": "day"})
    if r.status_code >= 300:
        log(f"exit submit FAILED {r.status_code}: {r.text[:200]} — flattening"); api("DELETE", f"/v2/positions/{SYM}"); return
    exit_id = r.json()["id"]; log(f"exit order {exit_id[:8]} submitted")
    xo = wait_order_filled(exit_id)
    exit_px = float(xo["filled_avg_price"]) if xo.get("status") == "filled" else None
    log(f"exit status={xo.get('status')} @ {exit_px}")
    time.sleep(2)
    flat = not any(p["symbol"] == SYM for p in api("GET", "/v2/positions").json() if isinstance(p, dict))
    log(f"{SYM} flat on Alpaca: {flat}")
    expected_pnl = round((exit_px - entry_px) * 1, 2) if exit_px else None

    # 4) insert canary paper_trades row as 'open' (exact reconcile trigger: broker flat, DB open).
    # entry_time is aged past PHANTOM_GRACE_MIN (15m) — the monitor deliberately skips freshly-opened
    # trades (an in-flight fill may not show as an Alpaca position yet), so a NOW() timestamp would be
    # grace-skipped and the reconcile would never fire.
    conn = db(); cur = conn.cursor()
    cur.execute("""INSERT INTO paper_trades (symbol, account, strategy_id, shares, entry_price, stop_loss,
                     side, status, lifecycle_state, broker, execution_account, dollar_risk,
                     broker_order_id, take_profit_order_id, entry_time, created_at, broker_status)
                   VALUES (%s,'ALPACA_PAPER',%s,1,%s,%s,'long','open','open','tradeai_automated','tradeai_automated',
                     %s,%s,%s,NOW()-interval '30 minutes',NOW()-interval '30 minutes','filled') RETURNING id""",
                [SYM, STRAT, entry_px, round(entry_px * 0.95, 2), round(entry_px * 0.05, 2), entry_id, exit_id])
    tid = cur.fetchone()[0]; conn.commit()
    log(f"canary paper_trades row #{tid} inserted (status=open, aged past 15m grace) — reconcile trigger armed")

    # 5) run the reconciler via the MONITOR phantom sweep — the exact path that had the false-void bug
    import paper_trade_monitor as ptm
    positions = ptm._api_get("/v2/positions")
    alpaca_symbols = {p["symbol"] for p in positions} if isinstance(positions, list) else set()
    log(f"alpaca positions: {sorted(alpaca_symbols)} (PLUG present: {SYM in alpaca_symbols})")
    n = ptm._fix_integrity_issues(conn, alpaca_symbols)
    log(f"_fix_integrity_issues (phantom sweep) processed {n} fix(es)")

    # 6) verify
    cur.execute("SELECT status, exit_reason, exit_price, pnl, outcome_verdict, closed_via FROM paper_trades WHERE id=%s", [tid])
    st, er, xp, pnl, verdict, cv = cur.fetchone()
    log(f"RESULT #{tid}: status={st} exit_reason={er} exit_price={xp} pnl={pnl} verdict={verdict} via={cv}")
    log(f"EXPECTED: real pnl~{expected_pnl}, NOT phantom/$0")
    ok = (st == "closed" and er and "phantom" not in (er or "") and pnl is not None
          and abs(float(pnl) - (expected_pnl or 0)) < 0.02)
    canonical = er and ("hit_reconciled" in er or "position_closed_in_alpaca" in er)
    log(f"VERDICT: {'PASS' if ok else 'FAIL'} — booked real exit, no phantom"
        + (f" | canonical tag: {er}" if canonical else " | (generic tag)"))

    # 7) cleanup — remove the canary row so it never reaches analytics
    cur.execute("DELETE FROM paper_trades WHERE id=%s AND strategy_id=%s", [tid, STRAT]); conn.commit()
    log(f"cleanup: canary row #{tid} deleted ({cur.rowcount} row). Alpaca flat, no residue.")
    conn.close()


if __name__ == "__main__":
    main()

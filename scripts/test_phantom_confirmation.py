"""test_phantom_confirmation.py — STEP 2 proof for the broker-confirmation gate.

Side-effect-light: confirms against REAL existing broker orders (places no new order), and
writes only to the hermes_fill_verifications staging table. Does NOT mutate paper_trades and
does NOT touch the live gate. Proves:

  1. a real confirmed fill passes the gate (BROKER_CONFIRMED + two-source VERIFIED)
  2. all historical phantoms are caught (not BROKER_CONFIRMED, not COUNTED)
  3. before/after win rate when only broker-proven fills count (computed, not applied)
  4. zero "alpaca" literals in the gate/verification logic
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_adapter import get_connection
from broker_confirmation_gate import confirm_and_finalize
from trade_fill_verifier import trade_ai_verify, hermes_verify, is_counted

VENDOR_NEUTRAL_FILES = ["broker_adapter.py", "broker_confirmation_gate.py", "trade_fill_verifier.py"]


def _rows(cur, sql, params=None):
    cur.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _broker_held_symbols():
    try:
        from broker_adapter import adapter_for
        a = adapter_for("tradeai_automated")
        return {p.get("symbol") for p in (a.get_positions() or []) if p.get("symbol")}
    except Exception:
        return set()


def section(t):
    print(f"\n{'='*72}\n{t}\n{'='*72}")


def main():
    # Warm the broker_config cache FIRST: its first DB read closes the shared global connection
    # (get_all_accounts → conn.close()), which would invalidate our cursor mid-run. After warm-up
    # it is cache-only and never closes the connection again.
    from broker_config import get_account_broker
    get_account_broker("tradeai_automated")
    held = _broker_held_symbols()
    conn = get_connection()      # fresh/reconnected after the warm-up close
    cur = conn.cursor()

    # ── 1. real confirmed fill passes ────────────────────────────────────────
    section("1. REAL FILL — a confirmed broker order passes the gate")
    open_linked = _rows(cur, """
        SELECT id, symbol, account, shares, entry_price, broker_order_id
        FROM paper_trades
        WHERE status='open' AND broker_order_id IS NOT NULL AND account ILIKE %s
        ORDER BY id LIMIT 1
    """, ['alpaca%'])
    passed_real = False
    if not open_linked:
        print("  (no order-linked open trade available to test against)")
    else:
        t = open_linked[0]
        fc, state = confirm_and_finalize(t, apply=False, held_at_broker=t["symbol"] in held)
        ai = trade_ai_verify(t)
        hz = hermes_verify(conn, t)
        counted = is_counted(t, ai, hz)
        passed_real = state == "BROKER_CONFIRMED" and counted
        print(f"  #{t['id']} {t['symbol']} order={t['broker_order_id'][:12]}…")
        print(f"    gate state      : {state}  (broker confirmed={fc.confirmed}, status={fc.status})")
        print(f"    TradeAI verify  : {ai['verdict']} (qty_match={ai['qty_match']}, price_match={ai['price_match']})")
        print(f"    Hermes verify   : {hz['verdict']} (confirmed={hz['confirmed']})")
        print(f"    COUNTED         : {counted}")
        print(f"    => {'PASS' if passed_real else 'FAIL'}: a real fill is recognized as broker-proven")

    # ── 2. phantoms are caught ───────────────────────────────────────────────
    section("2. PHANTOMS — every historical phantom is caught (never COUNTED)")
    phantoms = _rows(cur, """
        SELECT id, symbol, account, shares, entry_price, broker_order_id, opened_via, outcome_verdict
        FROM paper_trades
        WHERE outcome_verdict='PHANTOM' OR close_reason='phantom_no_alpaca_position'
        ORDER BY id
    """)
    caught = 0
    for t in phantoms:
        fc, state = confirm_and_finalize(t, apply=False, held_at_broker=t["symbol"] in held)
        ai = trade_ai_verify(t)
        hz = hermes_verify(conn, t)
        counted = is_counted(t, ai, hz)
        ok = not counted and state != "BROKER_CONFIRMED"
        caught += ok
        print(f"  #{t['id']:<3} {t['symbol']:<6} via={t['opened_via']:<17} order_id={'yes' if t['broker_order_id'] else 'NULL':<4} "
              f"-> {state:<24} counted={counted}  {'CAUGHT' if ok else 'LEAKED!'}")
    print(f"\n  => {caught}/{len(phantoms)} phantoms caught"
          + ("" if caught == len(phantoms) else "  *** LEAK ***"))

    # ── 3. before/after win rate ─────────────────────────────────────────────
    section("3. WIN RATE — all closed vs broker-proven only (computed, NOT applied)")
    def winrate(where):
        r = _rows(cur, f"""
            SELECT
              COUNT(*) FILTER (WHERE pnl > 0) AS wins,
              COUNT(*) FILTER (WHERE pnl < 0) AS losses
            FROM paper_trades
            WHERE status='closed' AND COALESCE(pnl,0) <> 0 AND {where}
        """)[0]
        w, l = r["wins"] or 0, r["losses"] or 0
        return w, l, round(100*w/(w+l), 1) if (w+l) else 0.0
    bw, bl, bpct = winrate("TRUE")
    aw, al, apct = winrate("broker_order_id IS NOT NULL AND broker_confirmed")
    print(f"  BEFORE (all closed)        : {bpct}%  ({bw}W / {bl}L, n={bw+bl})")
    print(f"  AFTER  (broker-proven only): {apct}%  ({aw}W / {al}L, n={aw+al})")
    print(f"  => win rate moves {bpct}% -> {apct}% when only broker-proven fills count")

    # ── 4. agnosticism proof ─────────────────────────────────────────────────
    section("4. AGNOSTICISM — zero vendor literals in gate/verification logic")
    here = os.path.dirname(os.path.abspath(__file__))
    all_clean = True
    for f in VENDOR_NEUTRAL_FILES:
        n = subprocess.run(["grep", "-ic", "alpaca", os.path.join(here, f)],
                           capture_output=True, text=True).stdout.strip()
        clean = n == "0"
        all_clean &= clean
        print(f"  {f:<32} alpaca literals: {n}  {'OK' if clean else 'VIOLATION'}")

    section("SUMMARY")
    print(f"  1. real fill passes          : {'PASS' if passed_real else 'FAIL'}")
    print(f"  2. phantoms caught           : {caught}/{len(phantoms)}")
    print(f"  3. win rate before/after     : {bpct}% -> {apct}%")
    print(f"  4. vendor-neutral gate logic : {'PASS' if all_clean else 'FAIL'}")
    ok = passed_real and caught == len(phantoms) and all_clean
    print(f"\n  STEP 2 {'PASSED' if ok else 'INCOMPLETE'} — no live wiring, no paper_trades mutation.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""sync_basis_from_broker.py — single-source-of-truth basis sync (operator decision 2026-06-12).

Found via audit_position_basis.py: 8 Schwab positions carried phantom basis (SCHD $4.02 vs broker
$31.04 → +$111K fake gain, etc.) because holdings.json basis came from stale CSV-window
reconstruction. New hierarchy, applied here:

  1. schwab_cost_basis_lots (Positions/Gain-Loss export — true TAX LOTS) when qty matches ±1%
  1.5 trade_transactions purchase history (txn_history) — ONLY for freshly ACATS'd positions
      whose broker basis is provably incomplete (2026-07-18 finding: 7 Fidelity→Schwab positions
      showed +97–104% because Schwab had received lots for only ~half the shares; QCOM "+101%"
      was really −7.8%). Requires: Security Transfer ≤45d + complete net-buy history matching
      held qty ±1% + broker basis <90% of txn basis. Self-heals: once Schwab's basis catches up,
      tier 2 wins again.
  2. Schwab API averagePrice (broker's own average cost — includes transfer-carried basis)
  3. (nothing — flagged partial; reconstruction is DEMOTED to Fidelity-only, never Schwab-primary)

Also upserts the raw API positions into schwab_positions_live (the DB canonical layer).
holdings.json is written ONLY through protected_holdings_write (Gate B: backup + atomic +
sanity/catastrophic-drop guards). READ-ONLY toward Schwab (transport reads / server endpoint).

  python3 scripts/sync_basis_from_broker.py            # dry-run: shows every change
  python3 scripts/sync_basis_from_broker.py --apply    # write (Gate B protected)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

HJ = PROJECT_ROOT / "data/portfolios/state/holdings.json"


def _api_positions():
    """Live positions per account: direct transport, else the running server (it holds the creds)."""
    import schwab_transport as st
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    cur.execute("SELECT account_key FROM broker_accounts WHERE broker ILIKE '%schwab%' ORDER BY 1")
    accounts = [r[0] for r in cur.fetchall()]
    out, errors = {}, {}
    for ak in accounts:
        pos = st.get_positions(ak)
        if isinstance(pos, dict):
            errors[ak] = pos.get("status")
        else:
            for p in pos:
                out[(ak, p["symbol"].upper())] = p
    if errors:
        try:
            import urllib.request
            with urllib.request.urlopen("http://localhost:7777/api/v2/schwab/accounts-live", timeout=30) as r:
                d = json.load(r)
            for a in (d.get("data", d)).get("accounts", []):
                if a.get("positions_status") == "ok":
                    errors.pop(a["account_key"], None)
                    for p in a["positions"]:
                        out[(a["account_key"], p["symbol"].upper())] = p
        except Exception as e:
            errors["_server_fallback"] = str(e)[:80]
    return out, errors


_BUY_ACTIONS = ("Buy", "Reinvest Shares", "Reinvest Dividend", "Reinvested Dividend",
                "Long Term Cap Gain Reinvest")


def _txn_history(cur):
    """Purchase-history basis + recent-transfer map for the ACATS partial-basis guard.

    Returns ({SYM: (net_qty, avg_cost_per_share)}, {(account_key, SYM)}) where the second set
    marks symbols with a Security Transfer into that Schwab account in the last 45 days.
    Basis is average-cost across ALL accounts' buys minus sells — correct only when the whole
    position's history is in the ledger, which the qty-match gate in main() enforces.
    """
    cur.execute("""SELECT upper(symbol),
                          sum(CASE WHEN action = ANY(%s) THEN quantity ELSE -quantity END),
                          sum(CASE WHEN action = ANY(%s) THEN quantity * price ELSE 0 END),
                          sum(CASE WHEN action = ANY(%s) THEN quantity ELSE 0 END)
                   FROM trade_transactions
                   WHERE action = ANY(%s) OR action = 'Sell'
                   GROUP BY 1""",
                (list(_BUY_ACTIONS), list(_BUY_ACTIONS), list(_BUY_ACTIONS), list(_BUY_ACTIONS)))
    hist = {}
    for sym, net_qty, buy_cost, buy_qty in cur.fetchall():
        if float(buy_qty or 0) > 0:
            hist[sym] = (float(net_qty or 0), float(buy_cost) / float(buy_qty))
    cur.execute("""SELECT DISTINCT account, upper(symbol) FROM trade_transactions
                   WHERE action = 'Security Transfer'
                     AND trade_date >= CURRENT_DATE - INTERVAL '45 days'""")
    recent_xfer = {(a, s) for a, s in cur.fetchall()}
    return hist, recent_xfer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    api, errors = _api_positions()
    if errors:
        print(f"⚠ API unavailable for {errors} — refusing to sync basis from partial data")
        sys.exit(1)

    # canonical DB layer
    if a.apply:
        for (ak, sym), p in api.items():
            cur.execute("""INSERT INTO schwab_positions_live (account_key, symbol, qty, avg_price,
                             market_value, unrealized_pl, captured_at)
                           VALUES (%s,%s,%s,%s,%s,%s,NOW())
                           ON CONFLICT (account_key, symbol) DO UPDATE SET qty=EXCLUDED.qty,
                             avg_price=EXCLUDED.avg_price, market_value=EXCLUDED.market_value,
                             unrealized_pl=EXCLUDED.unrealized_pl, captured_at=NOW()""",
                        (ak, sym, p["qty"], p["avg_entry_price"], p["market_value"], p["unrealized_pl"]))
        conn.commit()
        print(f"schwab_positions_live upserted: {len(api)} rows")

    # tax-lot layer
    cur.execute("SELECT account, symbol, quantity, cost_basis FROM schwab_cost_basis_lots WHERE kind='unrealized'")
    lots = {(r[0], r[1].upper()): (float(r[2] or 0), float(r[3] or 0)) for r in cur.fetchall()}

    txn_hist, recent_xfer = _txn_history(cur)

    h = json.loads(HJ.read_text())
    changes = []
    for x in h.get("holdings", []):
        acct = (x.get("account") or "")
        if not acct.startswith("schwab") or x.get("is_cash") or (x.get("symbol") or "").upper() == "CASH":
            continue
        ak = "schwab_roth_ira" if acct == "schwab_roth" else acct
        sym = (x.get("symbol") or "").upper()
        qty = float(x.get("shares") or x.get("quantity") or 0)
        old_basis, old_src = x.get("cost_basis"), x.get("cost_basis_source")
        lot = lots.get((ak, sym))
        p = api.get((ak, sym))
        new_basis = new_src = None
        if lot and qty and abs(lot[0] - qty) / qty <= 0.01:
            new_basis, new_src = lot[1], "csv_lot"                       # tier 1: true tax lots
        elif p and float(p["avg_entry_price"] or 0) > 0:
            new_basis, new_src = round(float(p["avg_entry_price"]) * qty, 2), "broker_api"   # tier 2
            # tier 1.5 — ACATS partial-basis guard: fresh transfer + complete purchase history
            # + broker basis provably short → the ledger's average cost is the truth.
            th = txn_hist.get(sym)
            if (th and qty and (ak, sym) in recent_xfer
                    and abs(th[0] - qty) / qty <= 0.01
                    and new_basis < 0.90 * round(th[1] * qty, 2)):
                x["_broker_reported_basis"] = new_basis
                new_basis, new_src = round(th[1] * qty, 2), "txn_history"
        if new_basis is None:
            continue
        if new_src != "txn_history":
            x.pop("_broker_reported_basis", None)
        if old_basis is None or abs(new_basis - float(old_basis or 0)) > max(1.0, 0.001 * new_basis) \
                or old_src != new_src:
            mv = float(x.get("market_value") or 0)
            x["cost_basis"] = new_basis
            x["cost_basis_source"] = new_src
            x["basis_partial"] = False
            # `gain_loss` is the canonical, continuously-recomputed P&L (this basis, kept
            # current by repricing elsewhere, against live market_value) — deliberately
            # distinct from holdings.json's `unrealized_pl`, which is Schwab's own raw
            # figure frozen at the last basis-sync timestamp (see schwab_adapter.py's
            # get_positions for why the two aren't meant to agree; audit finding M8).
            x["gain_loss"] = round(mv - new_basis, 2)
            x["gain_loss_pct"] = round((mv - new_basis) / new_basis * 100, 4) if new_basis else None
            changes.append((ak, sym, old_src, f"{float(old_basis or 0):,.0f}", new_src, f"{new_basis:,.0f}"))

    print(f"\nBASIS SYNC — {len(changes)} rows change ({'APPLY' if a.apply else 'DRY-RUN'}):")
    for c in changes:
        print(f"  {c[0]:22} {c[1]:8} {c[2] or '—':28} ${c[3]:>10} -> {c[4]:10} ${c[5]:>10}")
    if a.apply and changes:
        from schwab_position_sync import protected_holdings_write
        r = protected_holdings_write(h, source="broker_basis_sync", protect_basis=False)
        print("write:", r)
        sys.exit(0 if r.get("wrote") else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""sync_basis_from_broker.py — single-source-of-truth basis sync (operator decision 2026-06-12).

Found via audit_position_basis.py: 8 Schwab positions carried phantom basis (SCHD $4.02 vs broker
$31.04 → +$111K fake gain, etc.) because holdings.json basis came from stale CSV-window
reconstruction. New hierarchy, applied here:

  1. schwab_cost_basis_lots (Positions/Gain-Loss export — true TAX LOTS) when qty matches ±1%
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
        if new_basis is None:
            continue
        if old_basis is None or abs(new_basis - float(old_basis or 0)) > max(1.0, 0.001 * new_basis) \
                or old_src != new_src:
            mv = float(x.get("market_value") or 0)
            x["cost_basis"] = new_basis
            x["cost_basis_source"] = new_src
            x["basis_partial"] = False
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

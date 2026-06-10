#!/usr/bin/env python3
"""schwab_journal_builder.py — turn the granular Schwab ledger (trade_transactions, API-sourced) into
journal round-trips for the real accounts.

  • 5-MINUTE AGGREGATION: same-side fills ≤5 min apart collapse into one leg (a scaling event); a longer
    gap starts a separate leg/trade.
  • FIFO pairing: buy-legs matched to sell-legs by quantity → closed round-trips (entry → exit), with
    share-weighted prices, prorated fees, net P&L, hold time.
  • Classification (heuristic): intraday round-trip ≤ scalp/day window → 'day_trade'; held overnight → 'swing'.
  • Writes schwab_round_trips (idempotent on dedupe_key). Read-only of the ledger; no Schwab calls.

  python3 scripts/schwab_journal_builder.py [--apply] [--gap-min 5]
"""
from __future__ import annotations
import argparse, collections, datetime, json, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

DDL = """
CREATE TABLE IF NOT EXISTS schwab_round_trips (
    id BIGSERIAL PRIMARY KEY,
    account TEXT NOT NULL, symbol TEXT NOT NULL,
    entry_time TIMESTAMPTZ, exit_time TIMESTAMPTZ, hold_minutes INT,
    qty NUMERIC, entry_price NUMERIC, exit_price NUMERIC,
    gross_pnl NUMERIC, fees NUMERIC, net_pnl NUMERIC, pnl_pct NUMERIC,
    classification TEXT, dedupe_key TEXT UNIQUE, created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_srt_acct ON schwab_round_trips (account, symbol, exit_time);
"""


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _group_legs(fills, gap_min=5):
    """Collapse same-side fills ≤gap_min apart into one leg (the 5-minute scaling rule)."""
    legs, cur = [], None
    for f in sorted(fills, key=lambda r: r["t"]):
        if cur and cur["side"] == f["side"] and (f["t"] - cur["last"]).total_seconds() <= gap_min * 60:
            cur["qty"] += f["qty"]; cur["cost"] += f["qty"] * f["price"]; cur["fees"] += f["fees"]; cur["last"] = f["t"]
        else:
            if cur:
                legs.append(cur)
            cur = {"side": f["side"], "qty": f["qty"], "cost": f["qty"] * f["price"], "fees": f["fees"],
                   "t": f["t"], "last": f["t"]}
    if cur:
        legs.append(cur)
    for l in legs:
        l["price"] = l["cost"] / l["qty"] if l["qty"] else 0
    return legs


def _round_trips(account, symbol, legs):
    """FIFO-match buy-legs to sell-legs → closed round-trips."""
    buys = collections.deque()
    trips = []
    for leg in legs:
        if leg["side"] == "Buy":
            buys.append(dict(qty=leg["qty"], price=leg["price"], fees=leg["fees"], t=leg["t"]))
        else:
            sq, sp, sf, st = leg["qty"], leg["price"], leg["fees"], leg["t"]
            sell_qty0 = sq or 1
            while sq > 1e-9 and buys:
                b = buys[0]
                m = min(sq, b["qty"])
                gross = (sp - b["price"]) * m
                fees = round(b["fees"] * (m / (b["qty"] or 1)) + sf * (m / sell_qty0), 2)
                hold = int((st - b["t"]).total_seconds() / 60)
                same_day = st.date() == b["t"].date()
                cls = "day_trade" if (same_day and hold <= 390) else "swing"
                net = round(gross - fees, 2)
                trips.append({"account": account, "symbol": symbol, "entry_time": b["t"], "exit_time": st,
                              "hold_minutes": hold, "qty": round(m, 3), "entry_price": round(b["price"], 4),
                              "exit_price": round(sp, 4), "gross_pnl": round(gross, 2), "fees": fees,
                              "net_pnl": net, "pnl_pct": round((sp - b["price"]) / b["price"] * 100, 2) if b["price"] else 0,
                              "classification": cls,
                              "dedupe_key": f"{account}|{symbol}|{b['t'].isoformat()}|{st.isoformat()}|{round(m,3)}"})
                b["qty"] -= m; sq -= m
                if b["qty"] <= 1e-9:
                    buys.popleft()
    return trips


def run(apply=False, gap_min=5):
    conn = _conn(); cur = conn.cursor()
    cur.execute(DDL); conn.commit()
    cur.execute("""SELECT account, symbol, action, quantity, price, amount, fees, trade_time
                   FROM trade_transactions
                   WHERE import_source='schwab_api' AND action IN ('Buy','Sell') AND trade_time IS NOT NULL
                   ORDER BY account, symbol, trade_time""")
    bykey = collections.defaultdict(list)
    for acct, sym, action, qty, price, amount, fees, tt in cur.fetchall():
        px = float(price) if price and float(price) > 0 else (abs(float(amount) / float(qty)) if qty else 0)
        bykey[(acct, sym)].append({"side": action, "qty": float(qty or 0), "price": px,
                                   "fees": float(fees or 0), "t": tt})
    all_trips = []
    for (acct, sym), fills in bykey.items():
        all_trips.extend(_round_trips(acct, sym, _group_legs(fills, gap_min)))
    ins = 0
    if apply:
        for tp in all_trips:
            cur.execute("""INSERT INTO schwab_round_trips
                             (account,symbol,entry_time,exit_time,hold_minutes,qty,entry_price,exit_price,
                              gross_pnl,fees,net_pnl,pnl_pct,classification,dedupe_key)
                           VALUES (%(account)s,%(symbol)s,%(entry_time)s,%(exit_time)s,%(hold_minutes)s,%(qty)s,
                              %(entry_price)s,%(exit_price)s,%(gross_pnl)s,%(fees)s,%(net_pnl)s,%(pnl_pct)s,
                              %(classification)s,%(dedupe_key)s)
                           ON CONFLICT (dedupe_key) DO UPDATE SET net_pnl=EXCLUDED.net_pnl, fees=EXCLUDED.fees""", tp)
            ins += 1
        conn.commit()
    wins = sum(1 for t in all_trips if t["net_pnl"] > 0)
    report = {"mode": "APPLIED" if apply else "DRY-RUN", "round_trips": len(all_trips),
              "wins": wins, "losses": len(all_trips) - wins,
              "win_rate": round(wins / len(all_trips) * 100, 1) if all_trips else 0,
              "net_pnl": round(sum(t["net_pnl"] for t in all_trips), 2),
              "by_class": dict(collections.Counter(t["classification"] for t in all_trips)),
              "by_account": dict(collections.Counter(t["account"] for t in all_trips)), "inserted": ins}
    print(json.dumps(report, indent=2, default=str))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--gap-min", type=int, default=5)
    a = ap.parse_args()
    run(apply=a.apply, gap_min=a.gap_min)


if __name__ == "__main__":
    main()

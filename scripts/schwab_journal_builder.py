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
    classification TEXT, dedupe_key TEXT UNIQUE, created_at TIMESTAMPTZ DEFAULT NOW(),
    canary BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_srt_acct ON schwab_round_trips (account, symbol, exit_time);
"""


def _canary_symbols() -> set:
    """Stage 2a: symbols in the committed hardcoded canary allowlist (brokers/canary_gate.py). Trips on
    these symbols are tagged canary=true at ingest and EXCLUDED from all stats/journal/strategy data.
    The tag is sticky on upsert — once canary, always canary, even after the allowlist rotates."""
    try:
        from brokers.canary_gate import CANARY_SYMBOL_ALLOWLIST
        return {s.upper() for s in CANARY_SYMBOL_ALLOWLIST}
    except Exception:
        return set()


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _group_legs(fills, gap_min=5):
    """Collapse same-side fills ≤gap_min apart into one leg (the 5-minute scaling rule). Carries pre_window
    (opening lot predates the API window) + source through the grouping."""
    legs, cur = [], None
    for f in sorted(fills, key=lambda r: r["t"]):
        if cur and cur["side"] == f["side"] and (f["t"] - cur["last"]).total_seconds() <= gap_min * 60:
            cur["qty"] += f["qty"]; cur["cost"] += f["qty"] * f["price"]; cur["fees"] += f["fees"]; cur["last"] = f["t"]
            cur["pre_window"] = cur["pre_window"] or f.get("pre_window", False)
        else:
            if cur:
                legs.append(cur)
            cur = {"side": f["side"], "qty": f["qty"], "cost": f["qty"] * f["price"], "fees": f["fees"],
                   "t": f["t"], "last": f["t"], "pre_window": f.get("pre_window", False), "source": f.get("source", "api")}
    if cur:
        legs.append(cur)
    for l in legs:
        l["price"] = l["cost"] / l["qty"] if l["qty"] else 0
    return legs


def _round_trips(account, symbol, legs):
    """FIFO-match buy-legs to sell-legs → closed round-trips. A buy leg whose lot predates the API window
    (CSV opening lot or operator-basis injection) flags the trip as a long_term_trim (real long-term P&L,
    excluded from active trading stats). A sell with NO matching lot is flagged basis_unknown — NEVER a
    fabricated loss (entry/P&L null)."""
    buys = collections.deque()
    trips = []
    for leg in legs:
        if leg["side"] == "Buy":
            buys.append(dict(qty=leg["qty"], price=leg["price"], fees=leg["fees"], t=leg["t"],
                             pre=leg.get("pre_window", False), src=leg.get("source", "api")))
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
                if b["pre"]:
                    cls, bstat = "long_term_trim", "long_term_trim"
                else:
                    cls, bstat = ("day_trade" if (same_day and hold <= 390) else "swing"), None
                net = round(gross - fees, 2)
                trips.append({"account": account, "symbol": symbol, "entry_time": b["t"], "exit_time": st,
                              "hold_minutes": hold, "qty": round(m, 3), "entry_price": round(b["price"], 4),
                              "exit_price": round(sp, 4), "gross_pnl": round(gross, 2), "fees": fees,
                              "net_pnl": net, "pnl_pct": round((sp - b["price"]) / b["price"] * 100, 2) if b["price"] else 0,
                              "classification": cls, "basis_status": bstat, "basis_source": b["src"],
                              "dedupe_key": f"{account}|{symbol}|{b['t'].isoformat()}|{st.isoformat()}|{round(m,3)}"})
                b["qty"] -= m; sq -= m
                if b["qty"] <= 1e-9:
                    buys.popleft()
            if sq > 1e-9:  # FIFO UNDERFLOW: sold with no opening lot anywhere — flag, never fabricate a loss
                trips.append({"account": account, "symbol": symbol, "entry_time": None, "exit_time": st,
                              "hold_minutes": None, "qty": round(sq, 3), "entry_price": None,
                              "exit_price": round(sp, 4), "gross_pnl": None, "fees": round(sf, 2),
                              "net_pnl": None, "pnl_pct": None, "classification": "pre_window_trim",
                              "basis_status": "basis_unknown", "basis_source": None,
                              "dedupe_key": f"{account}|{symbol}|UNKNOWN|{st.isoformat()}|{round(sq,3)}"})
    return trips


def _load_overrides():
    try:
        import yaml
        c = yaml.safe_load((PROJECT_ROOT / "config" / "journal_basis_overrides.yaml").read_text())
        return (c or {}).get("overrides", {}) or {}
    except Exception:
        return {}


def run(apply=False, gap_min=5):
    import datetime as _dt
    conn = _conn(); cur = conn.cursor()
    cur.execute(DDL); conn.commit()
    overrides = _load_overrides()
    # API both sides (in-window) + CSV BUYS only (pre-window opening lots; never CSV sells — those are the
    # lossy collapsed rows we already replaced). CSV rows carry trade_date, not trade_time.
    cur.execute("""SELECT account, symbol, action, quantity, price, amount, fees, trade_time, trade_date,
                     (import_source='schwab_api') AS inwin
                   FROM trade_transactions
                   WHERE action IN ('Buy','Sell')
                     AND (import_source='schwab_api' OR action='Buy')
                   ORDER BY account, symbol""")
    bykey = collections.defaultdict(list)
    for acct, sym, action, qty, price, amount, fees, tt, td, inwin in cur.fetchall():
        px = float(price) if price and float(price) > 0 else (abs(float(amount) / float(qty)) if qty else 0)
        t = tt or _dt.datetime.combine(td, _dt.time(), tzinfo=_dt.timezone.utc)
        bykey[(acct, sym)].append({"side": action, "qty": float(qty or 0), "price": px, "fees": float(fees or 0),
                                   "t": t, "pre_window": (not inwin), "source": ("api" if inwin else "csv")})
    # inject operator-documented basis as a pre-window opening lot for any net-underflow override symbol
    for (acct, sym), fills in bykey.items():
        ov = overrides.get(f"{sym}|{acct}")
        if ov is None:
            continue
        # override may be a bare float (basis) or {basis, documented_qty}. documented_qty CAPS how many
        # pre-window shares get the operator basis; sells beyond it underflow FIFO -> basis_unknown (their
        # true basis needs Schwab's authoritative Gain/Loss export, never an extended hand override).
        ov_basis = float(ov["basis"]) if isinstance(ov, dict) else float(ov)
        doc_qty = ov.get("documented_qty") if isinstance(ov, dict) else None
        net = sum(f["qty"] for f in fills if f["side"] == "Buy") - sum(f["qty"] for f in fills if f["side"] == "Sell")
        if net < -0.01:
            inject = min(abs(net), float(doc_qty)) if doc_qty else abs(net)
            fills.append({"side": "Buy", "qty": inject, "price": ov_basis, "fees": 0.0,
                          "t": _dt.datetime(2008, 1, 1, tzinfo=_dt.timezone.utc), "pre_window": True, "source": "operator"})
    all_trips = []
    canary_syms = _canary_symbols()
    for (acct, sym), fills in bykey.items():
        for tp in _round_trips(acct, sym, _group_legs(fills, gap_min)):
            tp["canary"] = sym.upper() in canary_syms
            all_trips.append(tp)
    ins = 0
    if apply:
        for tp in all_trips:
            cur.execute("""INSERT INTO schwab_round_trips
                             (account,symbol,entry_time,exit_time,hold_minutes,qty,entry_price,exit_price,
                              gross_pnl,fees,net_pnl,pnl_pct,classification,basis_status,basis_source,dedupe_key,canary)
                           VALUES (%(account)s,%(symbol)s,%(entry_time)s,%(exit_time)s,%(hold_minutes)s,%(qty)s,
                              %(entry_price)s,%(exit_price)s,%(gross_pnl)s,%(fees)s,%(net_pnl)s,%(pnl_pct)s,
                              %(classification)s,%(basis_status)s,%(basis_source)s,%(dedupe_key)s,%(canary)s)
                           ON CONFLICT (dedupe_key) DO UPDATE SET net_pnl=EXCLUDED.net_pnl, fees=EXCLUDED.fees,
                             basis_status=EXCLUDED.basis_status, basis_source=EXCLUDED.basis_source,
                             canary=(schwab_round_trips.canary OR EXCLUDED.canary)""", tp)
            ins += 1
        # purge orphans: rows whose dedupe_key is no longer produced this run (e.g. a trip's classification
        # flipped long_term_trim -> basis_unknown when an override was capped, changing its dedupe_key).
        keys = tuple(tp["dedupe_key"] for tp in all_trips) or ("",)
        cur.execute("DELETE FROM schwab_round_trips WHERE dedupe_key NOT IN %s", (keys,))
        # ── CONSOLIDATION: schwab_round_trips is the single Schwab source of truth. Refresh trade_closed
        # (the /api/v2/journal "Trades" tab Schwab source) from it so the journal shows correct + current
        # data — fixes the stale/wrong V and the missing recent trades. basis_unknown excluded (no P&L).
        cur.execute("DELETE FROM trade_closed WHERE account LIKE 'schwab%'")
        cur.execute("""INSERT INTO trade_closed
                         (symbol, account, open_date, close_date, trade_type, shares, buy_price, sell_price,
                          cost_basis, proceeds, pnl, pnl_pct, hold_days, strategy_id, dedupe_key, created_at)
                       SELECT symbol, account, entry_time::date, exit_time::date, classification, qty,
                         entry_price, exit_price, round(entry_price*qty, 2), round(exit_price*qty, 2),
                         net_pnl, pnl_pct, round(hold_minutes/1440.0)::int, strategy_tag, 'srt:'||id, NOW()
                       FROM schwab_round_trips
                       WHERE basis_status IS DISTINCT FROM 'basis_unknown' AND entry_time IS NOT NULL
                         AND canary IS NOT TRUE
                       ON CONFLICT (dedupe_key) DO UPDATE SET pnl=EXCLUDED.pnl, close_date=EXCLUDED.close_date""")
        ins_tc = cur.rowcount
        conn.commit()
    # ACTIVE trading stats exclude long-term trims + basis_unknown + canary test orders (Stage 2a)
    active = [t for t in all_trips if t["basis_status"] is None and not t.get("canary")]
    awins = sum(1 for t in active if (t["net_pnl"] or 0) > 0)
    lt = [t for t in all_trips if t["basis_status"] == "long_term_trim"]
    unk = [t for t in all_trips if t["basis_status"] == "basis_unknown"]
    report = {"mode": "APPLIED" if apply else "DRY-RUN", "total_rows": len(all_trips),
              "canary_rows": sum(1 for t in all_trips if t.get("canary")),
              "active_round_trips": len(active), "active_win_rate": round(awins / len(active) * 100, 1) if active else 0,
              "active_net_pnl": round(sum(t["net_pnl"] or 0 for t in active), 2),
              "long_term_trims": len(lt), "long_term_realized": round(sum(t["net_pnl"] or 0 for t in lt), 2),
              "basis_unknown": len(unk), "basis_unknown_symbols": sorted(set(t["symbol"] for t in unk)),
              "inserted": ins}
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

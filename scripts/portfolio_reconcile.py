#!/usr/bin/env python3
"""Portfolio reconciliation: Command Center vs broker, open AND closed positions (read-only).

Operator 2026-10-05: "This discrepancy is real, and we need to validate that everything in the command
center and the portfolio is correct … do the same thing for every current holding, everything that it has
sold. I need this to be the source of truth." (CC showed SPCX $136.46 / -$8,272 while Schwab had $171.09 /
+$2,122.)

Broker truth used here (no new broker calls — the sanctioned read paths already record it):
  * open Schwab positions  -> schwab_positions_live, latest snapshot (written by the read-only position sync)
  * Schwab buys/sells      -> trade_transactions where import_source='schwab_api' (broker transaction ledger)
  * price                  -> the Command Center data broker quote (GET /api/v2/schwab/quotes → market_quotes)
Command Center surfaces compared:
  * GET /api/v2/portfolio/holdings (Portfolio table, symbol card KPIs) and holdings.json raw fields
  * trade_closed (REALIZED / TRADING KPIs, journal, per-symbol P&L)
Accounts without a broker read path (Fidelity manual/SnapTrade, moomoo, Alpaca) are labelled, not guessed.

  portfolio_reconcile.py                      # print summary
  portfolio_reconcile.py --json out.json --md out.md
Read-only: SELECTs in a READ ONLY transaction and HTTP GETs to the local Command Center API.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

CC_BASE = "http://127.0.0.1:7777"
def _state_dir() -> Path:
    from lib import portfolio_positions as _pp  # type: ignore
    return _pp.store_path().parent
PRICE_TOL_PCT = 1.0        # CC price vs data-broker quote
VALUE_TOL_USD = 1.0        # value / P&L arithmetic
QTY_TOL = 1e-3
DUST_USD = 50.0          # the holdings API hides non-cash rows under this value
BASIS_TOL_USD = 1.0
SCHWAB_ACCTS = {"schwab_rollover_ira": "schwab_rollover_ira", "schwab_roth": "schwab_roth_ira",
                "schwab_roth_ira": "schwab_roth_ira", "schwab_taxable": "schwab_taxable"}
TEST_ACCOUNTS = {"health", "journal_check"}
UNVERIFIABLE_ACCOUNT_NOTE = {
    "fidelity_rollover_ira": "Fidelity: no broker API (SnapTrade activity + manual entry) — not verifiable here",
    "moomoo_taxable_live": "moomoo: read-only sync only; no position ledger table to compare",
    "alpaca_taxable": "Alpaca: read-only data account",
}
ACQUIRE = {"Buy"}
# Outflows the Schwab ingest labels by direction since 2026-10-06 (before, every transfer read as an inflow).
DISPOSE_NO_PROCEEDS = {"Transfer Out", "Security Transfer Out", "Journaled Shares Out"}
ACQUIRE_UNKNOWN_BASIS = {"Transfer In", "Security Transfer", "Journaled Shares", "Reinvest Shares",
                         "Reinvested Dividend", "Journal"}


def _f(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


# ── open positions ────────────────────────────────────────────────────────────

def reconcile_positions(broker: Iterable[dict], cc: Iterable[dict], quotes: dict,
                        raw: Optional[dict] = None) -> list[dict]:
    """One row per (account, symbol) with broker vs CC vs quote and every mismatch named.

    broker rows: {account, symbol, qty, avg_price, market_value, unrealized_pl, captured_at}
    cc rows:     /api/v2/portfolio/holdings rows (shares, price, price_source, market_value, cost_basis)
    quotes:      {SYMBOL: {"last": float, "as_of": str}}  — the data broker's price
    raw:         {(account, SYMBOL): holdings.json row} — to name the stored field a wrong number came from
    """
    raw = raw or {}
    b_by = {(r["account"], r["symbol"].upper()): r for r in broker}
    c_by: dict = {}
    for r in cc:
        acct = SCHWAB_ACCTS.get(r.get("account") or "", r.get("account") or "")
        c_by[(acct, (r.get("symbol") or "").upper())] = r
    out = []
    for key in sorted(set(b_by) | set(c_by)):
        acct, sym = key
        b, c = b_by.get(key), c_by.get(key)
        q = quotes.get(sym) or {}
        qpx = _f(q.get("last"))
        row: dict[str, Any] = {"account": acct, "symbol": sym, "issues": []}
        if b:
            bq, bmv, bavg = _f(b["qty"]) or 0.0, _f(b["market_value"]) or 0.0, _f(b["avg_price"]) or 0.0
            row["broker"] = {"qty": bq, "avg_price": round(bavg, 6), "cost": round(bq * bavg, 2),
                             "market_value": round(bmv, 2), "price_at_snapshot": round(bmv / bq, 4) if bq else None,
                             "unrealized_pl": round(_f(b.get("unrealized_pl")) or 0.0, 2),
                             "captured_at": str(b.get("captured_at"))}
        if c:
            row["cc"] = {"shares": _f(c.get("shares")), "price": _f(c.get("price")),
                         "price_source": c.get("price_source"), "price_as_of": c.get("price_as_of"),
                         "market_value": _f(c.get("market_value")), "cost_basis": _f(c.get("cost_basis")),
                         "gain_loss": _f(c.get("gain_loss"))}
        rr = raw.get(key) or raw.get((c.get("account") if c else acct, sym)) or {}
        if (c and (c.get("is_cash") or sym == "CASH")) or (rr and rr.get("is_cash")):
            row["cash"] = True
            row["cc"] = {"shares": _f(c.get("shares")) if c else None, "market_value": _f(c.get("market_value")) if c else None}
            row["verifiable"] = "cash balance — no broker balance snapshot in the read paths; not compared"
            out.append(row)
            continue
        if rr:
            row["stored"] = {k: rr.get(k) for k in ("price", "current_price", "canonical_mark", "market_value",
                                                    "cost_basis", "gain_loss", "unrealized_pl",
                                                    "analytical_unrealized_pl_usd")}
        if qpx:
            row["quote"] = {"last": qpx, "as_of": q.get("as_of"), "source": q.get("source")}
        # ── checks ──
        if b and not c:
            bmv = row["broker"]["market_value"]
            stored_mv = _f(rr.get("market_value")) if rr else None
            if not sym.isalpha():
                row["note"] = "delisted CUSIP position (broker value $%s) — not shown in CC by design" % format(bmv, ",.2f")
            elif rr and (stored_mv or 0) < DUST_USD:
                row["note"] = f"dust (<${DUST_USD:g}) — in holdings.json, hidden from the CC table by design"
            else:
                row["issues"].append("MISSING_IN_CC: broker holds it, Command Center does not show it")
        if c and not b and acct in SCHWAB_ACCTS.values():
            row["issues"].append("PHANTOM_IN_CC: Command Center shows it, broker snapshot does not hold it")
        if c and acct not in SCHWAB_ACCTS.values():
            row["verifiable"] = UNVERIFIABLE_ACCOUNT_NOTE.get(acct, "no broker read path for this account")
        if b and c:
            bq, cq = row["broker"]["qty"], row["cc"]["shares"] or 0.0
            if abs(bq - cq) > QTY_TOL:
                row["issues"].append(f"QTY: CC {cq} vs broker {bq}")
            ccb, bcb = row["cc"]["cost_basis"], row["broker"]["cost"]
            if ccb is not None and abs(ccb - bcb) > max(BASIS_TOL_USD, 0.001 * bcb):
                row["issues"].append(f"COST: CC ${ccb:,.2f} vs broker ${bcb:,.2f} (Δ ${ccb - bcb:,.2f})")
        if c:
            cpx, cmv, csh = row["cc"]["price"], row["cc"]["market_value"], row["cc"]["shares"] or 0.0
            if qpx and cpx and abs(cpx - qpx) / qpx * 100 > PRICE_TOL_PCT:
                src = ""
                if rr and _f(rr.get("current_price")) and abs((_f(rr.get("current_price")) or 0) - cpx) < 0.005:
                    src = " — came from stored holdings.json `current_price` (never refreshed)"
                row["issues"].append(f"PRICE: CC ${cpx:,.2f} ({row['cc']['price_source']}) vs data-broker "
                                     f"quote ${qpx:,.2f} ({(cpx / qpx - 1) * 100:+.1f}%){src}")
            if qpx and csh and cmv is not None:
                fair = csh * qpx
                if abs(cmv - fair) > max(VALUE_TOL_USD, 0.01 * fair):
                    row["issues"].append(f"VALUE: CC ${cmv:,.2f} vs shares×quote ${fair:,.2f} (Δ ${cmv - fair:,.2f})")
                row["value_at_quote"] = round(fair, 2)
                cb = row["cc"]["cost_basis"]
                if cb is not None:
                    row["pl_at_quote"] = round(fair - cb, 2)
        out.append(row)
    return out


# ── closed positions ──────────────────────────────────────────────────────────

def fifo_sell_basis(txns: Iterable[dict]) -> dict:
    """Replay one account's broker ledger FIFO. Returns {(symbol, date, txn_key): (cost or None, detail)}.
    A sell that consumes any lot whose basis the ledger does not carry (transfers, journals,
    reinvestments, pre-ledger shares) gets cost None — unverifiable, never guessed."""
    lots: dict[str, list] = defaultdict(list)
    out: dict = {}
    for t in sorted(txns, key=lambda t: (str(t["trade_date"]), str(t.get("trade_time") or ""), t["action"] != "Buy")):
        sym, act, q = t["symbol"], t["action"], abs(_f(t["quantity"]) or 0.0)
        if not q:
            continue
        if act in ACQUIRE:
            lots[sym].append([q, _f(t["price"])])
        elif act in ACQUIRE_UNKNOWN_BASIS:
            lots[sym].append([q, None])
        elif act in DISPOSE_NO_PROCEEDS:
            # Shares left by transfer/journal: they close lots FIFO but are not a sale (no REALIZED row).
            need = q
            while need > 1e-9 and lots[sym]:
                take = min(need, lots[sym][0][0])
                lots[sym][0][0] -= take
                need -= take
                if lots[sym][0][0] <= 1e-9:
                    lots[sym].pop(0)
        elif act == "Sell":
            need, cost, known = q, 0.0, True
            while need > 1e-9 and lots[sym]:
                lot = lots[sym][0]
                take = min(need, lot[0])
                if lot[1] is None:
                    known = False
                else:
                    cost += take * lot[1]
                lot[0] -= take
                need -= take
                if lot[0] <= 1e-9:
                    lots[sym].pop(0)
            if need > 1e-6:
                known = False   # sold more than the ledger shows acquired → pre-ledger shares
            out[(sym, str(t["trade_date"]), t.get("dedupe_key"))] = (round(cost, 2) if known else None, need)
    return out


def _near(d1: str, d2: str, days: int = 1) -> bool:
    from datetime import date as _d
    try:
        return abs((_d.fromisoformat(d1) - _d.fromisoformat(d2)).days) <= days
    except ValueError:
        return d1 == d2


def reconcile_closed(sells: Iterable[dict], closed: Iterable[dict], all_txns: Iterable[dict],
                     excluded: Optional[Iterable[dict]] = None) -> dict:
    """Every broker sell must have closed record(s) with the same qty and net proceeds; every closed
    record must come from a broker sell. Grouped by (account, symbol, date) because one sell can close
    several lots and the builder may split rows."""
    sells, closed = list(sells), list(closed)
    s_g: dict = defaultdict(lambda: {"qty": 0.0, "net": 0.0, "fees": 0.0, "n": 0, "keys": []})
    for s in sells:
        k = (s["account"], s["symbol"], str(s["trade_date"]))
        g = s_g[k]
        g["qty"] += abs(_f(s["quantity"]) or 0)
        g["net"] += _f(s["amount"]) or 0
        g["fees"] += _f(s.get("fees")) or 0
        g["n"] += 1
        g["keys"].append(s.get("dedupe_key"))
    c_g: dict = defaultdict(lambda: {"qty": 0.0, "proceeds": 0.0, "cost": 0.0, "pnl": 0.0, "n": 0, "ids": []})
    test_rows, dup_keys = [], defaultdict(int)
    for c in closed:
        if c["account"] in TEST_ACCOUNTS:
            test_rows.append(c)
            continue
        dup_keys[c.get("dedupe_key")] += 1
        k = (c["account"], c["symbol"], str(c["close_date"]))
        g = c_g[k]
        g["qty"] += _f(c["shares"]) or 0
        g["proceeds"] += _f(c.get("proceeds")) or 0
        g["cost"] += _f(c.get("cost_basis")) or 0
        g["pnl"] += _f(c.get("pnl")) or 0
        g["n"] += 1
        g["ids"].append(c.get("id"))
    # FIFO basis per account from the broker ledger
    by_acct: dict = defaultdict(list)
    for t in all_txns:
        by_acct[t["account"]].append(t)
    fifo: dict = {}
    for acct, ts in by_acct.items():
        for (sym, d, key), v in fifo_sell_basis(ts).items():
            fifo[(acct, sym, d, key)] = v
    # sells the builder deliberately left out (basis unknown) — {account, symbol, date, qty, proceeds}
    exc_by: dict = defaultdict(list)
    for e in excluded or []:
        exc_by[(e["account"], e["symbol"])].append(e)
    rows = []
    for k in sorted(set(s_g) | set(c_g)):
        acct, sym, d = k
        s, c = s_g.get(k), c_g.get(k)
        r: dict[str, Any] = {"account": acct, "symbol": sym, "date": d, "issues": []}
        if s:
            r["broker"] = {"qty": round(s["qty"], 4), "net_proceeds": round(s["net"], 2), "fees": round(s["fees"], 2),
                           "sells": s["n"]}
            fc = [fifo.get((acct, sym, d, key)) for key in s["keys"]]
            if fc and all(x and x[0] is not None for x in fc):
                r["broker"]["fifo_cost"] = round(sum(x[0] for x in fc), 2)
                r["broker"]["fifo_pnl"] = round(s["net"] - r["broker"]["fifo_cost"], 2)
            else:
                r["basis_verifiable"] = False
        if c:
            r["cc"] = {"qty": round(c["qty"], 4), "proceeds": round(c["proceeds"], 2), "cost": round(c["cost"], 2),
                       "pnl": round(c["pnl"], 2), "records": c["n"], "ids": c["ids"]}
        exc = [e for e in exc_by.get((acct, sym), []) if _near(e["date"], d)] if s else []
        exc_qty = sum(e["qty"] for e in exc)
        if exc:
            r["excluded_basis_unknown"] = {"qty": round(exc_qty, 4),
                                           "proceeds": round(sum(e["proceeds"] for e in exc), 2)}
        if s and not c:
            if exc and abs(exc_qty - s["qty"]) <= QTY_TOL:
                r["note"] = "BASIS_UNKNOWN_EXCLUDED: whole sale left out of REALIZED (basis not in broker ledger)"
            else:
                r["issues"].append("MISSING_CLOSE: broker sell has no closed record")
        if c and not s:
            alt = [k2 for k2 in s_g if k2[0] == acct and k2[1] == sym and _near(k2[2], d)]
            if alt:
                r["issues"].append(f"DATE: closed on {d} but the broker trade date is {alt[0][2]} "
                                   "(order time used instead of trade date)")
            else:
                r["issues"].append("PHANTOM_CLOSE: closed record with no broker sell that day")
        if s and c:
            if abs(s["qty"] - (c["qty"] + exc_qty)) <= QTY_TOL and exc_qty > 0:
                r["note"] = (f"PARTIAL_BASIS_UNKNOWN: {exc_qty:g} of {s['qty']:g} sold shares left out of REALIZED "
                             "(basis not in broker ledger)")
            elif abs(s["qty"] - c["qty"]) > QTY_TOL:
                r["issues"].append(f"QTY: closed {c['qty']:g} vs sold {s['qty']:g}")
            implied_net = c["cost"] + c["pnl"]   # pnl is booked net of fees
            share = (c["qty"] / s["qty"]) if s["qty"] else 1.0   # compare only the closed part's proceeds
            if abs(implied_net - s["net"] * share) > max(BASIS_TOL_USD, 0.0005 * abs(s["net"])):
                r["issues"].append(f"PROCEEDS: closed cost+pnl ${implied_net:,.2f} vs broker net "
                                   f"${s['net'] * share:,.2f} for the {c['qty']:g} closed shares")
            fcost = r["broker"].get("fifo_cost")
            if fcost is not None and not exc and abs(fcost - c["cost"]) > max(BASIS_TOL_USD, 0.001 * fcost):
                r["issues"].append(f"BASIS: closed cost ${c['cost']:,.2f} vs FIFO from broker buys ${fcost:,.2f} "
                                   f"(P&L Δ ${c['pnl'] - r['broker']['fifo_pnl']:,.2f})")
        rows.append(r)
    return {"rows": rows, "test_rows": test_rows,
            "duplicate_dedupe_keys": {k: v for k, v in dup_keys.items() if v > 1 and k}}


# ── loaders (read-only) ───────────────────────────────────────────────────────

def _get(path: str):
    with urllib.request.urlopen(CC_BASE + path, timeout=60) as r:
        d = json.loads(r.read().decode())
    return d.get("data", d) if isinstance(d, dict) else d


def load_all(inprocess: bool = False) -> dict:
    from db_adapter import get_connection  # type: ignore
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cur.execute("SELECT max(captured_at) FROM schwab_positions_live")
    snap = cur.fetchone()[0]
    cur.execute("""SELECT account_key, symbol, qty, avg_price, market_value, unrealized_pl, captured_at
                   FROM schwab_positions_live WHERE captured_at = %s""", (snap,))
    broker = [{"account": r[0], "symbol": r[1], "qty": r[2], "avg_price": r[3], "market_value": r[4],
               "unrealized_pl": r[5], "captured_at": r[6]} for r in cur.fetchall()]
    cols = "trade_date, trade_time, account, symbol, action, quantity, price, amount, fees, dedupe_key, import_source"
    cur.execute(f"SELECT {cols} FROM trade_transactions WHERE symbol IS NOT NULL AND symbol <> '' ORDER BY trade_date")
    names = [c.strip() for c in cols.split(",")]
    txns = [dict(zip(names, r)) for r in cur.fetchall()]
    cur.execute("""SELECT account, symbol, (exit_time AT TIME ZONE 'America/New_York')::date, qty, qty*exit_price
                   FROM schwab_round_trips WHERE basis_status = 'basis_unknown' AND canary IS NOT TRUE""")
    excluded = [{"account": r[0], "symbol": r[1], "date": str(r[2]), "qty": float(r[3] or 0),
                 "proceeds": float(r[4] or 0)} for r in cur.fetchall()]
    cur.execute("""SELECT id, account, symbol, open_date, close_date, trade_type, shares, buy_price, sell_price,
                          cost_basis, proceeds, pnl, dedupe_key FROM trade_closed""")
    names = [d[0] for d in cur.description]
    closed = [dict(zip(names, r)) for r in cur.fetchall()]
    conn.rollback()
    conn.close()
    if inprocess:
        import api_v2 as _A  # type: ignore  # the code in THIS tree (e.g. a fix before it is deployed)
        _A.STATE_DIR = _state_dir()
        hold = _A.portfolio_holdings()
        hold = hold.get("data", hold) if isinstance(hold, dict) else hold
    else:
        hold = _get("/api/v2/portfolio/holdings")
    cc_rows = hold.get("holdings") if isinstance(hold, dict) else hold
    syms = sorted({(r.get("symbol") or "").upper() for r in cc_rows} | {b["symbol"].upper() for b in broker})
    quotes: dict = {}
    for i in range(0, len(syms), 40):
        q = _get("/api/v2/schwab/quotes?symbols=" + ",".join(syms[i:i + 40])) or {}
        quotes.update(q.get("quotes") or {})
    from lib import portfolio_positions as _pp  # type: ignore  # the one accessor for the position store
    raw_doc = _pp.load_store()
    raw = {}
    for r in raw_doc.get("holdings") or []:
        raw[(SCHWAB_ACCTS.get(r.get("account"), r.get("account")), (r.get("symbol") or "").upper())] = r
    return {"broker": broker, "snapshot_at": str(snap), "cc_rows": cc_rows, "quotes": quotes, "raw": raw,
            "raw_totals": raw_doc.get("portfolio_totals") or {}, "txns": txns, "closed": closed,
            "excluded": excluded}


def build_report(d: dict) -> dict:
    pos = reconcile_positions(d["broker"], d["cc_rows"], d["quotes"], d["raw"])
    sells = [t for t in d["txns"] if t["action"] == "Sell" and t["import_source"] == "schwab_api"]
    closed = [c for c in d["closed"] if c["account"] in SCHWAB_ACCTS.values() or c["account"] in TEST_ACCOUNTS]
    schwab_txns = [t for t in d["txns"] if t["account"] in SCHWAB_ACCTS.values()]
    cl = reconcile_closed(sells, closed, schwab_txns, d.get("excluded"))
    other_closed = [c for c in d["closed"] if c["account"] not in SCHWAB_ACCTS.values() and c["account"] not in TEST_ACCOUNTS]
    cc_total = sum(_f(r.get("market_value")) or 0 for r in d["cc_rows"])
    cc_schwab = sum(_f(r.get("market_value")) or 0 for r in d["cc_rows"] if (r.get("account") or "").startswith("schwab"))
    fair_schwab = sum(r.get("value_at_quote") or 0 for r in pos if r["account"] in SCHWAB_ACCTS.values() and r.get("cc"))
    broker_total = sum(_f(b["market_value"]) or 0 for b in d["broker"])
    cc_schwab_noncash = sum(_f(r.get("market_value")) or 0 for r in d["cc_rows"]
                            if (r.get("account") or "").startswith("schwab") and not r.get("is_cash")
                            and (r.get("symbol") or "").upper() != "CASH")
    real_closed = [c for c in d["closed"] if c["account"] not in TEST_ACCOUNTS]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "broker_snapshot_at": d["snapshot_at"],
        "positions": pos,
        "closed": cl,
        "closed_other_accounts": len(other_closed),
        "totals": {
            "cc_table_all_accounts": round(cc_total, 2),
            "cc_schwab_rows": round(cc_schwab, 2),
            "cc_schwab_noncash": round(cc_schwab_noncash, 2),
            "schwab_rows_at_data_broker_quote": round(fair_schwab, 2),
            "broker_snapshot_market_value": round(broker_total, 2),
            "holdings_json_portfolio_totals": d["raw_totals"],
            "realized_all_rows": round(sum(_f(c["pnl"]) or 0 for c in d["closed"]), 2),
            "realized_excluding_test_rows": round(sum(_f(c["pnl"]) or 0 for c in real_closed), 2),
            "closed_rows": len(d["closed"]), "closed_rows_real": len(real_closed),
            "excluded_basis_unknown_sells": len(d.get("excluded") or []),
            "excluded_basis_unknown_proceeds": round(sum(e["proceeds"] for e in d.get("excluded") or []), 2),
        },
    }


def render_markdown(rep: dict) -> str:
    L = ["# Portfolio reconciliation — Command Center vs broker",
         "", f"Generated {rep['generated_at']} · broker position snapshot {rep['broker_snapshot_at']} · "
         "read-only (`scripts/portfolio_reconcile.py`).", ""]
    pos = rep["positions"]
    bad = [p for p in pos if p["issues"]]
    L += ["## Open positions", "",
          f"{len(pos)} account×symbol rows · **{len(bad)} with a mismatch**.", "",
          "| Account | Symbol | Broker qty | Broker cost | CC price (source) | Quote | CC value | Value at quote | Δ value | Issues |",
          "|---|---|---:|---:|---|---:|---:|---:|---:|---|"]
    for p in pos:
        b, c, q = p.get("broker") or {}, p.get("cc") or {}, p.get("quote") or {}
        dv = (c.get("market_value") or 0) - (p.get("value_at_quote") or 0) if (c and p.get("value_at_quote")) else None
        L.append(f"| {p['account']} | {p['symbol']} | {b.get('qty', '—')} | "
                 f"{('$%s' % format(b['cost'], ',.2f')) if b else '—'} | "
                 f"{('$%s (%s)' % (format(c['price'], ',.2f'), c.get('price_source'))) if c.get('price') else '—'} | "
                 f"{('$%s' % format(q['last'], ',.2f')) if q else '—'} | "
                 f"{('$%s' % format(c['market_value'], ',.2f')) if c.get('market_value') is not None else '—'} | "
                 f"{('$%s' % format(p['value_at_quote'], ',.2f')) if p.get('value_at_quote') else '—'} | "
                 f"{('$%s' % format(dv, ',.2f')) if dv is not None else '—'} | "
                 f"{'; '.join(p['issues']) or p.get('note') or p.get('verifiable') or 'ok'} |")
    t = rep["totals"]
    L += ["", "### Totals", "",
          f"- CC Portfolio table, all accounts: **${t['cc_table_all_accounts']:,.2f}**",
          f"- CC Schwab rows incl. cash: ${t['cc_schwab_rows']:,.2f} · non-cash: **${t['cc_schwab_noncash']:,.2f}** · "
          f"same non-cash rows at the data-broker quote: **${t['schwab_rows_at_data_broker_quote']:,.2f}** "
          f"(Δ ${t['cc_schwab_noncash'] - t['schwab_rows_at_data_broker_quote']:,.2f})",
          f"- Broker snapshot market value (Schwab positions, {rep['broker_snapshot_at']}): ${t['broker_snapshot_market_value']:,.2f}",
          f"- holdings.json `portfolio_totals`: `{json.dumps({k: v for k, v in (t['holdings_json_portfolio_totals'] or {}).items() if not isinstance(v, (dict, list))})[:400]}`",
          ""]
    cl = rep["closed"]
    cbad = [r for r in cl["rows"] if r["issues"]]
    unver = [r for r in cl["rows"] if r.get("basis_verifiable") is False]
    L += ["## Closed positions (Schwab)", "",
          f"{len(cl['rows'])} account×symbol×day sell groups · **{len(cbad)} with a mismatch** · "
          f"{len(unver)} whose basis the broker ledger cannot verify (transferred / pre-ledger lots).", "",
          f"- Test rows in production `trade_closed`: {len(cl['test_rows'])} "
          f"({', '.join(str(r['account']) + '/' + str(r['symbol']) for r in cl['test_rows'])}) — counted in REALIZED today.",
          f"- Duplicate dedupe keys: {len(cl['duplicate_dedupe_keys'])}.",
          f"- Sells left out of REALIZED because their basis is not in the broker ledger: "
          f"**{t['excluded_basis_unknown_sells']}** (proceeds ${t['excluded_basis_unknown_proceeds']:,.2f}).",
          f"- REALIZED all rows ${t['realized_all_rows']:,.2f} ({t['closed_rows']} rows) · excluding test rows "
          f"${t['realized_excluding_test_rows']:,.2f} ({t['closed_rows_real']} rows).",
          f"- Closed rows on accounts without a broker ledger here (Fidelity etc.): {rep['closed_other_accounts']} — not verifiable.",
          "", "| Account | Symbol | Date | Sold qty | Broker net | FIFO cost | CC cost | CC P&L | FIFO P&L | Issues |",
          "|---|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for r in cl["rows"]:
        b, c = r.get("broker") or {}, r.get("cc") or {}
        if not r["issues"] and r.get("basis_verifiable") is not False and not r.get("note"):
            continue
        L.append(f"| {r['account']} | {r['symbol']} | {r['date']} | {b.get('qty', '—')} | "
                 f"{('$%s' % format(b['net_proceeds'], ',.2f')) if b else '—'} | "
                 f"{('$%s' % format(b['fifo_cost'], ',.2f')) if b.get('fifo_cost') is not None else 'unverifiable'} | "
                 f"{('$%s' % format(c['cost'], ',.2f')) if c else '—'} | {('$%s' % format(c['pnl'], ',.2f')) if c else '—'} | "
                 f"{('$%s' % format(b['fifo_pnl'], ',.2f')) if b.get('fifo_pnl') is not None else '—'} | "
                 f"{'; '.join(r['issues']) or r.get('note') or 'basis unverifiable from broker ledger'} |")
    L += ["", "_Rows with no issue and a verifiable basis are omitted from this table; the JSON carries all rows._", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("--inprocess", action="store_true",
                    help="price CC rows with this tree's api_v2.portfolio_holdings (verify a fix before deploy)")
    a = ap.parse_args(argv)
    rep = build_report(load_all(inprocess=a.inprocess))
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=1, default=str))
    md = render_markdown(rep)
    if a.md:
        Path(a.md).write_text(md)
    t = rep["totals"]
    print(json.dumps({"positions_with_issues": sum(1 for p in rep["positions"] if p["issues"]),
                      "positions": len(rep["positions"]),
                      "closed_groups_with_issues": sum(1 for r in rep["closed"]["rows"] if r["issues"]),
                      "closed_groups": len(rep["closed"]["rows"]), **{k: v for k, v in t.items() if not isinstance(v, dict)}},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

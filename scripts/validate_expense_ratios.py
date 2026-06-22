#!/usr/bin/env python3
"""Validate + correct fund/ETF expense ratios in symbol_profiles (operator 2026-06-21).

Bug it fixes: yfinance exposes the expense ratio in TWO different scales —
  • annualReportExpenseRatio  → a FRACTION  (FCNTX 0.0074 = 0.74%)
  • netExpenseRatio           → a PERCENT   (FCNTX 0.74   = 0.74%, SCHD 0.06 = 0.06%)
classify_instruments used a `while v>0.02: v/=100` heuristic that let stale/mis-scaled source values
through (FCNTX stored 1.47% vs the true 0.74%; AMANX stored NULL vs 0.59%). This validator uses a
DETERMINISTIC rule and cross-checks the two fields, updating symbol_profiles and logging every before→after.

Deterministic normalization (→ stored as a fraction):
  er = annualReportExpenseRatio (fraction, used as-is) ELSE netExpenseRatio/100.
  Cross-check: when BOTH exist, netExpenseRatio/100 should ≈ annualReportExpenseRatio (within 20%);
  disagreement is flagged. Sanity: 0 < er <= 0.025 (2.5%); anything outside is flagged, not written.

Read-only to the broker. Targets held fund/ETF symbols by default (or --symbols / --all-funds).
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = Path(HERE).parent
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SANITY_MAX = 0.025   # 2.5% — above this for an ETF/fund is almost certainly mis-scaled/bad data


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _held_fund_etf_symbols():
    try:
        h = json.loads((PROJ / "data" / "portfolios" / "state" / "holdings.json").read_text())
        rows = h.get("holdings") if isinstance(h, dict) else h
        syms = {(r.get("symbol") or "").upper() for r in rows if isinstance(r, dict) and r.get("symbol")}
    except Exception:
        syms = set()
    syms.discard("CASH"); syms.discard("")
    cur = _conn().cursor()
    cur.execute("SELECT upper(symbol) FROM symbol_profiles WHERE instrument_type IN ('fund','etf','mutual_fund') AND upper(symbol) = ANY(%s)",
                (sorted(syms),))
    return sorted({r[0] for r in cur.fetchall()})


def _authoritative_er(info: dict):
    """Return (er_fraction, confidence, detail). None er when unknown/insane."""
    ar = info.get("annualReportExpenseRatio")   # fraction
    net = info.get("netExpenseRatio")           # percent
    ar_f = float(ar) if isinstance(ar, (int, float)) and ar > 0 else None
    net_f = (float(net) / 100.0) if isinstance(net, (int, float)) and net > 0 else None
    if ar_f is not None and net_f is not None:
        agree = abs(ar_f - net_f) <= max(0.0002, 0.20 * max(ar_f, net_f))
        er = ar_f
        return (er, ("high" if agree else "low"),
                f"annualReport={ar_f:.4%} net={net_f:.4%} {'agree' if agree else 'DISAGREE'}")
    if ar_f is not None:
        return (ar_f, "medium", f"annualReportExpenseRatio={ar_f:.4%} (net absent)")
    if net_f is not None:
        return (net_f, "medium", f"netExpenseRatio={net_f:.4%} (annualReport absent)")
    return (None, "none", "no expense-ratio field on yfinance")


def run(symbols=None, apply=False):
    syms = symbols or _held_fund_etf_symbols()
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT upper(symbol), expense_ratio FROM symbol_profiles WHERE upper(symbol) = ANY(%s)", (syms,))
    before = {r[0]: (float(r[1]) if r[1] is not None else None) for r in cur.fetchall()}
    import yfinance as yf, time as _t
    changes, flags = [], []
    for s in syms:
        try:
            info = yf.Ticker(s).info or {}
        except Exception as e:
            flags.append({"symbol": s, "issue": f"yfinance error: {str(e)[:60]}"}); continue
        er, conf, detail = _authoritative_er(info)
        old = before.get(s)
        rec = {"symbol": s, "old_pct": (round(old * 100, 4) if old is not None else None),
               "new_pct": (round(er * 100, 4) if er is not None else None), "confidence": conf, "detail": detail}
        if er is None:
            flags.append({**rec, "issue": "no authoritative ratio — left unchanged"})
        elif er <= 0 or er > SANITY_MAX:
            flags.append({**rec, "issue": f"insane ({er:.4%} > {SANITY_MAX:.2%} cap) — NOT written"})
        else:
            changed = old is None or abs((old or 0) - er) > 1e-6
            rec["changed"] = changed
            if changed:
                changes.append(rec)
                if apply:
                    cur.execute("UPDATE symbol_profiles SET expense_ratio=%s WHERE upper(symbol)=%s", (round(er, 6), s))
            if conf == "low":
                flags.append({**rec, "issue": "two yfinance fields DISAGREE — verify"})
        _t.sleep(0.5)
    if apply:
        conn.commit()
    return {"ok": True, "applied": apply, "symbols": len(syms),
            "changed": changes, "flagged": flags,
            "note": "expense_ratio stored as a fraction; FRACTION field (annualReportExpenseRatio) preferred, "
                    "else percent/100; cross-checked; >2.5% rejected as mis-scaled."}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write corrections (else dry-run preview)")
    ap.add_argument("--symbols", help="comma-separated symbols (default: held funds/ETFs)")
    a = ap.parse_args()
    syms = [x.strip().upper() for x in a.symbols.split(",")] if a.symbols else None
    print(json.dumps(run(symbols=syms, apply=a.apply), indent=2, default=str))


if __name__ == "__main__":
    main()

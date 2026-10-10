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

Read-only to the broker. Targets held fund/ETF symbols by default (or --symbols).

Lane ``validate-expense-ratios`` (cron L550, ``--apply``). Three modes:
  * ``--dry-run`` (wins over ``--apply``): READ ONLY session, SELECTs only -- the target symbols and their
    stored expense_ratio; no yfinance request, no write, no receipt. Prints what an --apply run would check.
  * no ``--apply`` (the original preview, unchanged): READ ONLY session, fetches yfinance (free) and prints
    the would-be corrections; no write, no receipt.
  * ``--apply``: writes corrections and ``<state_root>/data/runtime/validate-expense-ratios_last.json``
    (LaneRunReceipt@v1; ``ok_at`` only on success).
Exit codes: 0 = ran (no change, flagged symbols, zero target symbols are findings); 1 = the run failed:
crash / DB unavailable (failed receipt on --apply, exception re-raised), or symbols existed and every
yfinance fetch raised (nothing could be fetched when work existed); 2 = usage error.
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

from lib.writers.symbol_profiles_writer import EXPENSE_RATIO_MAX, upsert_profile  # noqa: E402

SANITY_MAX = EXPENSE_RATIO_MAX   # 2.5% — above this for an ETF/fund is almost certainly mis-scaled/bad data
LANE_ID = "validate-expense-ratios"


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.validate_expense_ratios
        from scripts.lib import lane_last_receipt as lr
    return lr


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


def _stored_ratios(cur, syms):
    cur.execute("SELECT upper(symbol), expense_ratio FROM symbol_profiles WHERE upper(symbol) = ANY(%s)", (syms,))
    return {r[0]: (float(r[1]) if r[1] is not None else None) for r in cur.fetchall()}


def preview(symbols=None) -> dict:
    """--dry-run (AGENTS.md §6): READ ONLY session, SELECTs only; no yfinance, no upsert, no commit."""
    _receipt_lib().enforce_readonly(_conn())  # db_adapter's connection is thread-local: one session
    syms = symbols or _held_fund_etf_symbols()
    before = _stored_ratios(_conn().cursor(), syms)
    return {"symbols": len(syms),
            "stored_pct": {s: (round(before[s] * 100, 4) if before.get(s) is not None else None) for s in syms},
            "missing_ratio": sorted(s for s in syms if before.get(s) is None)}


def run(symbols=None, apply=False):
    if not apply:
        _receipt_lib().enforce_readonly(_conn())  # preview: the session cannot write
    syms = symbols or _held_fund_etf_symbols()
    conn = _conn(); cur = conn.cursor()
    before = _stored_ratios(cur, syms)
    import yfinance as yf, time as _t
    changes, flags = [], []
    fetch_errors = 0
    for s in syms:
        try:
            info = yf.Ticker(s).info or {}
        except Exception as e:
            fetch_errors += 1
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
                    rcpt = upsert_profile(cur, s, {"expense_ratio": round(er, 6)}, source="validate_expense_ratios")
                    if rcpt.rejected:
                        flags.append({**rec, "issue": f"write module refused: {rcpt.rejected[0]['reason']}"})
            if conf == "low":
                flags.append({**rec, "issue": "two yfinance fields DISAGREE — verify"})
        _t.sleep(0.5)
    if apply:
        conn.commit()
    return {"ok": True, "applied": apply, "symbols": len(syms), "fetch_errors": fetch_errors,
            "changed": changes, "flagged": flags,
            "note": "expense_ratio stored as a fraction; FRACTION field (annualReportExpenseRatio) preferred, "
                    "else percent/100; cross-checked; >2.5% rejected as mis-scaled."}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write corrections (else dry-run preview)")
    ap.add_argument("--dry-run", action="store_true",
                    help="SELECTs only (READ ONLY): no yfinance, no write, no receipt; wins over --apply")
    ap.add_argument("--symbols", help="comma-separated symbols (default: held funds/ETFs)")
    a = ap.parse_args(argv)
    syms = [x.strip().upper() for x in a.symbols.split(",")] if a.symbols else None
    lr = _receipt_lib()
    if a.dry_run:
        # Structural (AGENTS.md §6): run() -- yfinance, upsert_profile, commit -- is not reachable from here.
        plan = preview(syms)
        print(json.dumps(plan, indent=2, default=str))
        lr.dry_run_report(LANE_ID, {"symbols": plan["symbols"], "missing_ratio": len(plan["missing_ratio"]),
                                    "apply_requested": a.apply},
                          would_write=[f"symbol_profiles.expense_ratio (<= {plan['symbols']} rows, changed only)"])
        return 0
    if not a.apply:
        res = run(symbols=syms, apply=False)
        print(json.dumps(res, indent=2, default=str))
        return 1 if (res["symbols"] and res["fetch_errors"] >= res["symbols"]) else 0
    started = lr.now_iso()
    try:
        res = run(symbols=syms, apply=True)
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="validate_expense_ratios.py", error=f"{type(exc).__name__}: {exc}")
        raise
    print(json.dumps(res, indent=2, default=str))
    failed = bool(res["symbols"]) and res["fetch_errors"] >= res["symbols"]
    rc = 1 if failed else 0
    lr.write_lane_receipt(LANE_ID, ok=not failed, exit_code=rc, started_at=started,
                          script="validate_expense_ratios.py",
                          summary={"symbols": res["symbols"], "changed": len(res["changed"]),
                                   "flagged": len(res["flagged"]), "fetch_errors": res["fetch_errors"]})
    return rc


if __name__ == "__main__":
    sys.exit(main())

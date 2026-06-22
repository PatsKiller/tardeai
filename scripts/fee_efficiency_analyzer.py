#!/usr/bin/env python3
"""Fee / cost-efficiency analyzer (operator 2026-06-21).

Autonomous fee intelligence: for every holding, compute the ANNUAL $ fee drag from its expense ratio, and
flag holdings where a cheaper same-purpose fund the household ALREADY owns is matching or beating it — e.g.
FCNTX (active fund, ~1.47% ER, +10.5% YTD) vs SCHD (ETF, 0.06% ER, +14.9% YTD). Findings are emitted so
Reports + Rotation surface them automatically instead of the operator having to ask.

Sources: holdings (data/portfolios/state/holdings.json, real accounts) joined to symbol_profiles
(instrument_type, expense_ratio, ytd_return_pct, dividend_yield_pct). Honest about data gaps: a fund with a
NULL expense_ratio is flagged 'unknown — verify' rather than assumed free. No trades, no writes to holdings.
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

# A holding is "fee-inefficient" worth flagging when its expense ratio exceeds this (or it's an active fund
# with an unknown/!=0 ratio). 0.20%/yr is well above a broad-index ETF (~0.03–0.06%).
FEE_FLAG_THRESHOLD = 0.0020
LOW_COST_BASELINE = 0.0005          # 0.05% — a cheap broad ETF; excess fee is measured against this


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _holdings():
    for p in (PROJ / "data" / "portfolios" / "state" / "holdings.json",):
        try:
            h = json.loads(p.read_text())
            return h.get("holdings") if isinstance(h, dict) else h
        except Exception:
            continue
    return []


def _profiles(symbols):
    if not symbols:
        return {}
    try:
        cur = _conn().cursor()
        cur.execute("""SELECT symbol, instrument_type, expense_ratio, ytd_return_pct, dividend_yield_pct
                       FROM symbol_profiles WHERE symbol = ANY(%s)""", (list(symbols),))
        return {r[0]: {"instrument_type": r[1], "expense_ratio": (float(r[2]) if r[2] is not None else None),
                       "ytd_return_pct": (float(r[3]) if r[3] is not None else None),
                       "dividend_yield_pct": (float(r[4]) if r[4] is not None else None)} for r in cur.fetchall()}
    except Exception:
        return {}


def _is_ira(account: str) -> bool:
    a = (account or "").lower()
    return any(k in a for k in ("ira", "roth", "rollover", "401k"))


def analyze() -> dict:
    holds = _holdings()
    syms = sorted({(h.get("symbol") or "").upper() for h in holds if isinstance(h, dict) and h.get("symbol")})
    prof = _profiles(syms)
    # cheap broad-equity ETFs the household already owns — used as the honest "you already hold this cheaper"
    # contrast (not a precise style match; a directional cost+return reference).
    alts = {s: prof[s] for s in ("SCHD", "SCHG") if s in prof and prof[s].get("expense_ratio") is not None}

    positions, findings = [], []
    total_fee = 0.0
    by_account: dict[str, float] = {}
    for h in holds:
        if not isinstance(h, dict):
            continue
        sym = (h.get("symbol") or "").upper()
        acct = str(h.get("account") or h.get("account_key") or "")
        if not sym or "schwab" not in acct.lower() and "fidelity" not in acct.lower() and "ira" not in acct.lower():
            # real-money accounts only; skip cash/empty
            pass
        try:
            mv = float(h.get("market_value") or (float(h.get("shares") or h.get("quantity") or 0) * float(h.get("price") or 0)))
        except Exception:
            mv = 0.0
        if sym in ("CASH", "") or mv <= 0:
            continue
        p = prof.get(sym) or {}
        itype = p.get("instrument_type")
        er = p.get("expense_ratio")
        is_fund_etf = itype in ("fund", "etf", "mutual_fund")
        annual_fee = (er * mv) if (er is not None and is_fund_etf) else (0.0 if itype == "stock" else None)
        if annual_fee:
            total_fee += annual_fee
            by_account[acct] = by_account.get(acct, 0.0) + annual_fee
        rec = {"symbol": sym, "account": acct, "instrument_type": itype, "market_value": round(mv, 2),
               "expense_ratio": er, "expense_ratio_pct": (round(er * 100, 3) if er is not None else None),
               "annual_fee_usd": (round(annual_fee, 2) if annual_fee is not None else None),
               "ytd_return_pct": p.get("ytd_return_pct"), "dividend_yield_pct": p.get("dividend_yield_pct")}
        positions.append(rec)

        # ── flag fee-inefficient holdings ──
        flag = is_fund_etf and (
            (er is not None and er >= FEE_FLAG_THRESHOLD) or
            (itype in ("fund", "mutual_fund") and (er is None or er > LOW_COST_BASELINE)))
        if flag:
            excess = ((er - LOW_COST_BASELINE) * mv) if er is not None else None
            ytd = p.get("ytd_return_pct")
            # honest contrast vs a cheaper ETF the household already owns
            beaten_by = []
            for asym, a in alts.items():
                if asym == sym:
                    continue
                a_ytd = a.get("ytd_return_pct")
                cheaper = (er is None) or (a.get("expense_ratio", 1) < er)
                if cheaper and a_ytd is not None and ytd is not None and a_ytd >= ytd:
                    beaten_by.append({"symbol": asym, "expense_ratio_pct": round(a["expense_ratio"] * 100, 3),
                                      "ytd_return_pct": a_ytd, "yield_pct": a.get("dividend_yield_pct")})
            findings.append({
                "symbol": sym, "account": acct, "instrument_type": itype, "market_value": round(mv, 2),
                "expense_ratio_pct": (round(er * 100, 3) if er is not None else None),
                "expense_ratio_known": er is not None,
                "annual_fee_usd": (round(annual_fee, 2) if annual_fee else None),
                "excess_fee_vs_index_usd": (round(excess, 2) if excess is not None else None),
                "ytd_return_pct": ytd, "tax_free_to_switch": _is_ira(acct),
                "cheaper_alternatives_beating_it": beaten_by,
                "severity": ("high" if (excess and excess >= 300) or er is None else "medium"),
                "recommendation": _reco(sym, er, mv, ytd, beaten_by, _is_ira(acct)),
            })
    findings.sort(key=lambda f: (f.get("excess_fee_vs_index_usd") or 0), reverse=True)
    return {"positions": positions, "findings": findings,
            "total_annual_fee_usd": round(total_fee, 2),
            "by_account": {k: round(v, 2) for k, v in sorted(by_account.items(), key=lambda x: -x[1])},
            "flagged_count": len(findings),
            "note": "Annual fee = expense_ratio × market_value. Stocks have no expense ratio; a fund with a "
                    "NULL ratio is flagged 'verify' (not assumed free). Cheaper-alternative contrast uses "
                    "low-cost ETFs already held (SCHD/SCHG) — directional, not a precise style match."}


def _reco(sym, er, mv, ytd, beaten_by, tax_free):
    if er is None:
        return f"{sym} expense ratio is unknown in our data — verify it; active funds often run 0.4–1.5%/yr."
    msg = f"{sym} costs ~${round((er - LOW_COST_BASELINE) * mv):,}/yr above a broad-index ETF (~0.05%)."
    if beaten_by:
        b = beaten_by[0]
        msg += f" {b['symbol']} ({b['expense_ratio_pct']}% ER) returned {b['ytd_return_pct']}% YTD vs {sym}'s {ytd}% — cheaper AND ahead."
    if tax_free:
        msg += " It's in a tax-advantaged account, so switching has NO capital-gains cost."
    return msg


def emit_findings(min_severity_excess: float = 0.0):
    """Write fee findings to alert_events so Reports/Intelligence surface them autonomously. Idempotent-ish:
    one info event per flagged holding per run. Best-effort."""
    res = analyze()
    sent = 0
    try:
        from alert_event_writer import save_alert_event
        for f in res["findings"]:
            save_alert_event(alert_type="strategic_alert", severity="info",
                             source_script="fee_efficiency", symbol=f["symbol"],
                             raw_text=f"[fee-efficiency] {f['recommendation']}",
                             parsed_payload={"kind": "fee_efficiency", **f})
            sent += 1
    except Exception:
        pass
    res["emitted"] = sent
    return res


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true", help="also write findings to alert_events for Reports")
    a = ap.parse_args()
    res = emit_findings() if a.emit else analyze()
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()

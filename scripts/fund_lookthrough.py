#!/usr/bin/env python3
"""fund_lookthrough.py — Defense v4 WS-L1: effective sector exposure.

effective = direct holdings + Σ(fund value × factsheet sector weight). Weights come
ONLY from config/fund_lookthrough.json (provider factsheets, quarterly refresh) —
never inferred. Funds marked lookthrough:'none' land in the not_decomposed bucket
and render as such. Shared by sector_momentum_engine (book weights on every row)
and defense_recommendations (joins + stance cards).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_CFG = None
_CANON = None


def _cfg() -> dict:
    global _CFG
    if _CFG is None:
        _CFG = json.loads((ROOT / "config" / "fund_lookthrough.json").read_text())["funds"]
    return _CFG


def canon_sector(name: str) -> str:
    """Finviz names ('Financial Services', 'Consumer Cyclical'…) → the 11 canonical
    sector labels, via the SAME alias map C2 introduced (reverse direction)."""
    global _CANON
    if _CANON is None:
        aliases = json.loads((ROOT / "config" / "sector_momentum.json").read_text()).get("sector_aliases", {})
        _CANON = {}
        for canonical, alist in aliases.items():
            for a in alist:
                _CANON[a] = canonical
    return _CANON.get(name, name)


def effective_sector_exposure(rows: list) -> dict:
    """rows: [{symbol, sector, value}] (book-map shape, per holding).
    Returns {sector: {dollars, pct, direct_dollars, lookthrough_dollars,
    contributors: [{fund, dollars}]}} + special keys '_total', '_not_decomposed'."""
    cfg = _cfg()
    agg: dict = {}
    not_decomposed = []
    total = 0.0

    def bucket(sector):
        return agg.setdefault(sector, {"dollars": 0.0, "direct_dollars": 0.0,
                                       "lookthrough_dollars": 0.0, "contributors": []})

    for r in rows:
        sym = r.get("symbol")
        val = float(r.get("value") or 0)
        if val <= 0:
            continue
        total += val
        fund = cfg.get(sym)
        if fund and fund.get("weights"):
            allocated = 0.0
            for sector, w in fund["weights"].items():
                b = bucket(sector)
                d = val * w
                b["dollars"] += d
                b["lookthrough_dollars"] += d
                b["contributors"].append({"fund": sym, "dollars": round(d)})
                allocated += d
            if val - allocated > 1:
                b = bucket("Other")
                b["dollars"] += val - allocated
                b["lookthrough_dollars"] += val - allocated
        elif fund and fund.get("lookthrough") == "none":
            not_decomposed.append({"symbol": sym, "dollars": round(val), "why": fund.get("why", "")})
        else:
            b = bucket(canon_sector(r.get("sector") or "Other"))
            b["dollars"] += val
            b["direct_dollars"] += val
            b["contributors"].append({"fund": sym, "dollars": round(val), "direct": True})

    for sector, b in agg.items():
        b["dollars"] = round(b["dollars"])
        b["direct_dollars"] = round(b["direct_dollars"])
        b["lookthrough_dollars"] = round(b["lookthrough_dollars"])
        b["pct"] = round(b["dollars"] / total * 100, 1) if total else 0.0
        b["direct_pct"] = round(b["direct_dollars"] / total * 100, 1) if total else 0.0
        # top contributors only, largest first (hover decomposition)
        b["contributors"] = sorted(b["contributors"], key=lambda c: -c["dollars"])[:5]

    agg["_total"] = round(total)
    agg["_not_decomposed"] = {"dollars": round(sum(x["dollars"] for x in not_decomposed)),
                              "positions": not_decomposed}
    return agg

#!/usr/bin/env python3
"""Effective sector exposure with field-level fund provenance.

Effective exposure = direct holdings + configured factsheet sector weights.  Every
fund contribution now carries provider, factsheet date, refresh SLA, coverage and
unmapped weight.  Unknown weights remain explicitly unmapped; they are never guessed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from defense_data_quality import snapshot_hash

ROOT = Path(__file__).resolve().parent.parent
_CFG = None
_CANON = None


def _cfg_all() -> dict:
    global _CFG
    if _CFG is None:
        _CFG = json.loads((ROOT / "config" / "fund_lookthrough.json").read_text())
    return _CFG


def _cfg() -> dict:
    return _cfg_all()["funds"]


def canon_sector(name: str) -> str:
    global _CANON
    if _CANON is None:
        aliases = json.loads((ROOT / "config" / "sector_momentum.json").read_text()).get("sector_aliases", {})
        _CANON = {alias: canonical for canonical, values in aliases.items() for alias in values}
    return _CANON.get(name, name)


def _fund_meta(sym: str, fund: dict, allocated_weight: float) -> dict:
    due = fund.get("refresh_due")
    stale = False
    if due:
        try:
            stale = datetime.now(timezone.utc).date() > datetime.fromisoformat(str(due)[:10]).date()
        except Exception:
            stale = True
    return {
        "fund": sym,
        "provider": fund.get("provider"),
        "factsheet_as_of": fund.get("factsheet_as_of"),
        "refresh_due": due,
        "stale": stale,
        "mapping_quality": fund.get("mapping_quality", "unknown"),
        "coverage_pct": round(allocated_weight * 100, 2),
        "unmapped_weight_pct": round(max(0.0, 1.0 - allocated_weight) * 100, 2),
    }


def effective_sector_exposure(rows: list) -> dict:
    cfg_all, cfg = _cfg_all(), _cfg()
    agg: dict = {}
    not_decomposed = []
    provenance = {}
    total = 0.0
    unmapped_dollars = 0.0

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
            allocated = sum(float(w) for w in fund["weights"].values())
            meta = _fund_meta(sym, fund, allocated)
            provenance[sym] = meta
            for sector, weight in fund["weights"].items():
                dollars = val * float(weight)
                b = bucket(sector)
                b["dollars"] += dollars
                b["lookthrough_dollars"] += dollars
                b["contributors"].append({**meta, "dollars": round(dollars)})
            remainder = max(0.0, val * (1.0 - allocated))
            if remainder > 1:
                unmapped_dollars += remainder
                b = bucket("Other")
                b["dollars"] += remainder
                b["lookthrough_dollars"] += remainder
                b["contributors"].append({**meta, "dollars": round(remainder),
                                           "unmapped_remainder": True})
        elif fund and fund.get("lookthrough") == "none":
            meta = _fund_meta(sym, fund, 0.0)
            provenance[sym] = meta
            not_decomposed.append({"symbol": sym, "dollars": round(val),
                                   "why": fund.get("why", ""), **meta})
        else:
            sector = canon_sector(r.get("sector") or "Other")
            b = bucket(sector)
            b["dollars"] += val
            b["direct_dollars"] += val
            b["contributors"].append({"fund": sym, "dollars": round(val), "direct": True,
                                      "provider": "holding record", "mapping_quality": "direct"})

    for sector, b in agg.items():
        b["dollars"] = round(b["dollars"])
        b["direct_dollars"] = round(b["direct_dollars"])
        b["lookthrough_dollars"] = round(b["lookthrough_dollars"])
        b["pct"] = round(b["dollars"] / total * 100, 1) if total else 0.0
        b["direct_pct"] = round(b["direct_dollars"] / total * 100, 1) if total else 0.0
        b["contributors"] = sorted(b["contributors"], key=lambda c: -c["dollars"])[:8]

    agg["_total"] = round(total)
    agg["_not_decomposed"] = {"dollars": round(sum(x["dollars"] for x in not_decomposed)),
                              "positions": not_decomposed}
    agg["_provenance"] = {
        "schema_version": cfg_all.get("_schema_version"),
        "config_hash": snapshot_hash(cfg_all),
        "funds": provenance,
        "stale_funds": sorted(sym for sym, meta in provenance.items() if meta.get("stale")),
        "unmapped_dollars": round(unmapped_dollars),
        "unmapped_pct_of_book": round(unmapped_dollars / total * 100, 2) if total else 0.0,
    }
    return agg

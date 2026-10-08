"""Analyst Rollup — Data Broker read model for Street/Hermes consensus pills.

Reads pro_analyst_pills_latest.json (canonical store from pro_analyst_fetch.py).
Returns structured consensus data per symbol for Hermes scorer and decision desks.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_PILLS_PATH = PROJECT_ROOT / "data" / "runtime" / "pro_analyst_pills_latest.json"


def get_analyst_rollup(symbols: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Return {SYMBOL: {consensus, mean_target, analyst_count, rec_key, ...}} from the rollup JSON.

    Args:
        symbols: optional filter list. If None, returns ALL symbols in the pills file.
    """
    pills: dict[str, Any] = {}
    try:
        pills = json.loads(_PILLS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass

    pills_by_sym = pills.get("by_symbol") or pills.get("pills") or {}
    if isinstance(pills_by_sym, list):
        # pro_analyst_fetch writes a LIST of pills ({symbol, recommendation_key, target_mean_price, ...}); the dict
        # branch below never matched it, so this reader returned {} for every caller (found 2026-10-08).
        pills_by_sym = {
            str(p.get("symbol")).upper(): {
                "consensus": p.get("recommendation_key"),
                "mean_target": p.get("target_mean_price"),
                "target_high": p.get("target_high_price"),
                "target_low": p.get("target_low_price"),
                "analyst_count": p.get("number_of_analyst_opinions"),
                "rec_key": p.get("recommendation_key"),
                "recommendation_mean": p.get("recommendation_mean"),
                "upside_pct": p.get("upside_to_mean_target_pct"),
                "stale": p.get("stale"),
                "as_of": (p.get("provenance") or {}).get("yahoo_at") or pills.get("updated_at"),
            }
            for p in pills_by_sym if isinstance(p, dict) and p.get("symbol")
        }
    if not isinstance(pills_by_sym, dict):
        return {}

    symbol_set = None
    if symbols:
        symbol_set = {str(s).upper().strip() for s in symbols if s and str(s).strip()}

    out: dict[str, dict[str, Any]] = {}
    for sym, data in pills_by_sym.items():
        sym_u = str(sym).upper()
        if symbol_set and sym_u not in symbol_set:
            continue
        if not isinstance(data, dict):
            continue
        out[sym_u] = {
            "consensus": data.get("consensus"),
            "mean_target": data.get("mean_target"),
            "analyst_count": data.get("analyst_count") or data.get("n"),
            "rec_key": data.get("rec_key"),
            "std_dev": data.get("std_dev"),
            "as_of": data.get("as_of") or data.get("updated_at"),
            "sector": data.get("sector"),
            "target_high": data.get("target_high"),
            "target_low": data.get("target_low"),
            "recommendation_mean": data.get("recommendation_mean"),
            "upside_pct": data.get("upside_pct"),
            "stale": data.get("stale"),
        }
    return out

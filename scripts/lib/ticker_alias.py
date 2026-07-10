"""P2-2 ticker resolution — map Ross/catalog symbols to Finviz scan universe.

Handles STT typos and suffix variants (e.g. VRX transcript → VRAX screener).
"""
from __future__ import annotations

import csv
import glob
import re
from datetime import date
from pathlib import Path
from typing import Any

# Curated aliases from Ross audit discoveries (catalog_sym → finviz_sym).
STATIC_ALIASES: dict[str, str] = {
    "VRX": "VRAX",
}

_PREFIX_CONFIDENCE = 0.88
_FUZZY_CONFIDENCE = 0.75
_STATIC_CONFIDENCE = 0.95


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins = prev[j] + 1
            delete = cur[j - 1] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def load_finviz_universe(
    project_root: Path | str,
    trade_date: date | None = None,
) -> set[str]:
    """Symbols from prime_setups CSV for trade_date (or newest export)."""
    root = Path(project_root)
    if trade_date:
        pattern = str(root / "data" / "raw" / "finviz" / str(trade_date) / "**" / "prime_setups_*.csv")
        files = sorted(glob.glob(pattern, recursive=True))
    else:
        base = root / "data" / "raw" / "finviz"
        files = sorted(base.glob("**/prime_setups_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        files = [str(p) for p in files]

    syms: set[str] = set()
    for fp in files:
        try:
            with open(fp, newline="", encoding="utf-8", errors="replace") as f:
                for row in csv.DictReader(f):
                    tick = (row.get("Ticker") or row.get("ticker") or "").strip().upper()
                    if tick and re.fullmatch(r"[A-Z]{1,5}", tick):
                        syms.add(tick)
        except Exception:
            continue
    return syms


def _prefix_extension(catalog_sym: str, universe: set[str]) -> tuple[str, float] | None:
    """VRX-style: catalog symbol is a prefix of a longer universe ticker."""
    if len(catalog_sym) < 2:
        return None
    matches = [u for u in universe if u.startswith(catalog_sym) and len(u) > len(catalog_sym)]
    if len(matches) == 1:
        return matches[0], _PREFIX_CONFIDENCE
    if len(matches) > 1:
        # Pick shortest extension (VRX → VRAX not VRXXY)
        best = min(matches, key=len)
        return best, _PREFIX_CONFIDENCE * 0.9
    return None


def _fuzzy_match(catalog_sym: str, universe: set[str]) -> tuple[str, float] | None:
    if len(catalog_sym) < 3:
        return None
    best: tuple[str, int] | None = None
    for u in universe:
        d = _levenshtein(catalog_sym, u)
        if d == 0:
            continue
        if d == 1 and (best is None or len(u) < len(best[0])):
            best = (u, d)
    if best:
        return best[0], _FUZZY_CONFIDENCE
    return None


def resolve_symbol(
    symbol: str,
    project_root: Path | str,
    *,
    trade_date: date | None = None,
    universe: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve catalog symbol to scan-universe symbol.

    Returns dict with catalog_symbol, resolved_symbol, symbol_candidate, confidence, method.
    """
    catalog = str(symbol or "").strip().upper()
    if not catalog:
        return {
            "catalog_symbol": "",
            "resolved_symbol": "",
            "symbol_candidate": None,
            "confidence": 0.0,
            "method": "empty",
        }

    uni = universe if universe is not None else load_finviz_universe(project_root, trade_date)

    if catalog in uni:
        return {
            "catalog_symbol": catalog,
            "resolved_symbol": catalog,
            "symbol_candidate": None,
            "confidence": 1.0,
            "method": "exact",
        }

    static = STATIC_ALIASES.get(catalog)
    if static and (not uni or static in uni):
        return {
            "catalog_symbol": catalog,
            "resolved_symbol": static,
            "symbol_candidate": catalog,
            "confidence": _STATIC_CONFIDENCE,
            "method": "static_alias",
        }

    if uni:
        prefix = _prefix_extension(catalog, uni)
        if prefix:
            resolved, conf = prefix
            return {
                "catalog_symbol": catalog,
                "resolved_symbol": resolved,
                "symbol_candidate": catalog,
                "confidence": conf,
                "method": "prefix_extension",
            }

        fuzzy = _fuzzy_match(catalog, uni)
        if fuzzy:
            resolved, conf = fuzzy
            return {
                "catalog_symbol": catalog,
                "resolved_symbol": resolved,
                "symbol_candidate": catalog,
                "confidence": conf,
                "method": "fuzzy",
            }

    if static:
        return {
            "catalog_symbol": catalog,
            "resolved_symbol": static,
            "symbol_candidate": catalog,
            "confidence": _STATIC_CONFIDENCE * 0.85,
            "method": "static_alias_unverified",
        }

    return {
        "catalog_symbol": catalog,
        "resolved_symbol": catalog,
        "symbol_candidate": None,
        "confidence": 0.0,
        "method": "unresolved",
    }


def annotate_row_alias(row: dict, resolution: dict[str, Any]) -> dict:
    """Stamp symbol_candidate on a scored/scan row when alias was used."""
    if resolution.get("symbol_candidate") and resolution.get("resolved_symbol"):
        row["symbol_candidate"] = resolution["symbol_candidate"]
        row["symbol_alias_confidence"] = resolution.get("confidence")
        row["symbol_alias_method"] = resolution.get("method")
    return row
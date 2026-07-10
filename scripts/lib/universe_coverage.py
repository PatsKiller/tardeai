"""P2 universe coverage — always score Finviz prime-setup top gainers (Ross alignment).

Ensures breaking-news / top-gainer movers enter the scoring pipeline even when
they miss secondary screeners (e.g. VRX-style names).
"""
from __future__ import annotations

from pathlib import Path


def inject_prime_setup_universe(
    tickers: list[dict],
    project_root: Path | str,
    *,
    limit: int = 30,
    min_change_pct: float = 5.0,
    min_pre_score: int = 12,
) -> int:
    """Merge Finviz top gainers into ticker list for full scoring. Returns inject count."""
    import sys

    root = Path(project_root)
    lib = root / "scripts" / "lib"
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    from top_gainer_awareness import load_finviz_top_gainers

    gainers = load_finviz_top_gainers(root, limit=limit, min_change_pct=min_change_pct)
    if not gainers:
        return 0

    by_sym = {str(t.get("symbol", "")).upper(): t for t in tickers if t.get("symbol")}
    injected = 0

    for g in gainers:
        sym = g["symbol"]
        if sym in by_sym:
            row = by_sym[sym]
            row["_universe_inject"] = row.get("_universe_inject") or "prime_top_gainer"
            if not row.get("_pre_score") or row["_pre_score"] < min_pre_score:
                row["_pre_score"] = min_pre_score
            continue

        chg = g.get("change_pct") or 0
        gap = g.get("gap_pct") or 0
        rvol = g.get("rvol") or 0
        row = {
            "symbol": sym,
            "price": float(g.get("price") or 0),
            "change_percent": chg,
            "change_pct": chg,
            "gap_percent": gap,
            "gap_pct": gap,
            "relative_volume": float(rvol),
            "rvol": float(rvol),
            "float_m": float(g.get("float_m") or 0),
            "sector": g.get("sector") or "",
            "industry": g.get("industry") or "",
            "company": g.get("company") or "",
            "volume": 0,
            "avg_volume": 0,
            "source_count": 1,
            "source_lists": "prime_setups",
            "screener_name": "prime_setups",
            "primary_source_list": "prime_setups",
            "_source": "screener",
            "_universe_inject": "prime_top_gainer",
            "_pre_score": min_pre_score,
        }
        tickers.append(row)
        by_sym[sym] = row
        injected += 1

    return injected


def inject_catalog_aliases(
    tickers: list[dict],
    catalog_symbols: list[str],
    project_root: Path | str,
    *,
    trade_date=None,
    min_pre_score: int = 12,
) -> int:
    """Ensure alias-resolved catalog symbols are in universe (VRX → VRAX)."""
    import sys

    root = Path(project_root)
    lib = root / "scripts" / "lib"
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    from ticker_alias import resolve_symbol

    by_sym = {str(t.get("symbol", "")).upper(): t for t in tickers if t.get("symbol")}
    injected = 0
    for raw in catalog_symbols:
        sym = str(raw or "").strip().upper()
        if not sym:
            continue
        res = resolve_symbol(sym, root, trade_date=trade_date)
        resolved = res.get("resolved_symbol") or sym
        if resolved in by_sym or resolved == sym:
            continue
        row = {
            "symbol": resolved,
            "price": 0.0,
            "change_percent": 0.0,
            "change_pct": 0.0,
            "gap_percent": 0.0,
            "gap_pct": 0.0,
            "relative_volume": 0.0,
            "rvol": 0.0,
            "float_m": 0.0,
            "volume": 0,
            "avg_volume": 0,
            "source_count": 1,
            "source_lists": "catalog_alias",
            "screener_name": "catalog_alias",
            "primary_source_list": "catalog_alias",
            "_source": "catalog_alias",
            "_universe_inject": "catalog_alias",
            "_pre_score": min_pre_score,
            "symbol_candidate": res.get("symbol_candidate"),
            "symbol_alias_confidence": res.get("confidence"),
        }
        tickers.append(row)
        by_sym[resolved] = row
        injected += 1
    return injected
"""Inject Ross daily-catalog symbols into the scoring universe (with alias resolution)."""
from __future__ import annotations

from datetime import date
from pathlib import Path


def load_ross_catalog_symbols(project_root: Path | str, trade_date: date | str) -> list[str]:
    """Symbols Ross traded on trade_date from ross_daily_catalog."""
    if isinstance(trade_date, str):
        trade_date = date.fromisoformat(trade_date[:10])
    try:
        import sys
        root = Path(project_root)
        sys.path.insert(0, str(root / "scripts"))
        from db_adapter import _db_query
        rows = _db_query(
            """
            SELECT DISTINCT UPPER(s) AS symbol
            FROM ross_daily_catalog, unnest(symbols_traded) AS s
            WHERE trade_date = %s AND COALESCE(s, '') <> ''
            ORDER BY 1
            """,
            (trade_date,),
        ) or []
        return [r["symbol"] for r in rows if r.get("symbol")]
    except Exception:
        return []


def inject_ross_catalog_universe(
    tickers: list[dict],
    project_root: Path | str,
    trade_date: date | str,
    *,
    min_pre_score: int = 12,
) -> int:
    """Merge catalog symbols (via ticker alias) into ticker list. Returns inject count."""
    import sys

    root = Path(project_root)
    lib = root / "scripts" / "lib"
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    from universe_coverage import inject_catalog_aliases

    syms = load_ross_catalog_symbols(root, trade_date)
    if not syms:
        return 0
    td = date.fromisoformat(str(trade_date)[:10]) if isinstance(trade_date, str) else trade_date
    return inject_catalog_aliases(tickers, syms, root, trade_date=td, min_pre_score=min_pre_score)
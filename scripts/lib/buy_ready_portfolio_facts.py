"""Portfolio facts for a BUY_READY / ENTRY_NEAR packet — read-only, flags only.

M5 2026-09-24. The packet's ``portfolio_risk`` was a placeholder
(``ATTACH_WHEN_AVAILABLE``), so an ADD to an existing position was presented
with no concentration context. This assembles the facts the house already has:

* the name's current holding (per account) from ``holdings.json``,
* its share of the WHOLE book (incl. cash) and of invested capital,
* the IPS limits (``config/investment_policy_statement.json`` constraints),
* correlations from ``state/correlation.json`` — explicitly labelled as covering
  only ``symbols_analyzed`` (that file's sector / concentration numbers are for a
  subset, not the book: on 2026-09-24 it said V=17.2% while V was 3.8% of the
  book and 29.7% of invested capital),
* the options book greeks from ``state/options_monitor.json`` (cached; no broker
  call),
* cash as reported by holdings, marked UNVERIFIED unless the source says so.

It returns FACTS and FLAGS. It never proposes a size, a quantity, a weight or an
order (MBI_BEHAVIOR=0); the refused keys of cio_instrument_record.BEHAVIOR_FIELDS
never appear in its output.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
DEFAULT_PATHS = {
    "holdings": STATE_DIR / "holdings.json",
    "correlation": STATE_DIR / "correlation.json",
    "options_monitor": STATE_DIR / "options_monitor.json",
    "ips": PROJECT_ROOT / "config" / "investment_policy_statement.json",
}
SCHEMA = "BuyReadyPortfolioFacts@v1"


def _load(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _f(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _age_minutes(path: Path) -> Optional[float]:
    try:
        return round((datetime.now(timezone.utc).timestamp() - Path(path).stat().st_mtime) / 60.0, 1)
    except OSError:
        return None


def build_portfolio_facts(symbol: str, *, paths: Optional[dict[str, Path]] = None) -> dict[str, Any]:
    sym = str(symbol or "").upper().strip()
    p = dict(DEFAULT_PATHS)
    p.update(paths or {})
    flags: list[str] = []
    unknowns: list[str] = []

    hold = _load(p["holdings"]) or {}
    rows = [h for h in (hold.get("holdings") or []) if isinstance(h, dict)]
    total_mv = sum(_f(h.get("market_value")) or 0.0 for h in rows)
    invested_mv = sum(_f(h.get("market_value")) or 0.0 for h in rows if not h.get("is_cash"))
    cash_mv = sum(_f(h.get("market_value")) or 0.0 for h in rows if h.get("is_cash"))
    mine = [h for h in rows if str(h.get("symbol") or "").upper() == sym and not h.get("is_cash")]
    name_mv = sum(_f(h.get("market_value")) or 0.0 for h in mine)
    held_units = sum(_f(h.get("shares")) or 0.0 for h in mine)
    by_account = [{"account": h.get("account"), "held_units": _f(h.get("shares")),
                   "market_value": _f(h.get("market_value"))} for h in mine]
    if not rows:
        unknowns.append("holdings unavailable")

    ips = (_load(p["ips"]) or {}).get("constraints") or {}
    max_single = _f(ips.get("max_single_position_pct"))
    max_sector = _f(ips.get("max_sector_concentration_pct"))
    if max_single is None:
        unknowns.append("IPS max_single_position_pct unavailable")

    pct_total = round(100.0 * name_mv / total_mv, 2) if total_mv > 0 else None
    pct_invested = round(100.0 * name_mv / invested_mv, 2) if invested_mv > 0 else None
    held = bool(mine)
    if held:
        flags.append("ADD_TO_EXISTING_POSITION")
    if held and max_single is not None and pct_total is not None:
        if pct_total >= max_single:
            flags.append("AT_OR_ABOVE_IPS_SINGLE_NAME_LIMIT")
        # An add can only raise this name's share of the book.
        flags.append("ADD_RAISES_CONCENTRATION")
    if held and pct_invested is not None and max_single is not None and pct_invested >= max_single:
        flags.append("ABOVE_IPS_SINGLE_NAME_LIMIT_OF_INVESTED_CAPITAL")

    corr = _load(p["correlation"]) or {}
    analyzed = list(corr.get("symbols_analyzed") or [])
    matrix = (corr.get("correlation_matrix") or {}).get(sym) or {}
    top_corr = sorted(((k, v) for k, v in matrix.items() if k != sym and _f(v) is not None),
                      key=lambda kv: -abs(float(kv[1])))[:3]
    correlations = {
        "top": [{"symbol": k, "rho": round(float(v), 3)} for k, v in top_corr],
        "coverage": f"subset: {len(analyzed)} symbols analyzed ({', '.join(analyzed)})" if analyzed else "unavailable",
        "subset_sector_exposure_pct": corr.get("sector_exposure"),
        "subset_total_value": _f(corr.get("total_value")),
        "as_of": corr.get("last_updated"),
        "note": "correlation.json covers only symbols_analyzed — its sector/concentration figures are NOT whole-book",
    }
    if not matrix:
        unknowns.append(f"no correlation row for {sym}")

    mon = _load(p["options_monitor"]) or {}
    bg = mon.get("book_greeks") or {}
    options_book = {
        "net_delta_shares": _f(bg.get("net_delta_shares")),
        "net_delta_notional": _f(bg.get("net_delta_notional")),
        "leg_count": bg.get("leg_count"),
        "on_this_underlying": (bg.get("by_underlying") or {}).get(sym),
        "as_of": mon.get("monitored_at"),
        "cache_age_minutes": _age_minutes(p["options_monitor"]),
    }
    if not bg:
        unknowns.append("options book greeks unavailable")

    return {
        "schema": SCHEMA,
        "status": "OK" if rows else "UNAVAILABLE",
        "symbol": sym,
        "held": held,
        "held_units_total": round(held_units, 4) if held else 0.0,
        "held_by_account": by_account,
        "name_market_value": round(name_mv, 2),
        "pct_of_total_book": pct_total,
        "pct_of_invested_capital": pct_invested,
        "book_total_value": round(total_mv, 2),
        "book_invested_value": round(invested_mv, 2),
        "cash_value_reported": round(cash_mv, 2),
        "cash_state": "UNVERIFIED (holdings snapshot; not a broker-confirmed buying-power figure)",
        "ips_limits": {"max_single_position_pct": max_single, "max_sector_concentration_pct": max_sector,
                       "source": "config/investment_policy_statement.json constraints"},
        "sector_exposure_whole_book": "UNAVAILABLE (holdings rows carry no sector)",
        "correlations": correlations,
        "options_book": options_book,
        "holdings_as_of": hold.get("as_of") or hold.get("data_as_of"),
        "flags": flags,
        "unknowns": unknowns,
        "note": "Facts and flags only — never a size, quantity, weight or order (MBI_BEHAVIOR=0).",
    }


__all__ = ["SCHEMA", "build_portfolio_facts"]

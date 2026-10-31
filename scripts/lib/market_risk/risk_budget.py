"""Portfolio risk budget — exposure measured against operator limits (DSN-20261031-market-risk-engine §5.11).

Pure functions over normalized inputs (see ``exposure.normalize_*``). The engine reports "exposure vs budget";
it never resizes anything (MBI_BEHAVIOR = 0). A measure whose inputs are missing is ``None`` (unknown), never 0,
and an unknown measure is never a breach. Accounts appear only as opaque keys.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import yaml

from scripts.lib.market_risk.contract import assert_no_behavior_fields

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BUDGET_PATH = PROJECT_ROOT / "config" / "portfolio_risk_budget.yaml"

# measure name -> limit key in config accounts.*
MEASURES: dict[str, str] = {
    "single_sector_pct": "max_single_sector_pct",
    "ai_basket_pct": "max_ai_basket_pct",
    "growth_style_pct": "max_growth_style_pct",
    "single_theme_pct": "max_single_theme_pct",
    "earnings_exposure_48h_pct": "max_earnings_exposure_48h_pct",
    "event_cluster_exposure_pct": "max_event_cluster_exposure_pct",
    "unprotected_pct": "max_unprotected_pct",
    "recent_entry_in_event_window_pct": "max_recent_entry_in_event_window_pct",
}


def load_budget(path: Path | str = BUDGET_PATH) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if data.get("schema") != "PortfolioRiskBudget@v1":
        raise ValueError(f"{path}: expected schema PortfolioRiskBudget@v1, got {data.get('schema')!r}")
    return data


def limits_for(budget: dict[str, Any], account_key: str | None) -> dict[str, float]:
    accts = budget.get("accounts") or {}
    out = dict(accts.get("default") or {})
    if account_key:
        out.update((accts.get("overrides") or {}).get(account_key) or {})
    return {k: float(v) for k, v in out.items()}


def sessions_until(target: date | datetime | str | None, today: date) -> int | None:
    """Weekday sessions from ``today`` (exclusive) to ``target`` (inclusive); 0 = today; None if past/unknown.
    Exchange holidays are not modelled (a holiday makes the count one high, i.e. the window slightly wider)."""
    if target is None:
        return None
    if isinstance(target, str):
        try:
            target = date.fromisoformat(target[:10])
        except ValueError:
            return None
    if isinstance(target, datetime):
        target = target.date()
    if target < today:
        return None
    n, d = 0, today
    while d < target:
        d = date.fromordinal(d.toordinal() + 1)
        if d.weekday() < 5:
            n += 1
    return n


def _pct(part: float, whole: float) -> float | None:
    return round(100.0 * part / whole, 2) if whole > 0 else None


def classify(symbol: str, profile: dict[str, Any], cls: dict[str, Any]) -> dict[str, bool]:
    sector = str(profile.get("sector") or "")
    text = f"{profile.get('name') or ''} {profile.get('description') or ''}".lower()
    growth = sector in set(cls.get("growth_sectors") or []) or any(
        t in text for t in (cls.get("growth_name_tokens") or [])
    )
    defensive = sector in set(cls.get("defensive_sectors") or [])
    return {"growth": growth and not defensive, "ai": symbol in set(cls.get("ai_basket") or [])}


def measure(
    positions: list[dict[str, Any]],
    *,
    profiles: dict[str, dict[str, Any]],
    etf_lookthrough: dict[str, dict[str, float]] | None,
    stops: list[dict[str, Any]] | None,
    earnings: dict[str, Any] | None,
    entries: list[dict[str, Any]] | None,
    event_symbols: Iterable[str] | None,
    today: date,
    budget: dict[str, Any],
    sessions_48h: int = 2,
) -> dict[str, Any]:
    """Actual exposure percentages for one scope, plus the symbols driving each measure."""
    cls = budget.get("classification") or {}
    comp = (budget.get("vulnerability") or {}).get("components") or {}
    ev_sessions = int((comp.get("recent_event_entry") or {}).get("event_sessions", 5))
    entry_days = int((comp.get("recent_event_entry") or {}).get("entry_days", 10))
    total = sum(float(p.get("market_value") or 0) for p in positions)
    risk = [p for p in positions if not p.get("is_cash") and float(p.get("market_value") or 0) > 0]
    acc: dict[str, float] = {}
    drivers: dict[str, set[str]] = {k: set() for k in MEASURES}
    sectors: dict[str, float] = {}
    themes: dict[str, float] = {}
    stop_syms = {str(s.get("symbol") or "").upper() for s in (stops or [])} if stops is not None else None
    earn = earnings or {}
    recent = set()
    for e in entries or []:
        try:
            opened = date.fromisoformat(str(e.get("opened_at"))[:10])
        except ValueError:
            continue
        if 0 <= (today - opened).days <= entry_days:
            recent.add(str(e.get("symbol") or "").upper())
    ev = {s.upper() for s in event_symbols} if event_symbols is not None else None

    def add(key: str, sym: str, v: float) -> None:
        acc[key] = acc.get(key, 0.0) + v
        drivers[key].add(sym)

    for p in risk:
        sym = str(p.get("symbol") or "").upper()
        mv = float(p.get("market_value") or 0)
        prof = profiles.get(sym) or {}
        c = classify(sym, prof, cls)
        sec = str(prof.get("sector") or "Unknown")
        sectors[sec] = sectors.get(sec, 0.0) + mv
        if prof.get("theme"):
            themes[str(prof["theme"])] = themes.get(str(prof["theme"]), 0.0) + mv
        if c["growth"]:
            add("growth_style_pct", sym, mv)
        look = (etf_lookthrough or {}).get(sym)
        if c["ai"]:
            add("ai_basket_pct", sym, mv)
        elif look:
            ai_w = sum(w for s, w in look.items() if s.upper() in set(cls.get("ai_basket") or []))
            if ai_w > 0:
                add("ai_basket_pct", sym, mv * ai_w)
        names = {sym: 1.0} | ({s.upper(): w for s, w in look.items()} if look else {})
        for n, w in names.items():
            su = sessions_until(earn.get(n), today)
            if su is not None and su <= sessions_48h:
                add("earnings_exposure_48h_pct", sym, mv * w)
        if ev is not None and (sym in ev or any(n in ev for n in names)):
            add("event_cluster_exposure_pct", sym, mv)
        if stop_syms is not None and sym not in stop_syms:
            add("unprotected_pct", sym, mv)
        su_own = sessions_until(earn.get(sym), today)
        if sym in recent and su_own is not None and su_own <= ev_sessions:
            add("recent_entry_in_event_window_pct", sym, mv)

    out: dict[str, Any] = {"total_known": total > 0, "actual": {}, "drivers": {}}
    for k in MEASURES:
        out["actual"][k] = _pct(acc.get(k, 0.0), total)
        out["drivers"][k] = sorted(drivers[k])
    if sectors:
        top = max(sectors, key=lambda s: sectors[s])
        out["actual"]["single_sector_pct"] = _pct(sectors[top], total)
        out["drivers"]["single_sector_pct"] = [top]
    if not themes:
        out["actual"]["single_theme_pct"] = None  # no theme tags: unknown, not zero
    else:
        top = max(themes, key=lambda t: themes[t])
        out["actual"]["single_theme_pct"] = _pct(themes[top], total)
        out["drivers"]["single_theme_pct"] = [top]
    if stop_syms is None:
        out["actual"]["unprotected_pct"] = None
    if ev is None:
        out["actual"]["event_cluster_exposure_pct"] = None
    if earnings is None:
        out["actual"]["earnings_exposure_48h_pct"] = None
        out["actual"]["recent_entry_in_event_window_pct"] = None
    if entries is None:
        out["actual"]["recent_entry_in_event_window_pct"] = None
    if total <= 0:
        out["actual"] = {k: None for k in out["actual"]}
    return out


def breaches(
    measured: dict[str, Any], limits: dict[str, float], budget: dict[str, Any], *, scope: str
) -> list[dict[str, Any]]:
    up = budget.get("uplift") or {}
    warn_at, uplift_at = float(up.get("warn_at", 1.0)), float(up.get("uplift_at", 1.25))
    rows = []
    for m, lk in MEASURES.items():
        actual, limit = measured["actual"].get(m), limits.get(lk)
        if actual is None or not limit:
            continue
        ratio = round(actual / limit, 3)
        if ratio >= warn_at:
            rows.append(
                {
                    "scope": scope,
                    "budget": m,
                    "limit": limit,
                    "actual": actual,
                    "unit": "%",
                    "ratio": ratio,
                    "level": "UPLIFT" if ratio >= uplift_at else "WARN",
                    "breached": True,
                    "drivers": measured["drivers"].get(m, [])[:5],
                }
            )
    rows.sort(key=lambda r: -r["ratio"])
    assert_no_behavior_fields(rows)
    return rows

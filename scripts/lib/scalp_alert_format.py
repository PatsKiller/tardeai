"""Scalp Telegram alert formatting — country flag + source badge (matches Command Center TradingHub)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_COUNTRY_FLAGS = {
    "usa": "🇺🇸", "united states": "🇺🇸", "us": "🇺🇸",
    "canada": "🇨🇦", "israel": "🇮🇱", "china": "🇨🇳",
    "united kingdom": "🇬🇧", "uk": "🇬🇧", "japan": "🇯🇵",
    "germany": "🇩🇪", "france": "🇫🇷", "south korea": "🇰🇷",
    "australia": "🇦🇺", "brazil": "🇧🇷", "india": "🇮🇳",
    "taiwan": "🇹🇼", "ireland": "🇮🇪", "netherlands": "🇳🇱",
    "switzerland": "🇨🇭", "singapore": "🇸🇬", "hong kong": "🇭🇰",
    "mexico": "🇲🇽", "malaysia": "🇲🇾", "bermuda": "🇧🇲",
    "cayman islands": "🇰🇾", "luxembourg": "🇱🇺", "norway": "🇳🇴",
    "sweden": "🇸🇪", "denmark": "🇩🇰", "finland": "🇫🇮",
    "spain": "🇪🇸", "italy": "🇮🇹", "argentina": "🇦🇷",
}

_SRC_CFG: Dict[str, Tuple[str, str]] = {
    "social": ("💬", "Social"),
    "portfolio": ("💼", "Portfolio"),
    "personal_watchlist": ("👤", "Personal"),
    "ai_discovered": ("🤖", "AI"),
    "ai_watchlist": ("🔍", "AI Watch"),
    "screener": ("📊", "Finviz"),
    "continuous": ("📊", "Finviz"),
}


def country_flag(country_name: str) -> str:
    if not country_name:
        return "🇺🇸"
    return _COUNTRY_FLAGS.get(country_name.strip().lower(), "🌐")


def resolve_country_name(symbol: str, raw: str = "", project_root: Optional[Path] = None) -> str:
    """HQ country name; falls back to ticker_enrichment_cache.json like api_v2."""
    v = (raw or "").strip()
    if v:
        return v
    sym = (symbol or "").upper().strip()
    if not sym:
        return ""
    try:
        root = project_root or Path(__file__).resolve().parent.parent.parent
        cache = root / "data" / "portfolios" / "state" / "ticker_enrichment_cache.json"
        if cache.exists():
            data = json.loads(cache.read_text())
            return ((data.get(sym) or {}).get("country") or "").strip()
    except Exception:
        pass
    return ""


def format_country_label(country_name: str, symbol: str = "", *, project_root: Optional[Path] = None) -> str:
    name = resolve_country_name(symbol, country_name, project_root=project_root) or "United States"
    flag = country_flag(name)
    return f"{flag} {name}"


def format_source_label(source: str, source_detail: str = "") -> str:
    """Mirror Command Center srcBadge (TradingHub.tsx)."""
    key = (source or "screener").strip().lower()
    icon, label = _SRC_CFG.get(key, _SRC_CFG["screener"])
    if key == "social" and source_detail:
        detail = source_detail.strip()
        if detail and not detail.lower().startswith("social"):
            label = f"Social {detail}"
        elif detail:
            label = detail
    return f"{icon} {label}"


def resolve_source_fields(ticker: Dict[str, Any]) -> Tuple[str, str]:
    """Map a scored/live ticker row to (source_key, source_detail)."""
    raw = (ticker.get("_source") or ticker.get("source") or "screener").strip().lower()
    if raw == "social":
        lists = ticker.get("source_lists") or ""
        if isinstance(lists, (list, tuple)):
            detail = ", ".join(str(x) for x in lists[:2])
        else:
            detail = str(lists).replace(",", ", ").strip()
        return "social", detail
    if raw in _SRC_CFG:
        return raw, (ticker.get("source_detail") or ticker.get("screener_name") or "").strip()
    return "screener", (ticker.get("screener_name") or ticker.get("source_lists") or "").strip()


def format_scalp_meta_line(
    *,
    source: str,
    source_detail: str = "",
    country: str = "",
    symbol: str = "",
    project_root: Optional[Path] = None,
) -> str:
    """Compact 'Source · Country' line for Telegram scalp alerts."""
    parts = [format_source_label(source, source_detail)]
    parts.append(format_country_label(country, symbol, project_root=project_root))
    return " · ".join(p for p in parts if p)


def meta_line_from_ticker(ticker: Dict[str, Any], project_root: Optional[Path] = None) -> str:
    src, detail = resolve_source_fields(ticker)
    return format_scalp_meta_line(
        source=src,
        source_detail=detail,
        country=ticker.get("country") or "",
        symbol=ticker.get("symbol") or "",
        project_root=project_root,
    )
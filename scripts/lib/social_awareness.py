"""Social awareness-only rows — pre-market / social chatter without Finviz market data."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

AWARENESS_STATUS = "SOCIAL_AWARENESS"
SETUP_CLASS = "social_awareness_only"
COLOR_TOKEN = "socialAwareness"


def build_catalyst_text(
    *,
    news_title: str = "",
    edgar_title: str = "",
    stocktwits_body: str = "",
    mention_count: int = 0,
) -> str:
    for raw in (news_title, edgar_title, stocktwits_body):
        t = (raw or "").strip()
        if t:
            return t[:200]
    if mention_count > 0:
        return f"StockTwits pre-market activity ({mention_count} posts/2hr)"
    return "StockTwits pre-market mention"


def awareness_fields(
    *,
    catalyst: str,
    mention_count: int = 0,
    source_detail: str = "stocktwits_premarket",
) -> Dict[str, Any]:
    """DB + API fields for social-awareness-only scanner rows."""
    posts = int(mention_count or 0)
    cat = (catalyst or "").strip()[:200]
    detail = (source_detail or "stocktwits_premarket").strip()
    return {
        "awareness_status": AWARENESS_STATUS,
        "setup_class": SETUP_CLASS,
        "decision": "WAIT",
        "not_tradeable": True,
        "not_validation_ready": True,
        "manual_review_required": False,
        "operator_pill": f"SOCIAL AWARENESS · {posts} ST" if posts else "SOCIAL AWARENESS",
        "operator_subtitle": "Pre-market social chatter — not Finviz-scanned; awareness only",
        "operator_color_token": COLOR_TOKEN,
        "operator_tooltip_hints": [
            "No price/RVOL until orchestrator or social_scalp_scanner enriches",
            f"Source: {detail}",
        ],
        "catalyst": cat,
        "catalyst_verified": False,
        "catalyst_source": "premarket_social",
    }


def _has_market_data(row: Dict[str, Any]) -> bool:
    try:
        price = float(row.get("price") or 0)
    except (TypeError, ValueError):
        price = 0
    try:
        rvol = float(row.get("rvol") or 0)
    except (TypeError, ValueError):
        rvol = 0
    return price > 0 or rvol > 0


def _is_social_source(row: Dict[str, Any]) -> bool:
    src = (row.get("source") or "").lower()
    detail = (row.get("source_detail") or "").lower()
    run_type = (row.get("run_type") or "").lower()
    if row.get("awareness_status") == AWARENESS_STATUS:
        return True
    if src in ("social", "premarket_social") or "premarket" in src:
        return True
    if "stocktwits" in detail or "premarket" in detail:
        return True
    if run_type == "premarket_social":
        return True
    return False


def is_social_awareness_row(row: Optional[Dict[str, Any]]) -> bool:
    """True when row is social/premarket awareness without Finviz market fields."""
    if not row or not isinstance(row, dict):
        return False
    if row.get("scout_status") == "SOCIAL_SCOUT":
        return False
    if row.get("awareness_status") == AWARENESS_STATUS:
        return True
    return _is_social_source(row) and not _has_market_data(row)


def _row_price(row: Dict[str, Any]) -> float:
    try:
        return float(row.get("price") or 0)
    except (TypeError, ValueError):
        return 0.0


def _row_rvol(row: Dict[str, Any]) -> float:
    try:
        return float(row.get("rvol") or 0)
    except (TypeError, ValueError):
        return 0.0


def _fill_numeric(row: Dict[str, Any], key: str, val: Any) -> None:
    if val is None:
        return
    try:
        num = float(val)
    except (TypeError, ValueError):
        return
    if num <= 0:
        return
    if _row_price(row) > 0 and key == "price":
        return
    if _row_rvol(row) > 0 and key == "rvol":
        return
    cur = row.get(key)
    try:
        if cur is not None and float(cur) > 0:
            return
    except (TypeError, ValueError):
        pass
    row[key] = num


def _fill_str(row: Dict[str, Any], key: str, val: Any) -> None:
    if val is None:
        return
    if isinstance(val, (int, float)):
        s = str(round(float(val), 2))
    else:
        s = str(val).strip()
    if not s:
        return
    if row.get(key):
        return
    row[key] = s


def _fill_volume(row: Dict[str, Any], val: Any) -> None:
    if val is None:
        return
    try:
        num = int(float(val))
    except (TypeError, ValueError):
        return
    if num <= 0 or row.get("volume"):
        return
    row["volume"] = num


def _merge_enrichment_cache(row: Dict[str, Any], enc: Optional[Dict[str, Any]]) -> None:
    if not enc:
        return
    _fill_numeric(row, "rvol", enc.get("rvol"))
    _fill_str(row, "float_m", enc.get("float_m"))
    _fill_str(row, "sector", enc.get("sector"))
    _fill_str(row, "industry", enc.get("industry"))
    _fill_str(row, "gap_pct", enc.get("gap_pct"))
    if not row.get("change_pct") and enc.get("change_from_open_pct") is not None:
        _fill_str(row, "change_pct", enc.get("change_from_open_pct"))
    if not row.get("volume"):
        vb = enc.get("volume_base")
        if vb is not None:
            try:
                _fill_volume(row, float(vb) * 1_000_000)
            except (TypeError, ValueError):
                pass
        elif enc.get("avg_vol_m") is not None:
            try:
                _fill_volume(row, float(enc["avg_vol_m"]) * 1_000_000)
            except (TypeError, ValueError):
                pass


def _merge_quote_overlay(row: Dict[str, Any], quote: Optional[Dict[str, Any]]) -> None:
    if not quote:
        return
    _fill_numeric(row, "price", quote.get("price"))
    _fill_numeric(row, "rvol", quote.get("rvol") or quote.get("relative_volume"))
    _fill_volume(row, quote.get("volume"))
    chg = quote.get("change_pct")
    if chg is None:
        chg = quote.get("change_percent")
    if chg is not None and not row.get("change_pct"):
        try:
            row["change_pct"] = str(round(float(chg), 2))
        except (TypeError, ValueError):
            pass


def _merge_snapshot_fields(row: Dict[str, Any], snap: Optional[Dict[str, Any]]) -> None:
    if not snap:
        return
    _fill_numeric(row, "price", snap.get("price"))
    _fill_numeric(row, "rvol", snap.get("rvol"))
    _fill_volume(row, snap.get("volume"))
    _fill_str(row, "change_pct", snap.get("change_pct"))
    _fill_str(row, "gap_pct", snap.get("gap_pct"))
    _fill_str(row, "float_m", snap.get("float_m"))
    _fill_str(row, "sector", snap.get("sector"))
    _fill_str(row, "industry", snap.get("industry"))


def _load_quote_cache(project_root: Path) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for rel in (
        "data/portfolios/state/finviz_quote_cache.json",
        "data/state/finviz_quote_cache.json",
    ):
        path = project_root / rel
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged.update(data)
        except Exception:
            continue
    return merged


def _fetch_live_finviz_quotes(symbols: List[str], project_root: Path) -> Dict[str, Dict[str, Any]]:
    if not symbols:
        return {}
    try:
        scripts = project_root / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from portfolio_technical import _finviz_api_batch

        raw = _finviz_api_batch(symbols, project_root) or {}
        out: Dict[str, Dict[str, Any]] = {}
        for sym, data in raw.items():
            price = float(data.get("price") or 0)
            if price <= 0:
                continue
            out[sym.upper()] = {
                "price": price,
                "change_pct": float(data.get("change_pct") or 0),
                "volume": int(data.get("volume") or 0),
                "rvol": float(data.get("relative_volume") or 0),
                "source": "finviz_elite_live",
            }
        return out
    except Exception:
        return {}


def enrich_awareness_market_fields(
    tickers: List[Dict[str, Any]],
    project_root: Path | str,
    *,
    fetch_live_quotes: bool = True,
    live_quote_cap: int = 40,
) -> List[Dict[str, Any]]:
    """Backfill price/RVOL/volume/sector for social-awareness rows from Finviz caches."""
    root = Path(project_root)
    targets = []
    seen: set[str] = set()
    for t in tickers:
        sym = (t.get("symbol") or "").upper()
        if not sym or sym in seen:
            continue
        detail = (t.get("source_detail") or "").lower()
        src = (t.get("source") or "").lower()
        if (
            t.get("awareness_status") == AWARENESS_STATUS
            or t.get("setup_class") == SETUP_CLASS
            or is_social_awareness_row(t)
            or "stocktwits_premarket" in detail
            or src in ("premarket_social", "social") and not _has_market_data(t)
        ):
            targets.append(t)
            seen.add(sym)
    if not targets:
        return tickers

    try:
        from finviz_snapshot import load_latest_symbol_fields
    except ImportError:
        from lib.finviz_snapshot import load_latest_symbol_fields  # type: ignore

    snap_map = load_latest_symbol_fields(root)
    enc_cache: Dict[str, Any] = {}
    try:
        scripts = root / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from finviz_enrichment import load_cache

        enc_cache = load_cache(root)
    except Exception:
        enc_path = root / "data" / "state" / "ticker_enrichment_cache.json"
        if enc_path.exists():
            try:
                enc_cache = json.loads(enc_path.read_text(encoding="utf-8"))
            except Exception:
                enc_cache = {}

    quote_cache = _load_quote_cache(root)
    missing_price: List[str] = []

    for row in targets:
        sym = (row.get("symbol") or "").upper()
        if not sym:
            continue
        _merge_snapshot_fields(row, snap_map.get(sym))
        enc = enc_cache.get(sym) or enc_cache.get(sym.upper())
        if isinstance(enc, dict):
            _merge_enrichment_cache(row, enc)
        quote = quote_cache.get(sym) or quote_cache.get(sym.upper())
        if isinstance(quote, dict):
            _merge_quote_overlay(row, quote)
        if _row_price(row) <= 0:
            missing_price.append(sym)

    if fetch_live_quotes and missing_price:
        live = _fetch_live_finviz_quotes(missing_price[:live_quote_cap], root)
        by_sym = {(t.get("symbol") or "").upper(): t for t in targets}
        for sym, quote in live.items():
            row = by_sym.get(sym.upper())
            if row:
                _merge_quote_overlay(row, quote)
                row["market_data_source"] = quote.get("source") or "finviz_elite_live"

    for row in targets:
        if _has_market_data(row):
            row["operator_subtitle"] = (
                "Pre-market social + Finviz overlay (awareness only — not tradeable)"
            )
            hints = list(row.get("operator_tooltip_hints") or [])
            if not any("Finviz overlay" in h for h in hints):
                hints.append("Finviz overlay applied from cache/live quote")
            row["operator_tooltip_hints"] = hints
            if not row.get("market_data_source"):
                row["market_data_source"] = "finviz_overlay"

    return tickers


def tag_social_awareness_row(row: Dict[str, Any], *, catalyst_fallback: str = "") -> Dict[str, Any]:
    """Apply awareness tags in-place when row qualifies; return row."""
    if not is_social_awareness_row(row):
        return row
    if row.get("awareness_status") == AWARENESS_STATUS:
        if not (row.get("catalyst") or "").strip() and catalyst_fallback:
            row["catalyst"] = catalyst_fallback[:200]
        row["not_tradeable"] = True
        row["not_validation_ready"] = True
        return row
    fields = awareness_fields(
        catalyst=(row.get("catalyst") or "").strip() or catalyst_fallback,
        mention_count=int(row.get("mention_count") or row.get("social_stocktwits") or 0),
        source_detail=row.get("source_detail") or "stocktwits_premarket",
    )
    for k, v in fields.items():
        if k == "catalyst" and (row.get("catalyst") or "").strip():
            continue
        row[k] = v
    return row
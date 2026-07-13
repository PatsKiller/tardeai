"""Social awareness-only rows — pre-market / social chatter without Finviz market data."""
from __future__ import annotations

from typing import Any, Dict, Optional

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
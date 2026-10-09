"""GET /api/v3/opportunities[/SYMBOL] — Investment Command Center read API (operator 2026-10-08).

List: the curated ranking from CIO memory (data/cio/cio_opportunity_projection.json, written by
scripts/cio_opportunity_curator.py), with presets (top5, new, re_entry, add_on, exit), filters (type, min_conviction,
min_rr, min_upside, min_coverage, technical_condition, cap_band, sector, position_status, stance, q), sorts
(conviction, rr, upside, reward_pct, risk_pct, momentum, rank) and facets.
Detail: the curated assessment + a LIVE overlay (quote, price stats, levels, analyst, position, re-entry) read at
request time from the data broker (AGENTS §7A: price is the broker quote at read time) + daily candles + the CIO
symbol thesis + the assessment's version history. A symbol not yet curated is assessed on demand (curated=false).
Read-only, zero provider calls, zero LLM.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

#: The CIO-memory projection this API serves (written by cio_opportunity_curator via CIOOpportunityStore).
STORE = "data/cio/cio_opportunity_projection.json"


def _db_query(sql, params=None, fetch="all"):
    from db_adapter import _execute

    return _execute(sql, params, fetch=fetch)


def _store():
    try:
        from scripts.lib.cio_opportunity_store import CIOOpportunityStore
    except ImportError:  # pragma: no cover
        from lib.cio_opportunity_store import CIOOpportunityStore  # type: ignore
    return CIOOpportunityStore()


def get_list(query: dict | None = None) -> dict[str, Any]:
    from lib.data_broker import opportunity as op

    q = op.apply_preset(dict(query or {}))
    proj = _store().read_projection()
    items = list((proj.get("items") or {}).values())
    matched = [a for a in items if op.passes(a, q)]
    sort = str(q.get("sort") or "conviction")
    ranked = op.sort_items(matched, sort)
    try:
        limit = int(q.get("limit") or q.get("page_size") or 50)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(200, limit))
    try:
        page = max(1, int(q.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    rows = ranked[(page - 1) * limit: page * limit]
    facets = {k: dict(Counter(str(a.get(k)) for a in matched if a.get(k)))
              for k in ("type", "technical_condition", "cap_band", "position_status", "stance", "sector")}
    return {
        "ok": True,
        "schema": "OpportunityList@v1",
        "as_of": proj.get("as_of"),
        "run_id": proj.get("run_id"),
        "curated_by": "cio_opportunity_curator → CIO memory",
        "store": STORE,
        "universe": len(items),
        "total": len(matched),
        "page": page,
        "limit": limit,
        "sort": sort,
        "query": {k: v for k, v in q.items() if k != "_"},
        "presets": list((op.load_config().get("presets") or {}).keys()),
        "sorts": list(op.SORTS),
        "facets": facets,
        "factor_labels": {k: v.get("label") for k, v in (op.load_config().get("factors") or {}).items()},
        "items": rows,
        "provider_calls": 0,
        "authority": "READ_ONLY_ADVISORY",
    }


def _thesis(symbol: str) -> dict[str, Any] | None:
    try:
        try:
            from scripts.lib.cio_theses import CIOThesisStore
            from scripts.lib.symbol_thesis_coverage import symbol_thesis_id
        except ImportError:  # pragma: no cover
            from lib.cio_theses import CIOThesisStore  # type: ignore
            from lib.symbol_thesis_coverage import symbol_thesis_id  # type: ignore
        t = CIOThesisStore().get_current(symbol_thesis_id(symbol))
    except Exception:
        return None
    if not t:
        return None
    keep = ("thesis_version", "summary", "stance", "why_owned_or_watched", "evidence_for", "counter_evidence",
            "invalidation_conditions", "what_changes_my_mind", "catalysts", "updated_at", "created_at", "owner_agent",
            "write_provenance", "investment_brief")
    return {k: t.get(k) for k in keep if t.get(k) not in (None, "", [])}


def _modal_cfg() -> dict[str, Any]:
    from lib.data_broker.opportunity import load_config

    return load_config().get("modal") or {}


def _news(sym: str) -> list[dict[str, Any]]:
    """Latest articles (operator 2026-10-08: "nothing here on ... latest news"). Never raises."""
    try:
        from lib.data_broker.catalyst_record import get_symbol_news

        c = _modal_cfg()
        return get_symbol_news(_db_query, sym, days=int(c.get("news_days") or 45), limit=int(c.get("news_limit") or 6))
    except Exception:
        return []


def _catalysts(sym: str) -> list[dict[str, Any]]:
    try:
        from lib.data_broker.catalyst_record import get_symbol_catalysts

        c = _modal_cfg()
        return get_symbol_catalysts(_db_query, sym, days=int(c.get("catalyst_days") or 90),
                                    limit=int(c.get("catalyst_limit") or 5))
    except Exception:
        return []


def _news_and_catalysts(sym: str) -> dict[str, list]:
    """Catalysts first; news leaves out headlines already shown as a catalyst (they share a source row)."""
    from lib.data_broker.catalyst_record import title_key

    cats = _catalysts(sym)
    shown = {title_key(c.get("headline")) for c in cats}
    news = [n for n in _news(sym) if title_key(n.get("title")) not in shown]
    return {"catalysts": cats, "news": news}


def get_detail(symbol: str) -> dict[str, Any]:
    from lib.data_broker import opportunity as op
    from lib.data_broker.ohlc_bars import get_daily_ohlc

    sym = (symbol or "").upper().strip()
    store = _store()
    proj = store.read_projection()
    curated = (proj.get("items") or {}).get(sym)
    ctx = op.gather(_db_query, [sym]).get(sym) or {}
    live = op.assess(sym, ctx)
    ind = ctx.get("indicators") or {}
    st = ctx.get("stats") or {}
    an = ctx.get("analyst") or {}
    q = ctx.get("quote") or {}
    strat = ctx.get("strategy") or {}
    levels = ind.get("levels") or {}
    trend = str(ind.get("alignment") or st.get("ma_alignment") or "").lower()
    return {
        "ok": True,
        "schema": "OpportunityDetail@v1",
        "symbol": sym,
        "curated": curated is not None,
        "assessment": curated or live,
        "assessment_source": "cio_memory" if curated else "on_demand",
        "curated_as_of": proj.get("as_of") if curated else None,
        "live_assessment": live,
        "profile": ctx.get("profile") or {},
        "market": {
            "price": q.get("price"), "prev_close": q.get("prev_close"), "day_change_pct": q.get("day_change_pct"),
            "change_1w_pct": st.get("change_1w_pct"), "change_1m_pct": st.get("change_1m_pct"),
            "high_52w": st.get("high_52w"), "low_52w": st.get("low_52w"), "range_source": st.get("range_source"),
            "avg_volume_30d": st.get("avg_volume_30d"), "relative_volume": st.get("relative_volume") or ind.get("volume_ratio"),
            "volume": q.get("volume"), "quote_as_of": q.get("as_of"), "stats_as_of": st.get("as_of"),
        },
        "technical": {
            "support_1": levels.get("s1") or _num(strat.get("support")), "support_2": levels.get("s2"),
            "resistance_1": levels.get("r1") or _num(strat.get("resistance")), "resistance_2": levels.get("r2"),
            "levels_source": "pivots_weekly" if levels.get("s1") else ("strategy_card" if strat.get("support") else None),
            "trend": "bullish" if trend == "bullish" else ("bearish" if trend == "bearish" else ("neutral" if trend else None)),
            "rsi": ind.get("rsi"), "rsi_status": ind.get("rsi_status"),
            "macd_signal": ind.get("macd_signal"), "macd_histogram_direction": ind.get("macd_histogram_direction"),
            "sma_20": st.get("sma_20") or ind.get("sma_20"), "sma_50": st.get("sma_50") or ind.get("sma_50"),
            "sma_200": st.get("sma_200"), "ma_alignment": st.get("ma_alignment") or ind.get("alignment"),
            "atr": ind.get("atr"), "as_of": _iso((ctx.get("as_of") or {}).get("indicators")),
        },
        "analyst": {
            "consensus": an.get("recommendation_key"), "recommendation_mean": an.get("recommendation_mean"),
            "analyst_count": an.get("analyst_count"), "target_mean": an.get("target_mean"),
            "target_high": an.get("target_high"), "target_low": an.get("target_low"),
            "upside_pct": live.get("upside_pct"), "upside_flag": live.get("upside_flag"),
            "source": an.get("source"), "as_of": _iso((ctx.get("as_of") or {}).get("analyst")),
        },
        **_news_and_catalysts(sym),
        "position": ctx.get("position") or {},
        "reentry_state": ctx.get("reentry_state"),
        "chart": get_daily_ohlc(_db_query, sym, days=180),
        "thesis": _thesis(sym),
        "history": store.history(sym),
        "brief": (_thesis(sym) or {}).get("investment_brief"),
        "provider_calls": 0,
        "authority": "READ_ONLY_ADVISORY",
    }


def _num(v: Any):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _iso(v: Any):
    return v.isoformat() if hasattr(v, "isoformat") else v

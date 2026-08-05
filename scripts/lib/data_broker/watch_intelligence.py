"""Canonical Data Broker projection: Watch Intelligence (read-only, zero provider calls).

Typed domains for reuse across Watch, Portfolio, Re-Entry, Risk, Active Trader,
Research Intelligence, Agents, and reports.

Watch-specific React must NOT re-select quotes, invent company copy, or pick
agent artifacts — it consumes this projection only.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

CONTRACT_VERSION = "watch_intelligence.broker.v1"

# Views exposed on the unified primary page
VIEWS = (
    "top_ideas",
    "starred",
    "held",
    "screener_finds",
    "near_trigger",
    "reviewed_today",
    "needs_review",
    "needs_data",
    "avoid",
    "all",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def field(
    value: Any,
    *,
    source: str | None,
    source_record_id: str | None = None,
    observed_at: Any = None,
    freshness_state: str | None = None,
    quality_state: str = "VALID",
) -> dict[str, Any]:
    """Material field envelope — source/freshness always explicit."""
    fs = freshness_state
    qs = quality_state
    if value is None and qs == "VALID":
        qs = "UNAVAILABLE"
        fs = fs or "DATA_UNAVAILABLE"
    return {
        "value": value,
        "source": source,
        "source_record_id": source_record_id,
        "observed_at": observed_at.isoformat() if hasattr(observed_at, "isoformat") else observed_at,
        "freshness_state": fs or ("CURRENT" if value is not None else "DATA_UNAVAILABLE"),
        "quality_state": qs,
    }


def _snapshot_id(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _starred_set() -> set[str]:
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("SELECT upper(symbol) AS s FROM operator_starred_symbols")
        return {
            (r["s"] if hasattr(r, "keys") else r[0])
            for r in (cur.fetchall() or [])
        }
    except Exception:
        return set()


def _screener_origin_set() -> set[str]:
    out: set[str] = set()
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute(
            """
            SELECT upper(symbol) AS s FROM screener_find_pins WHERE active = true
            """
        )
        out |= {(r["s"] if hasattr(r, "keys") else r[0]) for r in (cur.fetchall() or [])}
    except Exception:
        pass
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute(
            """
            SELECT DISTINCT upper(symbol) AS s FROM watchlist_items
             WHERE status IN ('active','researched')
               AND (
                 lower(coalesce(source,'')) LIKE '%%screener%%'
                 OR lower(coalesce(trigger_source,'')) LIKE '%%screener%%'
                 OR lower(coalesce(source,'')) LIKE '%%find%%'
               )
             LIMIT 500
            """
        )
        out |= {(r["s"] if hasattr(r, "keys") else r[0]) for r in (cur.fetchall() or [])}
    except Exception:
        pass
    return out


def _held_set() -> set[str]:
    from lib.watchlist_intelligence import _held_set as hs
    return hs()


def _universe_symbols(*, view: str, page_size: int, extra: list[str] | None = None) -> list[str]:
    """Bounded symbol universe for the projection (never the full 5.7k dump)."""
    from lib.watchlist_intelligence import DEFAULT_PRIORITY

    starred = _starred_set()
    held = _held_set()
    screener = _screener_origin_set()
    base: list[str] = []

    if view == "starred":
        base = sorted(starred)
    elif view == "held":
        base = sorted(held)
    elif view == "screener_finds":
        base = sorted(screener)[: max(page_size * 3, 80)]
    elif view == "top_ideas":
        base = list(DEFAULT_PRIORITY)
        # enrich top ideas with strong street candidates later after cards built
    else:
        # all / needs_* / near_trigger / avoid / reviewed — start with priority + starred + held
        seen = set()
        for s in list(DEFAULT_PRIORITY) + sorted(starred) + sorted(held) + sorted(list(screener)[:40]):
            if s not in seen:
                seen.add(s)
                base.append(s)
        # add more active watchlist items up to bound
        try:
            from db_adapter import _get_conn
            cur = _get_conn().cursor()
            cur.execute(
                """
                SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s
                  FROM watchlist_items
                 WHERE status IN ('active','researched')
                 ORDER BY upper(symbol), updated_at DESC NULLS LAST
                 LIMIT 120
                """
            )
            for r in cur.fetchall() or []:
                s = r["s"] if hasattr(r, "keys") else r[0]
                if s not in seen:
                    seen.add(s)
                    base.append(s)
        except Exception:
            pass

    if extra:
        for s in extra:
            su = s.upper()
            if su not in base:
                base.append(su)
    return base


def _card_to_broker_item(card: dict[str, Any], *, starred: bool, screener: bool) -> dict[str, Any]:
    """Map intelligence card → typed broker domains with field provenance."""
    street = card.get("street_consensus") or {}
    cio = card.get("cio_review") or {}
    maria = card.get("maria_review") or {}
    rel = card.get("relative_performance") or {}

    quote_src = card.get("price_source") or "canonical_quote"
    qid = card.get("quote_id")
    srid = card.get("source_record_id")
    q_asof = card.get("price_as_of")
    q_fresh = card.get("freshness_state")

    identity = {
        "symbol": field(card.get("symbol"), source="watch_intelligence", quality_state="VALID"),
        "company": field(
            card.get("company"),
            source="symbol_profiles",
            observed_at=None,
            quality_state="VALID" if card.get("company") else "UNAVAILABLE",
        ),
        "company_summary": field(
            card.get("company_summary"),
            source="symbol_profiles.description_1s",
            quality_state="VALID" if card.get("company_summary") else "UNAVAILABLE",
        ),
        "sector": field(card.get("sector"), source="symbol_profiles"),
        "industry": field(card.get("industry"), source="symbol_profiles"),
        "instrument_type": field(card.get("instrument_type") or "stock", source="symbol_profiles"),
    }

    quote = {
        "last": field(card.get("last"), source=quote_src, source_record_id=str(srid or qid or ""), observed_at=q_asof, freshness_state=q_fresh),
        "day_change_pct": field(card.get("day_change_pct"), source=quote_src, source_record_id=str(srid or qid or ""), observed_at=q_asof, freshness_state=q_fresh),
        "price_as_of": field(q_asof, source=quote_src, source_record_id=str(srid or qid or ""), observed_at=q_asof, freshness_state=q_fresh),
        "price_source": field(quote_src, source="watch_canonical_quote"),
        "quote_id": field(qid, source="watch_canonical_quote", source_record_id=str(qid or "")),
        "source_record_id": field(srid, source="watch_canonical_quote", source_record_id=str(srid or "")),
        "market_session": field(card.get("market_session"), source="watch_canonical_quote", observed_at=q_asof, freshness_state=q_fresh),
        "freshness_state": field(q_fresh, source="watch_canonical_quote", observed_at=q_asof, freshness_state=q_fresh),
        "market_state": field(card.get("market_state"), source="watch_canonical_quote", freshness_state=q_fresh),
    }

    membership = {
        "on_watchlist": field(True, source="watchlist_items"),
        "starred": field(starred, source="operator_starred_symbols"),
        "held": field(bool(card.get("held")), source="holdings.json"),
        "screener_origin": field(screener, source="screener_find_pins|watchlist_items.source"),
        "status": field(None, source="watchlist_items", quality_state="UNAVAILABLE"),
    }

    street_domain = {
        "rating": field(card.get("street_rating") or "NOT RATED", source=street.get("source") or "yahoo_analyst_targets_history", observed_at=street.get("as_of")),
        "tone": field(card.get("street_tone"), source=street.get("source") or "yahoo_analyst_targets_history"),
        "analyst_count": field(street.get("analyst_count"), source=street.get("source") or "yahoo"),
        "target_mean": field(street.get("target_mean"), source=street.get("source") or "yahoo", observed_at=street.get("as_of")),
        "implied_upside_pct": field(street.get("implied_upside_pct"), source="computed_from_yahoo_target_vs_quote"),
        "recommendation_key": field(street.get("recommendation_key"), source=street.get("source") or "yahoo"),
        "as_of": field(street.get("as_of"), source=street.get("source") or "yahoo"),
    }

    trade_ai = {
        "primary_state": field(card.get("trade_ai_state"), source="decision_packets+projection"),
        "proposal_allowed": field(bool(card.get("proposal_allowed")), source="decision_action_policy"),
        "operator_meaning": field(card.get("operator_meaning") or card.get("one_line_thesis"), source="decision_projection"),
        "allowed_action_now": field(card.get("allowed_action_now") or card.get("next_operator_action"), source="decision_projection"),
        "current_mechanics_visible": field(bool(card.get("current_mechanics_visible")), source="decision_projection"),
        "primary_risk": field(card.get("primary_risk"), source="decision_projection"),
        "next_review": field(card.get("next_review_time"), source="decision_projection"),
    }

    def _review_domain(rev: dict, agent: str) -> dict:
        complete = rev.get("status") == "COMPLETE"
        return {
            "agent_id": field(agent, source="review_artifact" if complete else "not_run"),
            "status": field(rev.get("status") or "NOT_RUN", source="review_artifact" if complete else "not_run"),
            "summary": field(rev.get("summary") if complete else None, source="review_artifact" if complete else "not_run", quality_state="VALID" if complete and rev.get("summary") else "UNAVAILABLE"),
            "verdict": field(rev.get("verdict") if complete else None, source="review_artifact" if complete else "not_run"),
            "provider": field(rev.get("provider") if complete else None, source="review_artifact" if complete else "not_run", quality_state="VALID" if complete else "UNAVAILABLE"),
            "model": field(rev.get("model") if complete else None, source="review_artifact" if complete else "not_run", quality_state="VALID" if complete else "UNAVAILABLE"),
            "policy": field(rev.get("policy") if complete else "NO_CALL", source="review_artifact" if complete else "not_run"),
            "reason_code": field(rev.get("reason_code"), source="not_run" if not complete else "review_artifact"),
            "process_id": field(rev.get("process_id") if complete else None, source="review_artifact" if complete else "not_run"),
            "estimated_cost_usd": field(rev.get("estimated_cost_usd") if complete else 0.0, source="review_artifact" if complete else "not_run"),
            "display": rev.get("display"),
            "artifact": rev if complete else None,
        }

    catalyst = {
        "summary": field(card.get("catalyst_summary"), source="catalyst_events"),
        "versus_industry": field(card.get("catalyst_vs_industry"), source="derived", quality_state="PARTIAL" if card.get("catalyst_vs_industry") else "UNAVAILABLE"),
    }

    technical = {
        "support": field(card.get("support"), source="watchlist_strategy_cards"),
        "resistance": field(card.get("resistance"), source="watchlist_strategy_cards"),
        "setup": field(card.get("technical_setup"), source="watchlist_items|strategy_cards"),
        "rsi": field(card.get("rsi"), source="watchlist_items|enrichment"),
        "rvol": field(card.get("rvol"), source="watchlist_items"),
        "atr": field(card.get("atr"), source="enrichment_cache"),
    }

    relative = {
        "summary": field(card.get("relative_performance_summary") or rel.get("summary"), source="enrichment_cache|symbol_profiles"),
        "periods": field(rel.get("periods"), source="enrichment_cache"),
        "versus_industry": field(rel.get("versus_industry"), source=None, quality_state="UNAVAILABLE"),
        "versus_sector": field(rel.get("versus_sector"), source=None, quality_state="UNAVAILABLE"),
        "versus_spy": field(rel.get("versus_spy"), source=None, quality_state="UNAVAILABLE"),
        "missing": rel.get("missing") or [],
    }

    freshness = {
        "quote": field(q_fresh, source="watch_canonical_quote", observed_at=q_asof, freshness_state=q_fresh),
        "street": field(street.get("as_of") is not None, source=street.get("source") or "yahoo"),
        "cio_status": field(cio.get("status"), source="review_artifact|not_run"),
        "maria_status": field(maria.get("status"), source="review_artifact|not_run"),
    }

    # Flat convenience for UI (still broker-owned, not page-joined)
    flat = {
        "symbol": card.get("symbol"),
        "company": card.get("company"),
        "company_summary": card.get("company_summary"),
        "sector": card.get("sector"),
        "industry": card.get("industry"),
        "instrument_type": card.get("instrument_type"),
        "street_rating": card.get("street_rating"),
        "street_tone": card.get("street_tone"),
        "analyst_count": street.get("analyst_count"),
        "target_mean": street.get("target_mean"),
        "implied_upside_pct": street.get("implied_upside_pct"),
        "trade_ai_state": card.get("trade_ai_state"),
        "proposal_allowed": card.get("proposal_allowed"),
        "operator_meaning": card.get("operator_meaning") or card.get("one_line_thesis"),
        "next_operator_action": card.get("next_operator_action") or card.get("allowed_action_now"),
        "primary_risk": card.get("primary_risk"),
        "last": card.get("last"),
        "day_change_pct": card.get("day_change_pct"),
        "price_as_of": q_asof,
        "price_source": quote_src,
        "quote_id": qid,
        "source_record_id": srid,
        "freshness_state": q_fresh,
        "market_session": card.get("market_session"),
        "support": card.get("support"),
        "resistance": card.get("resistance"),
        "technical_setup": card.get("technical_setup"),
        "catalyst_summary": card.get("catalyst_summary"),
        "catalyst_vs_industry": card.get("catalyst_vs_industry"),
        "relative_performance_summary": card.get("relative_performance_summary"),
        "starred": starred,
        "held": bool(card.get("held")),
        "screener_origin": screener,
        "cio_review": cio,
        "maria_review": maria,
        "sentinel_review": card.get("sentinel_review"),
        "material_change": bool(card.get("material_change")),
        "next_review_time": card.get("next_review_time"),
    }

    return {
        "symbol": card.get("symbol"),
        "domains": {
            "SymbolIdentity": identity,
            "CanonicalQuote": quote,
            "WatchMembership": membership,
            "StreetConsensus": street_domain,
            "TradeAiDecision": trade_ai,
            "CioReviewArtifact": _review_domain(cio, "cio"),
            "AgentReviewArtifact": _review_domain(maria, "maria"),
            "CatalystContext": catalyst,
            "RelativePerformance": relative,
            "TechnicalSnapshot": technical,
            "PositionContext": {"held": field(bool(card.get("held")), source="holdings.json")},
            "FreshnessAndLineage": freshness,
        },
        "card": flat,
    }


def _apply_filters(items: list[dict], q: dict[str, Any]) -> list[dict]:
    view = (q.get("view") or "top_ideas").lower()
    street = {x.strip().upper().replace(" ", "_") for x in str(q.get("street_rating") or "").split(",") if x.strip()}
    states = {x.strip().upper() for x in str(q.get("trade_ai_state") or "").split(",") if x.strip()}
    sectors = {x.strip().lower() for x in str(q.get("sector") or "").split(",") if x.strip()}
    industries = {x.strip().lower() for x in str(q.get("industry") or "").split(",") if x.strip()}
    instruments = {x.strip().lower() for x in str(q.get("instrument") or "").split(",") if x.strip()}
    origin = (q.get("origin") or "").strip().lower()
    review = (q.get("review_status") or "").strip().upper()
    search = (q.get("q") or q.get("search") or "").strip().upper()
    starred_only = str(q.get("starred") or "").lower() in ("1", "true", "yes")
    held_only = str(q.get("held") or "").lower() in ("1", "true", "yes")

    out = []
    for it in items:
        c = it.get("card") or {}
        sym = c.get("symbol") or it.get("symbol")

        if view == "starred" and not c.get("starred"):
            continue
        if view == "held" and not c.get("held"):
            continue
        if view == "screener_finds" and not c.get("screener_origin"):
            continue
        if view == "needs_data":
            if c.get("freshness_state") not in ("DATA_UNAVAILABLE", "STALE") and c.get("last") is not None:
                # also needs company description
                if c.get("company_summary"):
                    continue
        if view == "needs_review":
            cio = (c.get("cio_review") or {}).get("status")
            maria = (c.get("maria_review") or {}).get("status")
            if cio == "COMPLETE" and maria == "COMPLETE":
                continue
        if view == "reviewed_today":
            # COMPLETE either review (date filter best-effort via artifact later)
            cio = (c.get("cio_review") or {}).get("status")
            maria = (c.get("maria_review") or {}).get("status")
            if cio != "COMPLETE" and maria != "COMPLETE":
                continue
        if view == "avoid":
            st = (c.get("trade_ai_state") or "").upper()
            if st not in ("AVOID", "BLOCKED", "DETERMINISTIC_FAIL"):
                continue
        if view == "near_trigger":
            # heuristic: WAIT with support/resistance present
            if (c.get("trade_ai_state") or "").upper() != "WAIT":
                continue
            if c.get("support") is None and c.get("resistance") is None:
                continue
        if view == "top_ideas":
            # Strong street or WAIT/MANAGING priority set — keep all passed base
            pass

        if starred_only and not c.get("starred"):
            continue
        if held_only and not c.get("held"):
            continue
        if origin in ("screener_find", "screener_finds", "screener") and not c.get("screener_origin"):
            continue

        sr = (c.get("street_rating") or "NOT RATED").upper().replace(" ", "_")
        if street:
            aliases = {sr, sr.replace("_", " ")}
            want = set()
            for w in street:
                want.add(w)
                want.add(w.replace("_", " "))
            if sr not in street and sr.replace("_", " ") not in {x.replace("_", " ") for x in street}:
                # normalize STRONG_BUY vs STRONG BUY
                ok = False
                for w in street:
                    if w.replace("_", " ") == (c.get("street_rating") or "").upper():
                        ok = True
                if not ok:
                    continue

        if states and (c.get("trade_ai_state") or "").upper() not in states:
            continue
        if sectors and (c.get("sector") or "").lower() not in sectors:
            continue
        if industries and (c.get("industry") or "").lower() not in industries:
            continue
        if instruments and (c.get("instrument_type") or "stock").lower() not in instruments:
            continue

        if review == "COMPLETE":
            if (c.get("cio_review") or {}).get("status") != "COMPLETE" and (c.get("maria_review") or {}).get("status") != "COMPLETE":
                continue
        if review == "NOT_RUN":
            if (c.get("cio_review") or {}).get("status") == "COMPLETE" or (c.get("maria_review") or {}).get("status") == "COMPLETE":
                continue

        if search:
            blob = f"{sym} {c.get('company')} {c.get('sector')} {c.get('industry')}".upper()
            if search not in blob:
                continue

        out.append(it)
    return out


def _sort_items(items: list[dict], sort: str) -> list[dict]:
    sort = (sort or "watch_rank").lower()

    def key(it: dict):
        c = it.get("card") or {}
        street_rank = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "NOT RATED": 4}.get(c.get("street_rating") or "NOT RATED", 5)
        if sort == "street_rating":
            return (street_rank, c.get("symbol") or "")
        if sort == "day_change":
            return (-(c.get("day_change_pct") or 0), c.get("symbol") or "")
        if sort == "symbol":
            return (c.get("symbol") or "",)
        if sort == "upside":
            return (-(c.get("implied_upside_pct") or -9999), street_rank)
        # default watch_rank
        starred = 0 if c.get("starred") else 1
        held = 0 if c.get("held") else 1
        return (starred, held, street_rank, c.get("symbol") or "")

    return sorted(items, key=key)


def list_watch_intelligence(query: dict | None = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/watch-intelligence — filtered, paginated, provenance-bearing."""
    from lib.watchlist_intelligence import list_intelligence

    q = dict(query or {})
    view = (q.get("view") or "top_ideas").lower()
    if view not in VIEWS:
        view = "top_ideas"
    page = max(1, int(q.get("page") or 1))
    page_size = min(100, max(1, int(q.get("page_size") or q.get("limit") or 40)))
    sort = str(q.get("sort") or "watch_rank")

    syms = _universe_symbols(view=view, page_size=page_size)
    # Build cards via shared intelligence aggregator (no provider calls)
    raw = list_intelligence(symbols=syms, limit=len(syms) or 1, priority_only=False, offset=0)
    cards = raw.get("cards") or []

    starred = _starred_set()
    screener = _screener_origin_set()

    items = [
        _card_to_broker_item(
            c,
            starred=(c.get("symbol") or "").upper() in starred,
            screener=(c.get("symbol") or "").upper() in screener,
        )
        for c in cards
    ]
    # ensure membership flags accurate
    for it in items:
        sym = (it.get("symbol") or "").upper()
        it["card"]["starred"] = sym in starred
        it["card"]["screener_origin"] = sym in screener
        it["domains"]["WatchMembership"]["starred"] = field(sym in starred, source="operator_starred_symbols")
        it["domains"]["WatchMembership"]["screener_origin"] = field(sym in screener, source="screener_find_pins|watchlist_items.source")

    filtered = _apply_filters(items, {**q, "view": view})
    sorted_items = _sort_items(filtered, sort)
    total = len(sorted_items)
    start = (page - 1) * page_size
    page_items = sorted_items[start : start + page_size]

    counts = {
        "total_matched": total,
        "page": page,
        "page_size": page_size,
        "starred_universe": len(starred),
        "held_universe": len(_held_set()),
        "screener_universe": len(screener),
        "street_strong_buy": sum(1 for i in filtered if (i.get("card") or {}).get("street_rating") == "STRONG BUY"),
        "street_buy": sum(1 for i in filtered if (i.get("card") or {}).get("street_rating") == "BUY"),
        "trade_ai_wait": sum(1 for i in filtered if (i.get("card") or {}).get("trade_ai_state") == "WAIT"),
        "proposal_eligible": sum(1 for i in filtered if (i.get("card") or {}).get("proposal_allowed")),
        "complete_reviews": sum(
            1 for i in filtered
            if (i.get("card") or {}).get("cio_review", {}).get("status") == "COMPLETE"
            or (i.get("card") or {}).get("maria_review", {}).get("status") == "COMPLETE"
        ),
    }

    body = {
        "ok": True,
        "snapshot_id": None,  # filled below
        "generated_at": _now(),
        "data_contract_version": CONTRACT_VERSION,
        "contract_version": CONTRACT_VERSION,
        "provider_calls": 0,
        "paid_flags_enabled": False,
        "broker_write_authority": "NONE",
        "view": view,
        "sort": sort,
        "query": {k: v for k, v in q.items() if k not in ("_")},
        "source_status": {
            "package": "scripts/lib/data_broker",
            "projection": "watch_intelligence",
            "canonical_quotes": "data_broker + watch_canonical_quote",
            "street_consensus": "data_broker.analyst_rollup + yahoo_analyst_targets_history",
            "decision_packets": "ok",
            "review_artifacts": "ok",
            "symbol_profiles": "data_broker.symbol_profile store",
            "membership": "operator_starred_symbols + holdings + screener_find_pins",
            "provider_calls": 0,
        },
        "data_quality_status": "OK",
        "counts": counts,
        "items": page_items,
        # convenience for existing board components
        "cards": [i.get("card") for i in page_items],
        "summary": {
            "street_strong_buy": counts["street_strong_buy"],
            "street_buy": counts["street_buy"],
            "trade_ai_wait": counts["trade_ai_wait"],
            "blocked_or_unavailable": sum(
                1 for i in filtered
                if (i.get("card") or {}).get("trade_ai_state") in (
                    "BLOCKED", "DATA_UNAVAILABLE", "DETERMINISTIC_FAIL", "STALE", "AVOID"
                )
            ),
            "managing_held": sum(1 for i in filtered if (i.get("card") or {}).get("held") or (i.get("card") or {}).get("trade_ai_state") == "MANAGING"),
            "proposal_eligible": counts["proposal_eligible"],
        },
        "flags": {
            "watch_intelligence_primary": True,
            "watch_legacy_hidden": True,
            "watch_deepseek_flash_enabled": False,
            "watch_cio_daily_enabled": False,
        },
        "consumers": [
            "Watch Intelligence",
            "Portfolio",
            "Re-Entry",
            "Risk",
            "Active Trader",
            "Research Intelligence",
            "Agents",
            "Reports",
        ],
        "data_broker": {
            "package": "scripts/lib/data_broker",
            "projection": "watch_intelligence",
            "contract_version": CONTRACT_VERSION,
            "catalog": "/api/v3/data-broker",
            "composes": [
                "market_quote / watch_canonical_quote",
                "symbol_profile",
                "analyst_rollup",
                "yahoo_analyst_targets_history",
                "catalyst_record / catalyst_events",
                "decision_packets",
                "review_artifacts",
                "operator_starred_symbols",
                "holdings.json",
                "screener_find_pins",
            ],
            "read_only": True,
            "provider_calls": 0,
        },
    }
    body["snapshot_id"] = _snapshot_id({
        "view": view, "count": total, "page": page,
        "symbols": [i.get("symbol") for i in page_items],
        "v": CONTRACT_VERSION,
    })
    return body


def detail_watch_intelligence(symbol: str) -> dict[str, Any]:
    from lib.watchlist_intelligence import detail_intelligence

    raw = detail_intelligence(symbol)
    if not raw.get("ok"):
        return {
            "ok": False,
            "error": raw.get("error") or "unavailable",
            "symbol": symbol.upper(),
            "provider_calls": 0,
            "data_contract_version": CONTRACT_VERSION,
            "generated_at": _now(),
        }
    card = raw.get("card") or {}
    starred = card.get("symbol", "").upper() in _starred_set()
    screener = card.get("symbol", "").upper() in _screener_origin_set()
    item = _card_to_broker_item(card, starred=starred, screener=screener)
    body = {
        "ok": True,
        "snapshot_id": _snapshot_id({"sym": symbol.upper(), "v": CONTRACT_VERSION, "t": raw.get("generated_at")}),
        "generated_at": _now(),
        "data_contract_version": CONTRACT_VERSION,
        "contract_version": CONTRACT_VERSION,
        "provider_calls": 0,
        "paid_flags_enabled": False,
        "broker_write_authority": "NONE",
        "source_status": {"detail": "ok", "provider_calls": 0},
        "data_quality_status": "OK",
        "counts": {"domains": len(item.get("domains") or {})},
        "symbol": symbol.upper(),
        "item": item,
        "card": item.get("card"),
        "detail": raw,  # full package for symbol page
        "domains": item.get("domains"),
        "consumers": [
            "Watch Intelligence", "Portfolio", "Re-Entry", "Risk",
            "Active Trader", "Research Intelligence", "Agents", "Reports",
        ],
    }
    return body


def watch_filters() -> dict[str, Any]:
    """Facet options for the unified filter toolbar."""
    from lib.watchlist_intelligence import list_intelligence, DEFAULT_PRIORITY

    raw = list_intelligence(symbols=list(DEFAULT_PRIORITY) + sorted(_starred_set())[:20], limit=80, priority_only=False)
    cards = raw.get("cards") or []
    sectors = sorted({c.get("sector") for c in cards if c.get("sector")})
    industries = sorted({c.get("industry") for c in cards if c.get("industry")})
    instruments = sorted({c.get("instrument_type") or "stock" for c in cards})
    states = sorted({c.get("trade_ai_state") for c in cards if c.get("trade_ai_state")})
    ratings = ["STRONG BUY", "BUY", "HOLD", "SELL", "NOT RATED"]
    return {
        "ok": True,
        "snapshot_id": _snapshot_id({"f": "filters", "t": _now()[:13]}),
        "generated_at": _now(),
        "data_contract_version": CONTRACT_VERSION,
        "provider_calls": 0,
        "views": list(VIEWS),
        "street_ratings": ratings,
        "trade_ai_states": states or ["WAIT", "READY", "MANAGING", "DETERMINISTIC_FAIL", "BLOCKED", "DATA_UNAVAILABLE"],
        "sectors": sectors,
        "industries": industries,
        "instruments": instruments,
        "origins": ["screener_find", "directive", "personal", "all"],
        "review_statuses": ["COMPLETE", "NOT_RUN"],
        "sorts": ["watch_rank", "street_rating", "day_change", "upside", "symbol"],
        "counts": {
            "starred": len(_starred_set()),
            "held": len(_held_set()),
            "screener": len(_screener_origin_set()),
        },
    }


def watch_lists() -> dict[str, Any]:
    """Saved lists / directive labels (bounded)."""
    lists: list[dict] = []
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute(
            """
            SELECT label, count(*) AS n
              FROM watch_directives
             WHERE kind='ticker' AND label IS NOT NULL AND label <> ''
             GROUP BY label
             ORDER BY n DESC
             LIMIT 80
            """
        )
        for r in cur.fetchall() or []:
            if hasattr(r, "keys"):
                lists.append({"id": r["label"], "label": r["label"], "count": r["n"], "source": "watch_directives"})
            else:
                lists.append({"id": r[0], "label": r[0], "count": r[1], "source": "watch_directives"})
    except Exception:
        pass
    return {
        "ok": True,
        "snapshot_id": _snapshot_id({"lists": len(lists)}),
        "generated_at": _now(),
        "data_contract_version": CONTRACT_VERSION,
        "provider_calls": 0,
        "items": lists,
        "starred_count": len(_starred_set()),
    }


def watch_reviews(symbol: str) -> dict[str, Any]:
    from lib.watchlist_intelligence import reviews_intelligence
    raw = reviews_intelligence(symbol)
    return {
        "ok": True,
        "snapshot_id": _snapshot_id({"sym": symbol.upper(), "n": raw.get("complete_count")}),
        "generated_at": _now(),
        "data_contract_version": CONTRACT_VERSION,
        "provider_calls": 0,
        "paid_flags_enabled": False,
        "symbol": symbol.upper(),
        "counts": {"total": raw.get("count"), "complete": raw.get("complete_count")},
        "items": raw.get("reviews") or [],
        "source_status": {"reviews": "ok"},
    }

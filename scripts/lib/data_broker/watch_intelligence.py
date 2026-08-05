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
    from lib.data_broker.watch_domains import membership_starred
    return membership_starred()


def _screener_origin_set() -> set[str]:
    from lib.data_broker.watch_domains import membership_screener
    return membership_screener()


def _held_set() -> set[str]:
    from lib.data_broker.watch_domains import membership_held
    held, _src = membership_held()
    return held


def _held_source() -> str:
    from lib.data_broker.watch_domains import membership_held
    _held, src = membership_held()
    return src


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
        # Always include symbols with authorized COMPLETE reviews (canary / operator proof)
        try:
            from lib.data_broker.watch_domains import ARTIFACTS
            if ARTIFACTS.exists():
                for path in ARTIFACTS.glob("*_maria.json"):
                    sym = path.name.split("_", 1)[0].upper()
                    if sym and sym not in base:
                        base.append(sym)
                for path in ARTIFACTS.glob("*_cio.json"):
                    sym = path.name.split("_", 1)[0].upper()
                    if sym and sym not in base:
                        base.append(sym)
        except Exception:
            pass
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
            # repair_queue: data failures / stale / pending review evidence
            from lib.data_broker.watch_domains import REPAIR_QUEUE
            st = (c.get("trade_ai_state") or "").upper()
            quote_bad = c.get("freshness_state") in ("DATA_UNAVAILABLE", "STALE") or c.get("last") is None
            if st not in REPAIR_QUEUE and not quote_bad and c.get("company_summary"):
                continue
        if view == "needs_review":
            cio = (c.get("cio_review") or {}).get("status")
            maria = (c.get("maria_review") or {}).get("status")
            if cio == "COMPLETE" and maria == "COMPLETE":
                continue
        if view == "reviewed_today":
            from lib.data_broker.watch_domains import completed_today
            cio = c.get("cio_review") or {}
            maria = c.get("maria_review") or {}
            ok_today = (
                (cio.get("status") == "COMPLETE" and completed_today(cio.get("completed_at")))
                or (maria.get("status") == "COMPLETE" and completed_today(maria.get("completed_at")))
            )
            if not ok_today:
                continue
        if view == "avoid":
            # excluded tier: AVOID / BLOCKED / DETERMINISTIC_FAIL
            from lib.data_broker.watch_domains import EXCLUDED_TOP
            st = (c.get("trade_ai_state") or "").upper()
            if st not in EXCLUDED_TOP:
                continue
        if view == "near_trigger":
            from lib.data_broker.watch_domains import near_trigger_eval
            nt = c.get("near_trigger") or near_trigger_eval(c)
            if not nt.get("is_near"):
                continue
        if view == "top_ideas":
            # Eligible-only ranking applied after this filter pass
            pass

        if starred_only and not c.get("starred"):
            continue
        if held_only and not c.get("held"):
            continue
        if origin in ("screener_find", "screener_finds", "screener") and not c.get("screener_origin"):
            continue

        # Extended filters
        list_id = str(q.get("saved_list") or q.get("list_id") or "").strip()
        if list_id:
            from lib.data_broker.watch_domains import saved_list_membership
            if (c.get("symbol") or "").upper() not in saved_list_membership(list_id):
                continue
        industry = (q.get("industry") or "").strip().lower()
        if industry and (c.get("industry") or "").lower() != industry:
            continue
        instrument = (q.get("instrument") or q.get("instrument_type") or "").strip().lower()
        if instrument and (c.get("instrument_type") or "stock").lower() != instrument:
            continue
        review_agent = (q.get("review_agent") or "").strip().lower()
        if review_agent:
            rev = c.get(f"{review_agent}_review") or {}
            if rev.get("status") != "COMPLETE":
                continue
        provider = (q.get("provider") or "").strip().lower()
        if provider:
            ok_p = False
            for key in ("cio_review", "maria_review"):
                r = c.get(key) or {}
                if r.get("status") == "COMPLETE" and str(r.get("provider") or "").lower() == provider:
                    ok_p = True
            if not ok_p:
                continue
        model = (q.get("model") or "").strip().lower()
        if model:
            ok_m = False
            for key in ("cio_review", "maria_review"):
                r = c.get(key) or {}
                if r.get("status") == "COMPLETE" and str(r.get("model") or "").lower() == model:
                    ok_m = True
            if not ok_m:
                continue
        freshness = (q.get("freshness") or "").strip().upper()
        if freshness and (c.get("freshness_state") or "").upper() != freshness:
            continue
        material = str(q.get("material_change") or "").lower()
        if material in ("1", "true", "yes") and not c.get("material_change"):
            continue
        if material in ("0", "false", "no") and c.get("material_change"):
            continue
        cio_view = (q.get("cio_view") or "").strip().upper()
        if cio_view:
            verdict = str((c.get("cio_review") or {}).get("verdict") or "").upper()
            if cio_view not in verdict and (c.get("cio_review") or {}).get("status") != "COMPLETE":
                continue
            if cio_view and (c.get("cio_review") or {}).get("status") == "COMPLETE" and cio_view not in verdict:
                # allow substring match on summary
                summary = str((c.get("cio_review") or {}).get("summary") or "").upper()
                if cio_view not in summary:
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


def _enrich_card_semantics(card: dict, *, enrich: dict, held_source: str) -> dict:
    """Broker-owned presentation fields: absolute vs relative, near-trigger, material change.

    Review dispositions always go through load_review_artifacts so quarantine
    (UNVERIFIED_OPERATOR_AUTHORIZATION) cannot be masked by NMC/legacy.
    Material fingerprints are read-only on GET (never written here).
    """
    from lib.data_broker.watch_domains import (
        absolute_performance,
        relative_performance_gaps,
        near_trigger_eval,
        material_fingerprint,
        material_change_vs_prior,
        load_review_artifacts,
        completed_today,
        dimensional_freshness,
        rank_eligibility,
        RANK_VERSION,
    )
    c = dict(card)
    # Re-bind reviews through durable disposition projection (quarantine wins)
    arts = load_review_artifacts(c.get("symbol") or "")
    for agent, key in (("cio", "cio_review"), ("maria", "maria_review")):
        if agent in arts:
            a = arts[agent]
            if a.get("status") == "COMPLETE" and a.get("artifact_disposition") == "COMPLETE":
                c[key] = {
                    "status": "COMPLETE",
                    "reason_code": None,
                    "artifact_disposition": "COMPLETE",
                    "summary": a.get("summary"),
                    "verdict": a.get("verdict"),
                    "provider": a.get("provider"),
                    "model": a.get("model"),
                    "policy": a.get("executed_policy") or a.get("requested_policy"),
                    "process_id": a.get("process_id"),
                    "completed_at": a.get("completed_at"),
                    "estimated_cost_usd": a.get("estimated_cost_usd"),
                    "display": a.get("display") or {
                        "label": f"{agent.upper()} REVIEW: COMPLETE",
                        "provider": str(a.get("provider") or "").upper(),
                        "model": a.get("model"),
                        "policy": a.get("executed_policy"),
                        "cost": f"${float(a.get('estimated_cost_usd') or 0):.5f}",
                        "reason": None,
                        "disposition": "COMPLETE",
                    },
                }
            else:
                # NOT_RUN path — keep reason_code + artifact_disposition visible
                c[key] = {
                    "agent_id": agent,
                    "status": "NOT_RUN",
                    "reason_code": a.get("reason_code") or "NOT_SCHEDULED",
                    "artifact_disposition": a.get("artifact_disposition") or "NOT_SCHEDULED",
                    "provider": None,
                    "model": None,
                    "policy": "NO_CALL",
                    "requested_policy": "NO_CALL",
                    "executed_policy": "NO_CALL",
                    "estimated_cost_usd": 0.0,
                    "fallback_used": False,
                    "display": a.get("display") or {
                        "label": f"{agent.upper()} REVIEW: NOT RUN",
                        "provider": "NONE",
                        "model": "NONE",
                        "policy": "NO_CALL",
                        "cost": "$0",
                        "reason": a.get("reason_code"),
                        "disposition": a.get("artifact_disposition"),
                    },
                }
        else:
            prev = c.get(key) or {}
            if prev.get("status") == "COMPLETE" and not prev.get("authorization_event_id"):
                c[key] = {
                    "status": "NOT_RUN",
                    "reason_code": "UNVERIFIED_OPERATOR_AUTHORIZATION",
                    "artifact_disposition": "AUTHORIZATION_REJECTED",
                    "provider": None,
                    "model": None,
                    "policy": "NO_CALL",
                    "estimated_cost_usd": 0.0,
                    "display": {
                        "label": f"{key.split('_')[0].upper()} REVIEW: NOT RUN",
                        "provider": "NONE",
                        "model": "NONE",
                        "policy": "NO_CALL",
                        "cost": "$0",
                        "reason": "UNVERIFIED_OPERATOR_AUTHORIZATION",
                        "disposition": "AUTHORIZATION_REJECTED",
                    },
                }

    abs_perf = absolute_performance(enrich or {})
    rel_gap = relative_performance_gaps()
    c["absolute_performance"] = abs_perf
    c["absolute_performance_summary"] = abs_perf.get("summary")
    # Do not label absolute as relative
    c["relative_performance_summary"] = None
    c["relative_vs_industry"] = None
    c["relative_vs_sector"] = None
    c["relative_vs_spy"] = None
    c["relative_performance_quality"] = "UNAVAILABLE"
    c["relative_performance_note"] = rel_gap.get("note")
    # News / catalyst projection (DB + optional async agent artifact; never provider calls)
    try:
        from lib.data_broker.news_intelligence import project_catalyst_context
        catx = project_catalyst_context(c)
        c["catalyst_summary"] = catx.get("catalyst_summary") or c.get("catalyst_summary")
        c["catalyst_as_of"] = catx.get("catalyst_as_of")
        c["catalyst_freshness"] = catx.get("catalyst_freshness") or "MISSING"
        c["catalyst_type"] = catx.get("catalyst_type")
        c["catalyst_severity"] = catx.get("catalyst_severity")
        c["catalyst_source_mix"] = catx.get("catalyst_source_mix") or []
        c["latest_headlines"] = catx.get("latest_headlines") or []
        c["catalyst_oversight_status"] = catx.get("catalyst_oversight_status")
        c["catalyst_worker_status"] = catx.get("catalyst_worker_status")
        c["catalyst_vs_industry"] = catx.get("catalyst_vs_industry")
        c["catalyst_vs_industry_quality"] = catx.get("catalyst_vs_industry_quality") or "UNAVAILABLE"
        c["catalyst_vs_industry_note"] = "Catalyst-versus-industry not joined"
    except Exception:
        c["catalyst_vs_industry"] = None
        c["catalyst_vs_industry_quality"] = "UNAVAILABLE"
        c["catalyst_vs_industry_note"] = "Catalyst-versus-industry not joined"
        c.setdefault("catalyst_freshness", "MISSING" if not c.get("catalyst_summary") else "STALE")

    nt = near_trigger_eval(c)
    c["near_trigger"] = nt
    c["is_near_trigger"] = bool(nt.get("is_near"))

    fp = material_fingerprint(c)
    c["material_fingerprint"] = fp
    # READ-ONLY: never mkdir/write fingerprints on GET
    c["material_change"] = material_change_vs_prior(c.get("symbol") or "", fp)

    # Dimensional freshness — never a generic whole-card CURRENT chip
    dims = dimensional_freshness(c)
    c["quote_freshness"] = dims.get("quote_freshness")
    c["technical_freshness"] = dims.get("technical_freshness")
    c["decision_freshness"] = dims.get("decision_freshness")
    c["street_freshness"] = dims.get("street_freshness")
    c["review_freshness"] = dims.get("review_freshness")
    c["freshness_dimensions"] = dims
    # Keep quote-level freshness_state; do not promote it as whole-card label
    c["card_freshness_label"] = None

    # Decision input price vs current quote (when risk references historical price)
    c["current_quote"] = c.get("last")
    c["current_quote_as_of"] = c.get("price_as_of")
    decision_input_price = c.get("decision_input_price") or c.get("decision_price") or c.get("packet_price")
    decision_input_as_of = c.get("decision_input_as_of") or c.get("decision_as_of") or c.get("packet_as_of")
    # Parse risk text for "$X.XX" when explicit fields absent (display only)
    if decision_input_price is None:
        risk = str(c.get("primary_risk") or "")
        import re
        m = re.search(r"\$(\d+(?:\.\d+)?)", risk)
        if m:
            try:
                decision_input_price = float(m.group(1))
            except ValueError:
                decision_input_price = None
    c["decision_input_price"] = decision_input_price
    c["decision_input_as_of"] = decision_input_as_of

    # Separate next review fields
    raw_next = c.get("next_review_time") or c.get("next_deterministic_review_condition")
    c["next_review_condition"] = raw_next if raw_next and not str(raw_next).endswith("Z") and "T" not in str(raw_next)[:20] else None
    c["next_review_at"] = raw_next if raw_next and ("T" in str(raw_next) or str(raw_next).endswith("Z")) else None
    if c.get("next_review_at") and c.get("next_review_condition") is None and " " in str(raw_next) and "T" not in str(raw_next):
        c["next_review_condition"] = raw_next
        c["next_review_at"] = None
    c["review_sla_state"] = "UNKNOWN"
    ages = []
    for key in ("cio_review", "maria_review"):
        r = c.get(key) or {}
        if r.get("status") == "COMPLETE" and r.get("completed_at"):
            ages.append(str(r.get("completed_at")))
    c["review_completed_at"] = max(ages) if ages else None
    c["reviewed_today"] = any(
        completed_today((c.get(k) or {}).get("completed_at"))
        for k in ("cio_review", "maria_review")
        if (c.get(k) or {}).get("status") == "COMPLETE"
    )

    street = c.get("street_consensus") or {}
    c["target_mean"] = c.get("target_mean") if c.get("target_mean") is not None else street.get("target_mean")
    c["implied_upside_pct"] = c.get("implied_upside_pct") if c.get("implied_upside_pct") is not None else street.get("implied_upside_pct")
    c["latest_analyst_action"] = None
    c["latest_analyst_action_quality"] = "UNAVAILABLE"
    c["position_source"] = held_source
    c["data_quality_note"] = "relative and business-model domains typed unavailable until broker providers land"

    elig, excl = rank_eligibility(c.get("trade_ai_state"))
    c.setdefault("rank_eligibility", elig)
    c.setdefault("rank_exclusion_reason", excl)
    c.setdefault("rank_version", RANK_VERSION)

    # Review schedule / SLA / next-run fields (no provider calls)
    try:
        from lib.watch_review_pipeline import review_freshness_fields, enrich_review_display
        rf = review_freshness_fields(c)
        c.update(rf)
        for agent, key in (("cio", "cio_review"), ("maria", "maria_review")):
            c[key] = enrich_review_display(c.get(key) or {}, agent=agent, card=c)
        # Prefer structured next review timestamps
        c["next_review_at"] = c.get("next_maria_review_at") or c.get("next_review_at")
    except Exception:
        pass
    return c


def list_watch_intelligence(query: dict | None = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/watch-intelligence — broker projection compose path.

    Dependency direction (target):
      watch_domains + existing broker modules → this projection → API → React

    Still uses list_intelligence for Trade AI / street / quote assembly until those
    domains are fully split; membership, ranking, near-trigger, review auth, and
    quality live in watch_domains.
    """
    from lib.watchlist_intelligence import list_intelligence
    from lib.data_broker.watch_domains import (
        rank_top_ideas,
        content_snapshot_id,
        assess_data_quality,
        enrichment_batch,
        DIRECT_DEPENDENCIES,
        RANK_VERSION,
    )

    q = dict(query or {})
    view = (q.get("view") or "top_ideas").lower()
    if view not in VIEWS:
        view = "top_ideas"
    page = max(1, int(q.get("page") or 1))
    page_size = min(100, max(1, int(q.get("page_size") or q.get("limit") or 40)))
    sort = str(q.get("sort") or "watch_rank")

    # Universe from membership domains — not DEFAULT_PRIORITY as production rank
    syms = _universe_symbols(view="all" if view == "top_ideas" else view, page_size=max(page_size, 80))
    raw = list_intelligence(symbols=syms, limit=len(syms) or 1, priority_only=False, offset=0)
    cards = raw.get("cards") or []

    starred = _starred_set()
    screener = _screener_origin_set()
    held = _held_set()
    held_source = _held_source()
    enrich_map = enrichment_batch([c.get("symbol") for c in cards if c.get("symbol")])

    items = []
    for c in cards:
        sym = (c.get("symbol") or "").upper()
        c = _enrich_card_semantics(
            {**c, "starred": sym in starred, "held": sym in held, "screener_origin": sym in screener},
            enrich=enrich_map.get(sym) or {},
            held_source=held_source,
        )
        it = _card_to_broker_item(c, starred=sym in starred, screener=sym in screener)
        it["card"] = c
        it["domains"]["WatchMembership"]["starred"] = field(sym in starred, source="operator_starred_symbols")
        it["domains"]["WatchMembership"]["screener_origin"] = field(sym in screener, source="screener_find_pins|watchlist_items.source")
        it["domains"]["PositionContext"] = {
            "held": field(sym in held, source=held_source),
            "source": field(held_source, source="data_broker.watch_domains.membership_held"),
        }
        # Absolute vs relative labels
        it["domains"]["RelativePerformance"] = {
            "absolute_summary": field(c.get("absolute_performance_summary"), source="enrichment_cache", quality_state="VALID" if c.get("absolute_performance_summary") else "UNAVAILABLE"),
            "versus_industry": field(None, source=None, quality_state="UNAVAILABLE"),
            "versus_sector": field(None, source=None, quality_state="UNAVAILABLE"),
            "versus_spy": field(None, source=None, quality_state="UNAVAILABLE"),
            "note": field(c.get("relative_performance_note"), source="broker"),
        }
        items.append(it)

    # Apply non-view ranking filters first (view=top_ideas filters after rank)
    filter_q = {**q, "view": "all" if view == "top_ideas" else view}
    filtered = _apply_filters(items, filter_q)

    if view == "top_ideas":
        ranked = rank_top_ideas(filtered)
        # Top Ideas = top ranked slice (dynamic), not DEFAULT_PRIORITY
        sorted_items = ranked
        sort = f"rank:{RANK_VERSION}"
    elif view == "near_trigger":
        sorted_items = _apply_filters(items, {**q, "view": "near_trigger"})
        sorted_items = _sort_items(sorted_items, sort)
    else:
        sorted_items = _apply_filters(items, {**q, "view": view})
        sorted_items = _sort_items(sorted_items, sort)

    total = len(sorted_items)
    start = (page - 1) * page_size
    page_items = sorted_items[start : start + page_size]
    quality = assess_data_quality(page_items)

    counts = {
        "total_matched": total,
        "page": page,
        "page_size": page_size,
        "starred_universe": len(starred),
        "held_universe": len(held),
        "screener_universe": len(screener),
        "street_strong_buy": sum(1 for i in sorted_items if (i.get("card") or {}).get("street_rating") == "STRONG BUY"),
        "street_buy": sum(1 for i in sorted_items if (i.get("card") or {}).get("street_rating") == "BUY"),
        "trade_ai_wait": sum(1 for i in sorted_items if (i.get("card") or {}).get("trade_ai_state") == "WAIT"),
        "proposal_eligible": sum(1 for i in sorted_items if (i.get("card") or {}).get("proposal_allowed")),
        "complete_reviews": sum(
            1 for i in sorted_items
            if (i.get("card") or {}).get("cio_review", {}).get("status") == "COMPLETE"
            or (i.get("card") or {}).get("maria_review", {}).get("status") == "COMPLETE"
        ),
        "near_trigger": sum(1 for i in items if (i.get("card") or {}).get("is_near_trigger")),
        "material_change": sum(1 for i in sorted_items if (i.get("card") or {}).get("material_change")),
    }

    cards_out = [i.get("card") for i in page_items]
    snap = content_snapshot_id(page_items, view=view, query=q)

    body = {
        "ok": True,
        "snapshot_id": snap,
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
            "domains_module": "lib.data_broker.watch_domains",
            "position_source": held_source,
            "canonical_quotes": "watch_canonical_quote",
            "street_consensus": "yahoo + analyst_rollup",
            "provider_calls": 0,
        },
        "data_quality_status": quality.get("status"),
        "data_quality": quality,
        "counts": counts,
        "items": page_items,
        "cards": cards_out,
        "summary": {
            "street_strong_buy": counts["street_strong_buy"],
            "street_buy": counts["street_buy"],
            "trade_ai_wait": counts["trade_ai_wait"],
            "blocked_or_unavailable": sum(
                1 for i in sorted_items
                if (i.get("card") or {}).get("trade_ai_state") in (
                    "BLOCKED", "DATA_UNAVAILABLE", "DETERMINISTIC_FAIL", "STALE", "AVOID"
                )
            ),
            "managing_held": sum(1 for i in sorted_items if (i.get("card") or {}).get("held") or (i.get("card") or {}).get("trade_ai_state") == "MANAGING"),
            "proposal_eligible": counts["proposal_eligible"],
        },
        "flags": {
            "watch_intelligence_primary": True,
            "watch_legacy_hidden": True,
            "watch_deepseek_flash_enabled": False,
            "watch_cio_daily_enabled": False,
            "ceco_artifacts_quarantined": True,
        },
        "consumers": [
            "Watch Intelligence", "Portfolio", "Re-Entry", "Risk",
            "Active Trader", "Research Intelligence", "Agents", "Reports",
        ],
        "data_broker": {
            "package": "scripts/lib/data_broker",
            "projection": "watch_intelligence",
            "domains": "lib.data_broker.watch_domains",
            "contract_version": CONTRACT_VERSION,
            "catalog": "/api/v3/data-broker",
            "dependency_direction": "watch_domains → watch_intelligence projection → API → React",
            "direct_dependencies": DIRECT_DEPENDENCIES,
            "read_only": True,
            "provider_calls": 0,
        },
        "rank_version": RANK_VERSION if view == "top_ideas" else None,
    }
    return body


def compose_broker_item(symbol: str, *, card: dict | None = None) -> dict[str, Any]:
    """Canonical broker item for one symbol — shared by list and detail.

    Applies membership, review disposition, dimensional freshness, absolute
    performance, and read-only material-change comparison. Zero provider calls.
    """
    from lib.watchlist_intelligence import list_intelligence
    from lib.data_broker.watch_domains import enrichment_batch, assess_data_quality

    sym = symbol.upper()
    if card is None:
        raw = list_intelligence(symbols=[sym], limit=1, priority_only=False, offset=0)
        cards = raw.get("cards") or []
        card = next((c for c in cards if (c.get("symbol") or "").upper() == sym), None)
        if not card and cards:
            card = cards[0]
        if not card:
            return {"ok": False, "error": "symbol_not_found", "symbol": sym}

    starred = sym in _starred_set()
    screener = sym in _screener_origin_set()
    held = sym in _held_set()
    held_source = _held_source()
    enrich_map = enrichment_batch([sym])
    c = _enrich_card_semantics(
        {**card, "symbol": sym, "starred": starred, "held": held, "screener_origin": screener},
        enrich=enrich_map.get(sym) or {},
        held_source=held_source,
    )
    it = _card_to_broker_item(c, starred=starred, screener=screener)
    it["card"] = c
    it["domains"]["WatchMembership"]["starred"] = field(starred, source="operator_starred_symbols")
    it["domains"]["WatchMembership"]["screener_origin"] = field(
        screener, source="screener_find_pins|watchlist_items.source"
    )
    it["domains"]["PositionContext"] = {
        "held": field(held, source=held_source),
        "source": field(held_source, source="data_broker.watch_domains.membership_held"),
    }
    it["domains"]["RelativePerformance"] = {
        "absolute_summary": field(
            c.get("absolute_performance_summary"),
            source="enrichment_cache",
            quality_state="VALID" if c.get("absolute_performance_summary") else "UNAVAILABLE",
        ),
        "versus_industry": field(None, source=None, quality_state="UNAVAILABLE"),
        "versus_sector": field(None, source=None, quality_state="UNAVAILABLE"),
        "versus_spy": field(None, source=None, quality_state="UNAVAILABLE"),
        "note": field(c.get("relative_performance_note"), source="broker"),
    }
    it["domains"]["FreshnessDimensions"] = {
        "quote": field(c.get("quote_freshness"), source="watch_canonical_quote"),
        "technical": field(c.get("technical_freshness"), source="decision_packet|risk"),
        "decision": field(c.get("decision_freshness"), source="trade_ai_state"),
        "street": field(c.get("street_freshness"), source="yahoo/analyst_rollup"),
        "review": field(c.get("review_freshness"), source="review_artifacts"),
    }
    quality = assess_data_quality([it])
    return {
        "ok": True,
        "symbol": sym,
        "item": it,
        "card": c,
        "quality": quality,
        "held_source": held_source,
    }


def detail_watch_intelligence(symbol: str) -> dict[str, Any]:
    """GET detail — same canonical composer as list (no hard-coded OK, no generated_at snapshot)."""
    from lib.data_broker.watch_domains import content_snapshot_id, DIRECT_DEPENDENCIES
    from lib.watchlist_intelligence import detail_intelligence

    composed = compose_broker_item(symbol)
    if not composed.get("ok"):
        return {
            "ok": False,
            "error": composed.get("error") or "unavailable",
            "symbol": symbol.upper(),
            "provider_calls": 0,
            "paid_flags_enabled": False,
            "broker_write_authority": "NONE",
            "data_contract_version": CONTRACT_VERSION,
            "generated_at": _now(),
        }

    item = composed["item"]
    card = composed["card"]
    quality = composed["quality"]
    # Full package for symbol page (legacy detail envelope) — still no providers
    raw = detail_intelligence(symbol)
    # Prefer broker-enriched card over raw for parity fields
    if isinstance(raw, dict) and raw.get("ok"):
        raw = dict(raw)
        raw["card"] = card

    snap = content_snapshot_id(
        [item],
        view="detail",
        query={"symbol": symbol.upper()},
    )
    body = {
        "ok": True,
        "snapshot_id": snap,
        "generated_at": _now(),
        "data_contract_version": CONTRACT_VERSION,
        "contract_version": CONTRACT_VERSION,
        "provider_calls": 0,
        "paid_flags_enabled": False,
        "broker_write_authority": "NONE",
        "source_status": {
            "detail": "ok",
            "provider_calls": 0,
            "composer": "compose_broker_item",
            "position_source": composed.get("held_source"),
        },
        "data_quality_status": quality.get("status"),
        "data_quality": quality,
        "counts": {"domains": len(item.get("domains") or {})},
        "symbol": symbol.upper(),
        "item": item,
        "card": card,
        "detail": raw if isinstance(raw, dict) else {"ok": True, "card": card},
        "domains": item.get("domains"),
        "data_broker": {
            "package": "scripts/lib/data_broker",
            "projection": "watch_intelligence",
            "domains": "lib.data_broker.watch_domains",
            "contract_version": CONTRACT_VERSION,
            "catalog": "/api/v3/data-broker",
            "dependency_direction": "watch_domains → watch_intelligence projection → API → React",
            "direct_dependencies": DIRECT_DEPENDENCIES,
            "read_only": True,
            "provider_calls": 0,
        },
        "consumers": [
            "Watch Intelligence", "Portfolio", "Re-Entry", "Risk",
            "Active Trader", "Research Intelligence", "Agents", "Reports",
        ],
    }
    return body


def watch_filters() -> dict[str, Any]:
    """Filter catalog with id/label/options/source/generated_at.

    Provider/model options derive ONLY from authorized COMPLETE artifacts —
    never hard-coded when zero authorized completes exist.
    Unavailable controls stay disabled with explanations.
    """
    from lib.watchlist_intelligence import list_intelligence
    from lib.data_broker.watch_domains import (
        saved_lists_canonical,
        authorized_complete_providers_models,
    )

    sample = sorted(_starred_set() | _held_set() | _screener_origin_set())[:40]
    from lib.watchlist_intelligence import DEFAULT_PRIORITY
    sample = list(dict.fromkeys(sample + list(DEFAULT_PRIORITY)))
    raw = list_intelligence(symbols=sample, limit=len(sample) or 1, priority_only=False)
    cards = raw.get("cards") or []
    sectors = sorted({c.get("sector") for c in cards if c.get("sector")})
    industries = sorted({c.get("industry") for c in cards if c.get("industry")})
    instruments = sorted({c.get("instrument_type") or "stock" for c in cards})
    states = sorted({c.get("trade_ai_state") for c in cards if c.get("trade_ai_state")})
    providers, models = authorized_complete_providers_models()
    lists = saved_lists_canonical()
    gen = _now()

    def filt(fid, label, options, source, applicability="all", *, enabled=True, note=None):
        return {
            "id": fid,
            "label": label,
            "options": options,
            "counts": None,
            "applicability": applicability,
            "source": source,
            "generated_at": gen,
            "enabled": enabled,
            "note": note,
        }

    unavailable = "typed unavailable until broker provider lands"
    filters = [
        filt("view", "View", list(VIEWS), "watch_intelligence"),
        filt("street_rating", "Street rating", ["STRONG BUY", "BUY", "HOLD", "SELL", "NOT RATED"], "yahoo/analyst_rollup"),
        filt(
            "trade_ai_state",
            "Trade AI state",
            states or ["WAIT", "READY", "MANAGING", "DETERMINISTIC_FAIL", "BLOCKED", "DATA_UNAVAILABLE"],
            "decision_packets",
        ),
        filt("sector", "Sector", sectors, "symbol_profiles"),
        filt("industry", "Industry", industries, "symbol_profiles"),
        filt("instrument", "Instrument", instruments, "symbol_profiles"),
        filt("origin", "Origin", ["screener_find"], "screener_find_pins"),
        filt(
            "saved_list",
            "Saved list",
            [x.get("id") for x in lists],
            "canonical_lists",
            enabled=bool(lists),
            note=None if lists else "No canonical saved-list membership on host",
        ),
        filt("review_status", "Review status", ["COMPLETE", "NOT_RUN"], "review_artifacts"),
        filt("review_agent", "Review agent", ["cio", "maria"], "review_artifacts"),
        filt(
            "provider",
            "Provider",
            providers,
            "authorized COMPLETE review artifacts only",
            enabled=bool(providers),
            note=None if providers else "No authorized COMPLETE review artifacts — options empty",
        ),
        filt(
            "model",
            "Model",
            models,
            "authorized COMPLETE review artifacts only",
            enabled=bool(models),
            note=None if models else "No authorized COMPLETE review artifacts — options empty",
        ),
        filt(
            "freshness",
            "Quote freshness",
            ["CURRENT", "PREMARKET_CURRENT", "AFTER_HOURS_CURRENT", "STALE", "DATA_UNAVAILABLE"],
            "canonical_quote",
        ),
        filt("material_change", "Material change", ["1", "0"], "material_fingerprint"),
        filt(
            "cio_view",
            "CIO view",
            ["ADD", "HOLD", "AVOID", "WATCH", "RESEARCH"],
            "cio_review.verdict",
            enabled=bool(providers),
            note=None if providers else "No authorized COMPLETE CIO reviews",
        ),
        filt("starred", "Starred only", ["1"], "operator_starred_symbols"),
        filt("held", "Held only", ["1"], "portfolio_snapshot|holdings_fallback"),
        filt("sort", "Sort", ["watch_rank", "street_rating", "day_change", "upside", "symbol"], "projection"),
        # Typed unavailable — keep disabled with explanation
        filt("catalyst_window", "Catalyst window", [], "not_implemented", enabled=False, note=unavailable),
        filt("earnings_window", "Earnings window", [], "not_implemented", enabled=False, note=unavailable),
        filt("relative_strength_band", "Relative-strength band", [], "not_implemented", enabled=False, note=unavailable),
        filt("valuation_band", "Valuation band", [], "not_implemented", enabled=False, note=unavailable),
    ]
    return {
        "ok": True,
        "snapshot_id": _snapshot_id({"filters": [f["id"] for f in filters], "n": len(filters), "providers": providers, "models": models}),
        "generated_at": gen,
        "data_contract_version": CONTRACT_VERSION,
        "provider_calls": 0,
        "views": list(VIEWS),
        "filters": filters,
        "street_ratings": ["STRONG BUY", "BUY", "HOLD", "SELL", "NOT RATED"],
        "trade_ai_states": states or ["WAIT", "READY", "MANAGING", "DETERMINISTIC_FAIL", "BLOCKED", "DATA_UNAVAILABLE"],
        "sectors": sectors,
        "industries": industries,
        "instruments": instruments,
        "origins": ["screener_find"],
        "review_statuses": ["COMPLETE", "NOT_RUN"],
        "providers": providers,
        "models": models,
        "saved_lists": [x.get("id") for x in lists],
        "cio_views": ["ADD", "HOLD", "AVOID", "WATCH", "RESEARCH"] if providers else [],
        "sorts": ["watch_rank", "street_rating", "day_change", "upside", "symbol"],
        "unavailable_filters": [
            {"id": "catalyst_window", "note": unavailable},
            {"id": "earnings_window", "note": unavailable},
            {"id": "relative_strength_band", "note": unavailable},
            {"id": "valuation_band", "note": unavailable},
        ],
        "counts": {
            "starred": len(_starred_set()),
            "held": len(_held_set()),
            "screener": len(_screener_origin_set()),
            "saved_lists": len(lists),
            "authorized_providers": len(providers),
            "authorized_models": len(models),
        },
    }


def watch_lists() -> dict[str, Any]:
    """Canonical saved lists only — not directive label substitution."""
    from lib.data_broker.watch_domains import saved_lists_canonical
    lists = saved_lists_canonical()
    return {
        "ok": True,
        "snapshot_id": _snapshot_id({"lists": [x.get("id") for x in lists]}),
        "generated_at": _now(),
        "data_contract_version": CONTRACT_VERSION,
        "provider_calls": 0,
        "items": lists,
        "canonical": True,
        "starred_count": len(_starred_set()),
        "note": None if lists else "No canonical saved-list membership table on host; directive labels intentionally not substituted",
        "quality_state": "VALID" if lists else "UNAVAILABLE",
    }


def watch_reviews(symbol: str) -> dict[str, Any]:
    """Reviews through durable disposition projection.

    Quarantine excluded from narrative/model/cost, but disposition remains visible:
      status=NOT_RUN, reason_code=UNVERIFIED_OPERATOR_AUTHORIZATION,
      artifact_disposition=QUARANTINED
    """
    from lib.data_broker.watch_domains import load_review_artifacts

    arts = load_review_artifacts(symbol)
    agents = ("cio", "maria", "sentinel", "steph", "risk", "grok", "chatgpt")
    items = []
    complete = 0
    quarantined = 0
    for a in agents:
        if a in arts:
            items.append(arts[a])
            if arts[a].get("status") == "COMPLETE":
                complete += 1
            if arts[a].get("artifact_disposition") == "QUARANTINED":
                quarantined += 1
        else:
            from lib.data_broker.watch_domains import _not_run_display
            items.append(_not_run_display(a, "NOT_SCHEDULED", disposition="NOT_SCHEDULED"))
    return {
        "ok": True,
        "snapshot_id": _snapshot_id({
            "sym": symbol.upper(),
            "n": complete,
            "q": quarantined,
            "agents": [(i.get("status"), i.get("reason_code"), i.get("artifact_disposition")) for i in items],
        }),
        "generated_at": _now(),
        "data_contract_version": CONTRACT_VERSION,
        "provider_calls": 0,
        "paid_flags_enabled": False,
        "symbol": symbol.upper(),
        "counts": {"total": len(items), "complete": complete, "quarantined": quarantined},
        "items": items,
        "source_status": {"reviews": "authorization_gated", "quarantine_excluded": True},
    }

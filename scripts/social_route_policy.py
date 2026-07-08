#!/usr/bin/env python3
"""social_route_policy.py — P0-5: deterministic routing for social-discovery candidates.

A social candidate is routed to EXACTLY ONE destination based on verified-catalyst status,
liquidity/float/price boundaries, and squeeze evidence. This is the single, testable place
that decides whether a social signal may become actionable and which strategy family owns it.

Hard rules (never violated):
  * An unverified / social-only candidate can NEVER route to GO — it is watch_only (WATCH/WAIT).
  * Large-float / squeeze candidates require MANUAL REVIEW (meme_squeeze_momentum), never auto-GO.
  * Missing/stale Finviz or missing RVOL → at most WAIT, never GO.
  * LLMs/social sentiment are advisory; this function is pure and deterministic.

    from social_route_policy import route_social_candidate
    r = route_social_candidate(candidate, finviz_data, catalyst_enrichment, trace_id="...")
"""
from __future__ import annotations

ROUTES = ("watch_only", "momentum_scalp", "meme_squeeze_momentum", "large_float_social_scout",
          "portfolio_agents", "reject")
# SCOUT (P0-2): an operator-awareness state for a social candidate that meets >=2 of the 5 Social
# Scout pillars but is NOT GO, NOT validation-fast-path eligible, NOT a standard momentum_scalp. It is
# strictly stronger-than-WATCH visibility, never tradeable.
ACTIONABILITY = ("WATCH", "WAIT", "SCOUT", "GO", "MANUAL_REVIEW", "AVOID")
FLOAT_CLASSES = ("micro_float", "large_float", "unknown")

# Micro-cap momentum-scalp boundaries (kept in sync with momentum_scalp.yaml screen_filters).
SCALP_MAX_FLOAT_M = 20.0
SCALP_MAX_PRICE = 25.0
SCALP_MIN_RVOL = 5.0
SQUEEZE_MIN_RVOL = 8.0
SQUEEZE_MIN_GAP = 5.0
# Large-float social scout (hybrid): a verified social/momentum name above the micro-cap ceiling
# is RETAINED for operator review — never a standard momentum_scalp, never auto-GO.
SCOUT_MAX_PRICE = 50.0
SCOUT_LABEL = "large_float_social_scout"

_PORTFOLIO_TAGS = {"dividend", "income", "retirement", "401k", "ira", "roth", "reit",
                   "bond", "core", "compounder", "defense", "long_term", "dividend_growth"}
_SQUEEZE_KEYWORDS = ("squeeze", "short squeeze", "gamma", "shorts", "short interest",
                     "days to cover", "dtc", "short float", "ftd", "naked short")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def catalyst_is_verified(catalyst_enrichment: dict) -> bool:
    """A catalyst is 'verified' if RAG- or Hermes-confirmed, flagged verified, or backed by credible news
    articles (SEC / news / analyst / press). Social mentions alone are NOT verification.

    NOTE (2026-07-08 fix): this previously read `catalyst`/`catalyst_source`, which build_catalyst_enrichment
    never sets — so news-backed setups were never 'verified' and the route always downgraded to
    SOCIAL_ONLY_UNVERIFIED (→ SCOUT, never GO), independent of the social-only cap. Read the keys the
    enrichment actually produces: `catalysts` (news_articles rows) and `hermes_catalyst_confirmed`."""
    ce = catalyst_enrichment or {}
    if ce.get("catalyst_verified") or ce.get("rag_catalyst_confirmed") or ce.get("hermes_catalyst_confirmed"):
        return True
    # Credible catalyst articles were actually found for this symbol (news_articles / Hermes) — not just
    # social keyword hits.
    if ce.get("catalysts") or ce.get("catalyst_tier") in ("high_impact", "medium_impact"):
        return True
    if ce.get("catalyst") and any(
        kw in str(ce.get("catalyst_source", "")).lower()
        for kw in ("sec", "news", "yahoo", "finnhub", "analyst", "press")):
        return True
    return False


def has_squeeze_evidence(candidate: dict, finviz: dict, catalyst_enrichment: dict) -> bool:
    """Large-float / short-squeeze signature: squeeze language, short-interest evidence, or a
    float well above the micro-cap scalp ceiling."""
    text = str((candidate or {}).get("sample_content") or "").lower()
    if any(kw in text for kw in _SQUEEZE_KEYWORDS):
        return True
    si = _num((finviz or {}).get("short_float")) or _num((finviz or {}).get("short_interest"))
    if si is not None and si >= 15:   # >=15% short float is squeeze-relevant
        return True
    if (catalyst_enrichment or {}).get("short_interest_evidence"):
        return True
    float_m = _num((finviz or {}).get("float_m"))
    if float_m is not None and float_m > SCALP_MAX_FLOAT_M:
        return True
    return False


def route_social_candidate(candidate: dict, finviz_data: dict,
                           catalyst_enrichment: dict, trace_id: str = None) -> dict:
    """Route one social candidate. Returns the documented routing dict. Pure / deterministic."""
    candidate = candidate or {}
    finviz = finviz_data or {}
    ce = catalyst_enrichment or {}
    reason_codes: list[str] = []

    price = _num(finviz.get("price"))
    rvol = _num(finviz.get("rvol") if finviz.get("rvol") is not None else finviz.get("relative_volume"))
    float_m = _num(finviz.get("float_m"))
    gap = _num(finviz.get("gap_pct"))
    tags = [str(t).lower() for t in (candidate.get("strategy_tags") or [])]
    verified = catalyst_is_verified(ce)

    # P0-2: evaluate the 5 Social Scout pillars (operator-awareness only — never makes anything
    # tradeable). Lazy import avoids a circular dependency (the pillar module imports this one).
    from social_scout_pillars import evaluate_social_scout_pillars
    scout = evaluate_social_scout_pillars(candidate, finviz, ce)

    evidence = {
        "symbol": candidate.get("symbol"),
        "price": price, "rvol": rvol, "float_m": float_m, "gap_pct": gap,
        "catalyst_verified": verified,
        "catalyst_source": ce.get("catalyst_source"),
        "mention_count": candidate.get("mention_count"),
        "sources": candidate.get("sources"),
    }

    float_class = "unknown" if float_m is None else ("micro_float" if float_m <= SCALP_MAX_FLOAT_M else "large_float")

    def result(route, actionability, strategy_id, requires_verified, social_only,
               scout_label=None, manual_review_required=False, operator_label=None):
        # P0-2: a candidate that meets >=2 pillars but is NOT GO surfaces as a Social Scout. The pill
        # never upgrades actionability into anything tradeable — at most WATCH/WAIT becomes SCOUT
        # (still non-tradeable). GO is never touched; a graduated GO suppresses the scout pill.
        count = scout["pillar_count"]
        is_go = actionability == "GO"
        # Scout surfacing is for "interesting, not there yet" lanes only — watch_only, large-float
        # scout, and meme-squeeze (all non-tradeable / manual-review). A terminal reject/AVOID or a
        # portfolio/income name is NOT a Social Scout, and a graduated GO suppresses the pill.
        _scoutable = route in ("watch_only", "large_float_social_scout", "meme_squeeze_momentum")
        is_scout = (count >= 2) and not is_go and _scoutable
        act = actionability
        if is_scout and act in ("WATCH", "WAIT"):
            act = "SCOUT"
        assert route in ROUTES and act in ACTIONABILITY

        if is_scout:
            if float_class == "large_float" or manual_review_required:
                operator_pill = f"SOCIAL SCOUT · LARGE FLOAT · {count}/5"
            else:
                operator_pill = f"SOCIAL SCOUT · {count}/5"
            scout_status = "SOCIAL_SCOUT"
            operator_subtitle = scout["operator_subtitle"]
            operator_color_token = scout["operator_color_token"]
            # Surface why it is a scout + what it still needs (drives operator tooltips).
            for rc in scout["reason_codes"] + scout["missing_reason_codes"]:
                if rc not in reason_codes:
                    reason_codes.append(rc)
        else:
            operator_pill = None
            scout_status = "NONE"
            operator_subtitle = None
            operator_color_token = None

        return {
            "route": route,
            "actionability": act,
            "strategy_id": strategy_id,
            "float_class": float_class,
            "scout_label": scout_label,
            "manual_review_required": manual_review_required,
            "operator_label": operator_label,
            "reason_codes": reason_codes,
            "requires_verified_catalyst": requires_verified,
            "social_only": social_only,
            "trace_id": trace_id,
            "evidence": evidence,
            "symbol": candidate.get("symbol"),
            # --- Social Scout operator-awareness fields (P0-2) ---
            "scout_status": scout_status,
            "scout_pillar_count": count,
            "pillar_count": count,
            "pillars_met": scout["pillars_met"],
            "pillars_missing": scout["pillars_missing"],
            "operator_pill": operator_pill,
            "operator_subtitle": operator_subtitle,
            "operator_color_token": operator_color_token,
            "operator_tooltip_hints": scout["operator_tooltip_hints"] if is_scout else [],
            # HARD: a Scout/non-GO surface is never tradeable or validation-ready. Only GO (decided by
            # this policy's own gates) is validation/tradeable-eligible via the normal path.
            "not_tradeable": not is_go,
            "not_validation_ready": not is_go,
        }

    # 1. Portfolio / income / retirement tags → portfolio agents (advisory, never a scalp).
    if any(t in _PORTFOLIO_TAGS for t in tags):
        reason_codes.append("PORTFOLIO_INCOME_TAG")
        return result("portfolio_agents", "MANUAL_REVIEW", None, requires_verified=False, social_only=False)

    # 2. Missing/stale Finviz or missing RVOL/price → cannot be actionable (never GO).
    if rvol is None or price is None:
        reason_codes.append("MISSING_FINVIZ_DATA")
        return result("watch_only", "WAIT", None, requires_verified=True, social_only=not verified)

    # 3. Verified-catalyst routes.
    if verified:
        squeeze = has_squeeze_evidence(candidate, finviz, ce)
        micro = float_m is not None and float_m <= SCALP_MAX_FLOAT_M
        large = float_m is not None and float_m > SCALP_MAX_FLOAT_M

        # 3a. MICRO-cap momentum scalp → momentum_scalp (GO eligible). Standard low-float scalp ONLY.
        if rvol >= SCALP_MIN_RVOL and micro and price <= SCALP_MAX_PRICE:
            reason_codes.append("VERIFIED_MICROCAP_MOMENTUM")
            return result("momentum_scalp", "GO", "momentum_scalp",
                          requires_verified=True, social_only=False)

        # 3b. LARGE-float social scout (hybrid, P0-5): retained for the operator, clearly labelled
        # LARGE FLOAT, MANUAL REVIEW — never a standard momentum_scalp, never auto-GO/fast-path.
        # Squeeze signature routes to meme_squeeze_momentum (with the scout sublabel); plain
        # large-float momentum routes to the dedicated large_float_social_scout.
        if large and rvol >= SCALP_MIN_RVOL and price <= SCOUT_MAX_PRICE:
            if rvol >= SQUEEZE_MIN_RVOL and (gap is not None and gap >= SQUEEZE_MIN_GAP) and squeeze:
                reason_codes.append("VERIFIED_LARGE_FLOAT_SQUEEZE")
                route_id = "meme_squeeze_momentum"
            else:
                reason_codes.append("VERIFIED_LARGE_FLOAT_SOCIAL_SCOUT")
                route_id = "large_float_social_scout"
            return result(route_id, "MANUAL_REVIEW", route_id,
                          requires_verified=True, social_only=False,
                          scout_label=SCOUT_LABEL, manual_review_required=True,
                          operator_label="LARGE FLOAT SOCIAL SCOUT")

        # 3c. Very large float / high-price established name → portfolio agents (not a scalp/scout).
        if large and price > SCOUT_MAX_PRICE:
            reason_codes.append("LARGE_FLOAT_HIGH_PRICE_PORTFOLIO")
            return result("portfolio_agents", "MANUAL_REVIEW", None,
                          requires_verified=True, social_only=False, manual_review_required=True)

        # 3d. Verified but price/float/rvol outside every strategy boundary → reject.
        reason_codes.append("OUT_OF_STRATEGY_BOUNDS")
        return result("reject", "AVOID", None, requires_verified=True, social_only=False)

    # 4. Social-only / unverified catalyst → watch_only, NEVER GO.
    reason_codes.append("SOCIAL_ONLY_UNVERIFIED")
    if rvol >= SCALP_MIN_RVOL and (float_m is not None and float_m <= SCALP_MAX_FLOAT_M) \
            and price <= SCALP_MAX_PRICE:
        # Meets scalp metrics but lacks catalyst verification — hold as WAIT pending confirmation.
        reason_codes.append("AWAITING_CATALYST_VERIFICATION")
        return result("watch_only", "WAIT", None, requires_verified=True, social_only=True)
    return result("watch_only", "WATCH", None, requires_verified=True, social_only=True)


if __name__ == "__main__":
    import json
    demo = route_social_candidate(
        {"symbol": "DEMO", "mention_count": 40, "sources": ["reddit"], "strategy_tags": []},
        {"price": 5.0, "rvol": 7.0, "float_m": 8.0, "gap_pct": 6.0},
        {"catalyst_verified": True, "catalyst_source": "news"}, trace_id="demo")
    print(json.dumps(demo, indent=2, default=str))

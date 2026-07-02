#!/usr/bin/env python3
"""pre_promotion_readiness_policy.py — Gate candidates before promotion to proposal.

Pure functions. No DB writes. No broker calls. No order submission.
"""

MIN_RR = 2.0
MAX_PRICE_DRIFT_PCT = 8.0
MAX_SPREAD_PCT = {"INTRADAY_MOMENTUM": 1.5, "GAP_EVENT": 2.0, "SHORT_SWING": 3.0, "MEDIUM_SWING": 5.0, "RECOVERY_WATCH": 5.0, "DIVIDEND_CORE_COMPOUNDER": 3.0}
MIN_VOLUME = 5000

# Strategies requiring specific pre-checks
CATALYST_REQUIRED = {"earnings_catalyst", "earnings_post_momentum", "earnings_pre_buildup", "recovery_watch", "defense_thesis"}
TECHNICAL_REQUIRED = {"swing_breakout", "swing_trade", "fib_retracement_bounce", "recovery_watch", "speculative_growth"}

DAILY_SCALP_SOURCES = {"daily_momentum_scalp", "tradeai_daily_scalp", "external_scalp"}


def evaluate_pre_promotion_readiness(candidate: dict) -> dict:
    """Check whether a candidate is ready to become an actionable proposal."""
    blockers = []
    warnings = []
    sid = candidate.get("strategy_id", "")

    # 1. Valid strategy_id
    try:
        from strategy_config_loader import load_all_strategy_configs
        valid_ids = set(load_all_strategy_configs().keys())
        if sid and sid not in valid_ids:
            blockers.append(f"invalid_strategy_id: '{sid}' not in YAML configs")
    except ImportError:
        pass

    # 2. Out-of-scope source
    source = (candidate.get("discovery_source") or candidate.get("proposed_by") or "").lower()
    if source in DAILY_SCALP_SOURCES:
        blockers.append("out_of_scope_daily_scalp")

    # 3. R:R minimum
    rr = candidate.get("rr") or candidate.get("proposed_rr") or 0
    entry = float(candidate.get("entry") or candidate.get("proposed_entry") or 0)
    stop = float(candidate.get("stop") or candidate.get("proposed_stop") or 0)
    target = float(candidate.get("target") or candidate.get("proposed_target1") or 0)
    if entry > 0 and stop > 0 and target > 0:
        computed_rr = round((target - entry) / (entry - stop), 4) if entry > stop else 0
        if computed_rr < MIN_RR - 0.005:  # tolerance for floating point
            blockers.append(f"rr_below_minimum: {computed_rr:.2f} < {MIN_RR}")

    # 4. Quote age gate (ATP-5)
    QUOTE_AGE_HARD_EXPIRE_HOURS = 168  # 7 days
    QUOTE_AGE_STALE_HOURS = {"momentum_scalp": 0.25, "gap_and_go": 0.25, "swing_trade": 4, "swing_breakout": 4, "default": 24}
    quote_age_hours = candidate.get("quote_age_hours")
    quote_checked_at = candidate.get("last_price_checked_at") or candidate.get("quote_checked_at")
    scan_age_hours = candidate.get("scan_age_hours") or candidate.get("latest_scan_age_hours")

    # Use scan age as fallback if quote_age not provided
    effective_quote_age = quote_age_hours or scan_age_hours

    if effective_quote_age is None and quote_checked_at is None:
        blockers.append("quote_never_checked: cannot promote without any quote data")
    elif effective_quote_age is not None:
        if float(effective_quote_age) > QUOTE_AGE_HARD_EXPIRE_HOURS:
            blockers.append(f"quote_extremely_stale: {float(effective_quote_age):.0f}h > {QUOTE_AGE_HARD_EXPIRE_HOURS}h hard limit")
        else:
            stale_threshold = QUOTE_AGE_STALE_HOURS.get(sid, QUOTE_AGE_STALE_HOURS["default"])
            if float(effective_quote_age) > stale_threshold:
                warnings.append(f"quote_stale: {float(effective_quote_age):.1f}h > {stale_threshold}h threshold for {sid}")

    # 4b. Price/quote freshness (drift check)
    quote_price = candidate.get("quote_price") or candidate.get("current_price")
    if quote_price and entry > 0:
        drift = abs(float(quote_price) - entry) / entry * 100
        if drift > MAX_PRICE_DRIFT_PCT:
            blockers.append(f"price_moved: {drift:.1f}% drift from entry")
        elif drift > MAX_PRICE_DRIFT_PCT * 0.6:
            warnings.append(f"price_drift_elevated: {drift:.1f}%")

    # 5. Spread
    spread = candidate.get("spread_pct")
    if spread is not None:
        family = candidate.get("strategy_family", "SHORT_SWING")
        max_sp = MAX_SPREAD_PCT.get(family, 3.0)
        if float(spread) > max_sp:
            blockers.append(f"spread_too_wide: {float(spread):.1f}% > {max_sp:.1f}%")

    # 6. Volume
    volume = candidate.get("volume") or candidate.get("day_volume")
    if volume is not None and int(volume) < MIN_VOLUME:
        warnings.append(f"low_volume: {volume}")

    # 7. Catalyst required
    if sid in CATALYST_REQUIRED:
        if not candidate.get("catalyst") and not candidate.get("catalyst_verified"):
            warnings.append("catalyst_missing_for_strategy")

    # 8. Authoritative trade plan — no pure R:R gambling geometry at promotion time
    sym = str(candidate.get("symbol") or "").upper().strip()
    if sym and entry > 0 and stop > 0 and target > 0:
        try:
            import broker_trade_plan_gate as btpg
            basis = candidate.get("sizing_basis")
            if isinstance(basis, str):
                import json as _json
                try:
                    basis = _json.loads(basis)
                except Exception:
                    basis = {}
            gate = btpg.assess_broker_trade_plan(
                entry, stop, target, sid,
                sizing_basis=basis if isinstance(basis, dict) else None,
            )
            if not gate.get("allowed"):
                v0 = (gate.get("violations") or ["no_authoritative_trade_plan"])[0]
                blockers.append(f"no_authoritative_trade_plan: {v0[:120]}")
        except Exception:
            pass

    # Status
    if blockers:
        status = "blocked"
    elif warnings:
        status = "promote_review_only"
    else:
        status = "promote_ready"

    return {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "promote_ready": status == "promote_ready",
        "gate_version": "pre_promotion_v2_quote_age",
    }


def promotion_blockers(candidate: dict) -> list:
    """Return list of promotion blocker strings."""
    r = evaluate_pre_promotion_readiness(candidate)
    return r["blockers"]


def promotion_next_action(candidate: dict) -> str:
    """Recommend next action for blocked candidate."""
    r = evaluate_pre_promotion_readiness(candidate)
    if r["status"] == "promote_ready":
        return "Ready to promote"
    if any("rr_below" in b for b in r["blockers"]):
        return "Rebuild with updated entry/stop/target or expire"
    if any("price_moved" in b for b in r["blockers"]):
        return "Refresh quote and rebuild if price still misaligned"
    if any("spread_too_wide" in b for b in r["blockers"]):
        return "Wait for tighter spread"
    if any("invalid_strategy" in b for b in r["blockers"]):
        return "Assign valid YAML strategy"
    return "Review blockers before promotion"

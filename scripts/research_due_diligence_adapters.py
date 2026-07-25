#!/usr/bin/env python3
"""Specialized adapters for the shared research due-diligence contract.

Each adapter preserves its domain's own arithmetic and evidence requirements.
The shared envelope only makes maturity, provenance, freshness and authority
comparable across surfaces.
"""
from __future__ import annotations

import math
from typing import Any

import research_due_diligence as rdd

ADAPTER_VERSION = "specialized-research-adapters-v1"


def _num(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _truth_source(source_id: str, truth: dict | None, *, required: bool = True,
                  payload: Any = None) -> dict:
    truth = truth or {}
    return rdd.source_ref(
        source_id=source_id,
        provider=truth.get("source") or truth.get("provider"),
        as_of=truth.get("source_as_of") or truth.get("as_of") or truth.get("captured_at"),
        calculation_version=truth.get("calculation_version"),
        quality=truth.get("quality") or "unknown",
        cadence=truth.get("cadence"),
        required=required,
        stale=bool(truth.get("stale")),
        coverage_n=truth.get("coverage_n"),
        coverage_total=truth.get("coverage_total"),
        payload=payload if payload is not None else truth,
        payload_hash=truth.get("content_hash") or truth.get("snapshot_hash"),
        notes=truth.get("notes"),
    )


def proposal_due_diligence(
    proposal: dict,
    watch_packet: dict,
    *,
    account_context: dict | None = None,
    event_context: dict | None = None,
) -> dict:
    """Evaluate whether specialized proposal research is complete.

    The adapter validates the existing proposal; it never asks a model to invent
    or amend entry, stop, target, sizing or account mechanics.
    """
    import watch_packet_quality

    account_context = account_context or {}
    event_context = event_context or (watch_packet.get("event_state") or {})
    selected = watch_packet_quality.select_governing_validation(watch_packet or {})
    validation = selected.get("validation") or {}
    quality = validation.get("quality_admission") or {}
    freshness = watch_packet.get("freshness") or {}
    market = (watch_packet.get("current_input_snapshot")
              or watch_packet.get("input_snapshot") or {}).get("market") or {}

    entry = _num(proposal.get("proposed_entry") or proposal.get("entry")
                 or proposal.get("limit_price"))
    stop = _num(proposal.get("proposed_stop") or proposal.get("stop")
                or proposal.get("stop_price"))
    target = _num(proposal.get("proposed_target1") or proposal.get("target")
                  or proposal.get("target_price"))
    stated_rr = _num(proposal.get("risk_reward") or proposal.get("rr"))
    recomputed_rr = None
    arithmetic_ok = bool(entry and stop and target and entry > stop and target > entry)
    if arithmetic_ok:
        recomputed_rr = round((target - entry) / (entry - stop), 3)

    sources = [
        rdd.source_ref(
            source_id="proposal",
            provider="paper_trade_proposals or proposal producer",
            as_of=proposal.get("updated_at") or proposal.get("created_at"),
            calculation_version=proposal.get("calculation_version") or proposal.get("strategy_id"),
            quality="ok" if proposal else "missing",
            required=True,
            payload=proposal,
        ),
        rdd.source_ref(
            source_id="watch_validation",
            provider="governing Watch deterministic validator",
            as_of=watch_packet.get("evaluated_at") or watch_packet.get("generated_at")
                  or freshness.get("last_strategy_build_at"),
            calculation_version=validation.get("validator_version"),
            quality="ok" if validation else "missing",
            required=True,
            payload=validation,
            payload_hash=validation.get("ticket_hash"),
        ),
        rdd.source_ref(
            source_id="market",
            provider="canonical Watch input snapshot",
            as_of=market.get("price_as_of") or market.get("technical_as_of")
                  or watch_packet.get("facts_as_of"),
            calculation_version=watch_packet.get("action_policy_version"),
            quality=str(freshness.get("overall_state") or "unknown").lower(),
            required=True,
            stale=str(freshness.get("overall_state") or "").upper() in {"STALE", "FAILED"},
            payload=market,
        ),
        rdd.source_ref(
            source_id="account_context",
            provider="account-specific proposal capacity",
            as_of=account_context.get("as_of"),
            calculation_version=account_context.get("policy_version"),
            quality="ok" if account_context else "missing",
            required=True,
            payload=account_context,
        ),
        rdd.source_ref(
            source_id="event_context",
            provider="normalized event calendar",
            as_of=event_context.get("as_of") or event_context.get("evaluated_at")
                  or watch_packet.get("evaluated_at"),
            calculation_version=event_context.get("policy_version") or "normalized-event-contract",
            quality="ok" if event_context else "missing",
            required=True,
            payload=event_context,
        ),
    ]

    checks = [
        rdd.check(
            "proposal_levels",
            rdd.CHECK_PASS if arithmetic_ok else rdd.CHECK_FAIL,
            "entry, stop and target form one coherent long-risk ticket"
            if arithmetic_ok else "proposal entry/stop/target are missing or not ordered entry > stop and target > entry",
            evidence_refs=["proposal"],
            details={"entry": entry, "stop": stop, "target": target,
                     "rr_recomputed": recomputed_rr, "rr_stated": stated_rr},
        ),
        rdd.check(
            "proposal_rr",
            rdd.CHECK_PASS if recomputed_rr is not None and (
                stated_rr is None or abs(stated_rr - recomputed_rr) <= 0.05
            ) else rdd.CHECK_FAIL,
            "proposal R:R is independently reproducible"
            if recomputed_rr is not None and (stated_rr is None or abs(stated_rr - recomputed_rr) <= 0.05)
            else "proposal R:R does not reproduce from entry, stop and target",
            evidence_refs=["proposal"],
        ),
        rdd.check(
            "watch_deterministic_validation",
            rdd.CHECK_PASS if selected.get("deterministic") == "PASS"
            else rdd.CHECK_WARN if selected.get("deterministic") == "REVIEW_REQUIRED"
            else rdd.CHECK_FAIL,
            f"governing Watch validation is {selected.get('deterministic') or 'NOT_RUN'}",
            evidence_refs=["watch_validation"],
            details={"validation_source": selected.get("source")},
        ),
        rdd.check(
            "quality_admission",
            rdd.CHECK_PASS if quality.get("state") == "ADMITTED"
            and quality.get("new_entry_allowed") is not False else rdd.CHECK_FAIL,
            "underlying is explicitly ADMITTED for a new entry"
            if quality.get("state") == "ADMITTED" and quality.get("new_entry_allowed") is not False
            else f"underlying quality admission is {quality.get('state') or 'UNASSESSED'}",
            evidence_refs=["watch_validation"],
        ),
        rdd.check(
            "watch_freshness",
            rdd.CHECK_PASS if str(freshness.get("overall_state") or "").upper()
            in {"CURRENT", "DUE_SOON"} else rdd.CHECK_FAIL,
            f"Watch evidence freshness is {freshness.get('overall_state') or 'UNKNOWN'}",
            evidence_refs=["market"],
        ),
        rdd.check(
            "account_specific_capacity",
            rdd.CHECK_PASS if account_context.get("account")
            and account_context.get("sizing") is not None
            and account_context.get("capacity") is not None else rdd.CHECK_FAIL,
            "proposal carries account-specific sizing and remaining capacity"
            if account_context.get("account") and account_context.get("sizing") is not None
            and account_context.get("capacity") is not None
            else "account-specific sizing or remaining capacity is missing",
            evidence_refs=["account_context"],
        ),
        rdd.check(
            "event_clearance",
            rdd.CHECK_FAIL if event_context.get("blocks_action")
            or str(event_context.get("state") or "").upper() in {"BLOCKED", "UNKNOWN"}
            else rdd.CHECK_PASS,
            "normalized event state permits proposal research"
            if not event_context.get("blocks_action")
            and str(event_context.get("state") or "").upper() not in {"BLOCKED", "UNKNOWN"}
            else "event state is blocked or unresolved",
            evidence_refs=["event_context"],
        ),
    ]

    packet = rdd.evaluate(
        domain="proposal",
        subject={
            "proposal_id": proposal.get("id") or proposal.get("proposal_id"),
            "symbol": str(proposal.get("symbol") or watch_packet.get("symbol") or "").upper(),
            "strategy_id": proposal.get("strategy_id"),
            "account": account_context.get("account"),
        },
        checks=checks,
        sources=sources,
        evidence={
            "proposal_levels": {"entry": entry, "stop": stop, "target": target,
                                "rr_recomputed": recomputed_rr},
            "watch_validation_source": selected.get("source"),
            "quality_admission": quality,
            "account_context": account_context,
            "event_context": event_context,
        },
        policy_version=quality.get("policy_version") or "watch-quality-admission-v1",
        calculation_version="proposal-due-diligence-v1",
    )
    packet["downstream"].update({
        "proposal_research_complete": packet["deterministic_state"] == rdd.PASS,
        "proposal_state_write": False,
        "model_may_review_existing_ticket": packet["model_oversight"]["allowed"],
        "model_may_amend_ticket": False,
    })
    return packet


def sector_due_diligence(sector_row: dict, snapshot: dict,
                         *, benchmark: str = "SPY") -> dict:
    truth = sector_row.get("truth") or {}
    ledger = snapshot.get("truth_ledger") or {}
    freshness = sector_row.get("freshness") or {}
    sources = [
        _truth_source("sector_row", truth, payload=sector_row),
        _truth_source("sector_returns", ledger.get("sector_returns"), payload={
            "rs5": sector_row.get("rs5"), "rs20": sector_row.get("rs20"),
            "rs60": sector_row.get("rs60"), "slope": sector_row.get("slope"),
        }),
        _truth_source("breadth", ledger.get("breadth") or truth, payload={
            "breadth_pct": sector_row.get("breadth_pct"),
            "covered": sector_row.get("breadth_coverage_n"),
            "members": sector_row.get("breadth_membership_n"),
            "quality": sector_row.get("breadth_quality"),
        }),
    ]
    breadth_ok = sector_row.get("breadth_quality") == "ok" \
        and sector_row.get("breadth_pct") is not None
    metrics_ok = all(sector_row.get(key) is not None for key in ("rs20", "slope", "state"))
    current = not sector_row.get("quarantined") and not freshness.get("stale")
    checks = [
        rdd.check("benchmark", rdd.CHECK_PASS if benchmark == "SPY" else rdd.CHECK_WARN,
                  f"sector relative strength benchmark is {benchmark}",
                  evidence_refs=["sector_returns"]),
        rdd.check("relative_strength_math", rdd.CHECK_PASS if metrics_ok else rdd.CHECK_FAIL,
                  "RS20, slope and quadrant state are present"
                  if metrics_ok else "sector relative-strength state is incomplete",
                  evidence_refs=["sector_returns"]),
        rdd.check("exact_covered_breadth", rdd.CHECK_PASS if breadth_ok else rdd.CHECK_FAIL,
                  "covered-universe breadth passed exact-session coverage policy"
                  if breadth_ok else f"breadth quality is {sector_row.get('breadth_quality') or 'missing'}",
                  evidence_refs=["breadth"]),
        rdd.check("freshness", rdd.CHECK_PASS if current else rdd.CHECK_FAIL,
                  "sector row is current and not quarantined"
                  if current else "sector row is stale or quarantined",
                  evidence_refs=["sector_row"]),
        rdd.check("calculation_version", rdd.CHECK_PASS if sector_row.get("calculation_version") else rdd.CHECK_FAIL,
                  "sector calculation version is explicit"
                  if sector_row.get("calculation_version") else "sector calculation version missing",
                  evidence_refs=["sector_row"]),
    ]
    packet = rdd.evaluate(
        domain="sector",
        subject={"sector": sector_row.get("sector"), "etf": sector_row.get("etf")},
        checks=checks,
        sources=sources,
        evidence={
            "benchmark": benchmark,
            "state": sector_row.get("state"),
            "rs20": sector_row.get("rs20"),
            "slope": sector_row.get("slope"),
            "breadth": {
                "pct": sector_row.get("breadth_pct"),
                "coverage_n": sector_row.get("breadth_coverage_n"),
                "membership_n": sector_row.get("breadth_membership_n"),
                "quality": sector_row.get("breadth_quality"),
                "universe": "covered screener membership; not official ETF constituents",
            },
        },
        policy_version=snapshot.get("policy_version") or "defense-breadth-policy-v1",
        calculation_version=sector_row.get("calculation_version")
        or snapshot.get("calculation_version"),
    )
    packet["downstream"].update({
        "sector_research_complete": packet["deterministic_state"] == rdd.PASS,
        "rotation_recommendation_eligible": packet["deterministic_state"] == rdd.PASS,
    })
    return packet


def industry_due_diligence(industry_row: dict, snapshot: dict) -> dict:
    truth = industry_row.get("truth") or {}
    baseline = snapshot.get("spy_baseline") or {}
    sources = [
        _truth_source("industry_row", truth, payload=industry_row),
        rdd.source_ref(
            source_id="spy_baseline",
            provider=baseline.get("provider"),
            as_of=baseline.get("captured_at"),
            calculation_version=snapshot.get("calculation_version"),
            quality=baseline.get("quality") or "missing",
            required=True,
            payload=baseline,
        ),
        rdd.source_ref(
            source_id="industry_mapping",
            provider="versioned canonical industry-sector map",
            as_of=snapshot.get("captured_at"),
            calculation_version=(snapshot.get("data_quality") or {}).get("mapping_version"),
            quality=industry_row.get("mapping_quality") or "missing",
            required=True,
            payload={
                "industry": industry_row.get("industry"),
                "sector": industry_row.get("sector"),
                "mapping_quality": industry_row.get("mapping_quality"),
                "mapping_version": industry_row.get("mapping_version"),
            },
        ),
    ]
    mapped = industry_row.get("mapping_quality") in {"exact", "rule"} \
        and bool(industry_row.get("sector"))
    metrics_ok = all(industry_row.get(key) is not None for key in ("rel1w", "rel1m", "state"))
    same_run = baseline.get("quality") == "same_vendor_same_run"
    close_capture = snapshot.get("capture_kind") == "close"
    checks = [
        rdd.check("canonical_mapping", rdd.CHECK_PASS if mapped else rdd.CHECK_FAIL,
                  "industry maps to a canonical sector"
                  if mapped else "industry is unmapped and quarantined",
                  evidence_refs=["industry_mapping"]),
        rdd.check("provider_alignment", rdd.CHECK_PASS if same_run else rdd.CHECK_FAIL,
                  "industry and SPY baseline use the same provider and run"
                  if same_run else "industry and benchmark provider alignment is missing",
                  evidence_refs=["industry_row", "spy_baseline"]),
        rdd.check("relative_level_direction", rdd.CHECK_PASS if metrics_ok else rdd.CHECK_FAIL,
                  "one-month relative level and one-week relative direction are complete"
                  if metrics_ok else "industry relative level/direction is incomplete",
                  evidence_refs=["industry_row", "spy_baseline"]),
        rdd.check("close_confirmation", rdd.CHECK_PASS if close_capture else rdd.CHECK_WARN,
                  "close-confirmed industry capture"
                  if close_capture else "intraday refresh is research-only until the close capture",
                  evidence_refs=["industry_row"]),
    ]
    packet = rdd.evaluate(
        domain="industry",
        subject={"industry": industry_row.get("industry"),
                 "sector": industry_row.get("sector")},
        checks=checks,
        sources=sources,
        evidence={
            "capture_kind": snapshot.get("capture_kind"),
            "state": industry_row.get("state"),
            "rel1w": industry_row.get("rel1w"),
            "rel1m": industry_row.get("rel1m"),
            "mapping_quality": industry_row.get("mapping_quality"),
            "quadrant_method": snapshot.get("quadrant_mapping"),
        },
        policy_version=(snapshot.get("data_quality") or {}).get("mapping_version"),
        calculation_version=snapshot.get("calculation_version"),
    )
    packet["downstream"].update({
        "industry_research_complete": packet["deterministic_state"] == rdd.PASS,
        "proposal_or_rotation_eligible": packet["deterministic_state"] == rdd.PASS
        and close_capture,
    })
    return packet


def defense_due_diligence(
    card: dict,
    sector_snapshot: dict,
    *,
    sector_packet: dict | None = None,
    oversight: dict | None = None,
) -> dict:
    sector_packet = sector_packet or {}
    allocation = card.get("allocation_policy") or {}
    sizing = card.get("account_sizing") or {}
    risk = card.get("risk_context") or {}
    quality_gate = card.get("quality_gate") or {}
    sources = [
        rdd.source_ref(
            source_id="defense_card",
            provider="defense recommendation producer",
            as_of=card.get("as_of"),
            calculation_version=quality_gate.get("version"),
            quality="ok" if card else "missing",
            required=True,
            payload=card,
        ),
        rdd.source_ref(
            source_id="sector_packet",
            provider="shared sector due-diligence adapter",
            as_of=sector_packet.get("generated_at"),
            calculation_version=sector_packet.get("calculation_version"),
            quality=(sector_packet.get("deterministic_state") or "missing").lower(),
            required=True,
            payload_hash=sector_packet.get("packet_hash"),
        ),
        rdd.source_ref(
            source_id="account_sizing",
            provider="account-specific allocation policy",
            as_of=card.get("as_of"),
            calculation_version=quality_gate.get("version"),
            quality="ok" if sizing else "missing",
            required=True,
            payload={"allocation": allocation, "sizing": sizing,
                     "exposure": card.get("account_exposure")},
        ),
        rdd.source_ref(
            source_id="risk_context",
            provider="aligned realized volatility and SPY correlation",
            as_of=card.get("as_of"),
            calculation_version="realized-vol-corr-v1",
            quality=risk.get("quality") or "missing",
            required=True,
            payload=risk,
        ),
    ]
    if oversight is not None:
        sources.append(rdd.source_ref(
            source_id="model_oversight",
            provider="independent critique seats",
            as_of=oversight.get("generated_at") or oversight.get("at"),
            calculation_version=oversight.get("contract_version") or "critique-only",
            quality="ok" if oversight else "missing",
            required=False,
            payload=oversight,
        ))

    eligible_accounts = [
        account for account, decision in allocation.items()
        if isinstance(decision, dict) and decision.get("eligible")
    ]
    all_sized = bool(eligible_accounts) and all(account in sizing for account in eligible_accounts)
    all_account_specific = all(
        isinstance(row, dict) and row.get("current_account_weight_pct") is not None
        and row.get("capacity_pct") is not None and row.get("risk_target_pct") is not None
        for row in allocation.values() if isinstance(row, dict)
    )
    sector_pass = sector_packet.get("deterministic_state") == rdd.PASS
    checks = [
        rdd.check("shadow_mode", rdd.CHECK_PASS if card.get("mode") == "SHADOW" else rdd.CHECK_FAIL,
                  "recommendation remains SHADOW/advisory"
                  if card.get("mode") == "SHADOW" else "recommendation mode is not SHADOW",
                  evidence_refs=["defense_card"]),
        rdd.check("sector_due_diligence", rdd.CHECK_PASS if sector_pass else rdd.CHECK_FAIL,
                  "underlying sector research passed the shared contract"
                  if sector_pass else f"sector research is {sector_packet.get('deterministic_state') or 'missing'}",
                  evidence_refs=["sector_packet"]),
        rdd.check("account_specific_exposure", rdd.CHECK_PASS if all_account_specific else rdd.CHECK_FAIL,
                  "every allocation decision carries its own current weight, target and capacity"
                  if all_account_specific else "one or more account decisions lack account-specific exposure or capacity",
                  evidence_refs=["account_sizing"]),
        rdd.check("account_specific_sizing", rdd.CHECK_PASS if all_sized else rdd.CHECK_FAIL,
                  "every eligible account has its own percentage and dollar sizing band"
                  if all_sized else "eligible account sizing is missing or shared across accounts",
                  evidence_refs=["account_sizing"]),
        rdd.check("risk_context", rdd.CHECK_PASS if risk.get("quality") == "ok"
                  and risk.get("annualized_vol_pct") is not None
                  and risk.get("correlation") is not None else rdd.CHECK_FAIL,
                  "realized volatility and benchmark correlation are complete"
                  if risk.get("quality") == "ok" and risk.get("annualized_vol_pct") is not None
                  and risk.get("correlation") is not None else "risk context is incomplete",
                  evidence_refs=["risk_context"]),
        rdd.check("entry_and_invalidation", rdd.CHECK_PASS if (card.get("levels") or {}).get("entry_zone")
                  and card.get("invalidation") else rdd.CHECK_FAIL,
                  "entry logic and invalidation are explicit"
                  if (card.get("levels") or {}).get("entry_zone") and card.get("invalidation")
                  else "entry logic or invalidation is missing",
                  evidence_refs=["defense_card"]),
        rdd.check("stock_quality_gate", rdd.CHECK_PASS
                  if quality_gate.get("stock_picks_passed") is not None else rdd.CHECK_FAIL,
                  "stock-quality gate result is explicit"
                  if quality_gate.get("stock_picks_passed") is not None
                  else "stock-quality gate result is missing",
                  evidence_refs=["defense_card"]),
    ]
    packet = rdd.evaluate(
        domain="defense",
        subject={"card_id": card.get("id"), "group": card.get("group"),
                 "title": card.get("title")},
        checks=checks,
        sources=sources,
        evidence={
            "eligible_accounts": eligible_accounts,
            "account_sizing": sizing,
            "allocation_policy": allocation,
            "risk_context": risk,
            "quality_gate": quality_gate,
            "oversight_attached": oversight is not None,
        },
        policy_version=quality_gate.get("version"),
        calculation_version=quality_gate.get("version"),
    )
    packet["downstream"].update({
        "defense_research_complete": packet["deterministic_state"] == rdd.PASS,
        "recommendation_card_eligible": packet["deterministic_state"] == rdd.PASS,
        "oversight_is_critique_only": True,
    })
    return packet

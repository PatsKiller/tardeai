#!/usr/bin/env python3
"""strategy_ticket_review.py — adversarial critics of the EXACT final ticket.

Runs ONLY after deterministic construction and validation. Three bounded lanes:

    LOCAL_CRITIC          local_llm.generate_local_only (cloud structurally off)
    GROK_OAUTH_CRITIC     free Grok OAuth lane (llm_lane)
    CHATGPT_OAUTH_CRITIC  free ChatGPT OAuth lane (llm_lane)

Every critic receives the same immutable, curated packet and no other critic's
verdict. Street ratings, CIO conclusions, Hermes rank and model verdicts are
excluded to prevent anchoring. Reviews bind to ticket_hash + facts_hash; a
changed ticket voids them. Critics can never create mechanics, grant quality
admission, or override deterministic failure.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

CRITIC_SCHEMA_KEYS = (
    "verdict", "math_check", "semantic_contradictions", "missing_evidence",
    "stale_inputs", "risk_objections", "questions", "evidence_citations",
)
ARRAY_KEYS = (
    "semantic_contradictions", "missing_evidence", "stale_inputs",
    "risk_objections", "questions", "evidence_citations",
)
MATH_KEYS = (
    "entry_consistent", "stop_consistent", "target_consistent",
    "rr_recomputed", "rr_matches",
)

_SYSTEM = (
    "You are an independent adversarial reviewer of one already-constructed "
    "trading-desk ticket. Deterministic arithmetic, quality admission, freshness, "
    "risk policy and release authority remain sovereign. You NEVER create, move "
    "or repair an entry, stop, target, size, trigger or option contract. You NEVER "
    "turn RESEARCH_ONLY or QUARANTINED into permission. Recompute simple ticket "
    "arithmetic; identify semantic contradictions, missing or stale evidence, "
    "non-scalping quality objections and reasons no-trade may be more honest. "
    "Use only evidence in the packet. Do not infer from analyst ratings, CIO "
    "opinions, Hermes rank, social buzz or another model; those are intentionally "
    "absent. Reply with STRICT JSON only, exactly: "
    '{"verdict":"PASS|CAUTION|REJECT","math_check":'
    '{"entry_consistent":bool,"stop_consistent":bool,'
    '"target_consistent":bool,"rr_recomputed":number|null,'
    '"rr_matches":bool|null},"semantic_contradictions":[],'
    '"missing_evidence":[],"stale_inputs":[],"risk_objections":[],'
    '"questions":[],"evidence_citations":[]}'
)

FUNDAMENTAL_KEYS = (
    "market_cap_usd_millions", "pe", "forward_pe", "peg", "pb", "ps",
    "eps_ttm", "eps_next_y", "eps_next_5y", "eps_past_5y", "sales_past_5y",
    "sales_qoq", "gross_margin_pct", "oper_margin_pct", "profit_margin_pct",
    "roe_pct", "roa_pct", "roic_pct", "lt_debt_equity", "total_debt_equity",
    "current_ratio", "quick_ratio", "short_float_pct", "shares_outstanding_m",
    "fundamentals_as_of",
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _technical_summary(snapshot: dict | None) -> dict:
    tech = snapshot or {}
    daily = ((tech.get("timeframes") or {}).get("daily") or {})
    indicators = daily.get("indicators") or {}
    momentum = daily.get("momentum_context") or {}
    volume = indicators.get("volume_roc") or {}
    return {
        "overall_freshness": tech.get("overall_freshness"),
        "overall_direction": tech.get("overall_direction"),
        "computed_at": tech.get("computed_at"),
        "source_hash": tech.get("source_hash"),
        "verdict": tech.get("verdict"),
        "primary_pattern": tech.get("primary_pattern"),
        "daily": {
            "freshness": (daily.get("meta") or {}).get("freshness_state"),
            "trend": daily.get("trend"),
            "momentum": momentum,
            "confluence": daily.get("confluence"),
            "volume_signal": volume.get("signal"),
            "volume_details": volume.get("details"),
        },
        "unavailable": tech.get("unavailable") or [],
        "error": tech.get("error"),
    }


def build_review_packet(symbol: str, ticket: dict, facts: dict,
                        validation: dict) -> dict:
    """Immutable, minimum-sufficient packet shared by every critic lane.

    Raw deterministic evidence is included; pre-chewed third-party or model
    recommendations are excluded. The validator's quality result is included
    so critics may challenge evidence completeness but cannot waive the gate.
    """
    fundamentals = facts.get("fundamentals") or {}
    catalysts = []
    for item in (facts.get("catalysts") or [])[:3]:
        if not isinstance(item, dict):
            continue
        catalysts.append({
            key: item.get(key)
            for key in ("headline", "published_at", "type", "source")
            if item.get(key) is not None
        })
    return {
        "contract": "watch-ticket-independent-review-v2",
        "symbol": str(symbol or "").upper(),
        "authority": {
            "deterministic_is_sovereign": True,
            "critic_can_create_mechanics": False,
            "critic_can_override_quality": False,
            "critic_can_release_or_propose": False,
        },
        "market_truth": {
            "current_price": facts.get("live_price") or facts.get("enriched_price"),
            "quote_as_of": facts.get("live_price_as_of") or facts.get("enriched_at"),
            "atr": facts.get("atr"),
            "rvol": facts.get("rvol"),
            "float_m": facts.get("float_m"),
            "support": facts.get("support") or [],
            "resistance": facts.get("resistance") or [],
        },
        "fundamentals": {
            key: fundamentals.get(key)
            for key in FUNDAMENTAL_KEYS
            if fundamentals.get(key) is not None
        },
        "deterministic_thesis": facts.get("deterministic_thesis") or {},
        "technical_snapshot": _technical_summary(facts.get("technical_state")),
        "data_quality": facts.get("data_quality") or {},
        "events": facts.get("events") or {},
        "catalysts": catalysts,
        "ticket": {
            key: ticket.get(key)
            for key in (
                "structure", "entry_mode", "entry_state", "entry_zone",
                "limit_price", "stop_price", "targets", "risk_reward",
                "trigger", "invalidation", "mechanics_current",
            )
        },
        "deterministic_validation": {
            key: validation.get(key)
            for key in (
                "state", "hard_failures", "warnings", "recomputed",
                "quality_admission", "ticket_hash", "facts_hash",
                "validator_version",
            )
        },
        "excluded_anchoring_inputs": [
            "Street recommendation", "CIO verdict", "Hermes rank",
            "social popularity", "other critic verdicts",
        ],
    }


def _prompt(packet: dict) -> str:
    return (
        "Review this exact ticket adversarially. Cite packet field paths in "
        "evidence_citations. A deterministic or quality failure is not appealable.\n\n"
        + json.dumps(packet, indent=1, default=str)
        + "\n\nReturn strict JSON only, using every required field from the system schema."
    )


def _parse(text: str) -> dict | None:
    raw = (text or "").strip()
    if "```" in raw:
        chunks = raw.split("```")
        raw = chunks[1] if len(chunks) > 1 else raw
        raw = raw.removeprefix("json").strip()
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        obj = json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    if set(CRITIC_SCHEMA_KEYS) - set(obj):
        return None
    verdict = str(obj.get("verdict") or "").upper()
    if verdict not in {"PASS", "CAUTION", "REJECT"}:
        return None
    math_check = obj.get("math_check")
    if not isinstance(math_check, dict) or set(MATH_KEYS) - set(math_check):
        return None
    for key in ("entry_consistent", "stop_consistent", "target_consistent"):
        if not isinstance(math_check.get(key), bool):
            return None
    if math_check.get("rr_matches") is not None and not isinstance(math_check.get("rr_matches"), bool):
        return None
    if math_check.get("rr_recomputed") is not None and _finite(math_check.get("rr_recomputed")) is None:
        return None
    for key in ARRAY_KEYS:
        if not isinstance(obj.get(key), list) or not all(isinstance(item, str) for item in obj[key]):
            return None
    obj["verdict"] = verdict
    return obj


def _finish(base: dict, parsed: dict | None, raw_err: str | None = None) -> dict:
    if parsed is None:
        base.update(
            verdict="UNAVAILABLE",
            error=raw_err or "critic response failed the strict schema contract",
        )
        return base
    for key in CRITIC_SCHEMA_KEYS:
        base[key] = parsed[key]
    return base


def _base(review_type: str, provider_family: str, validation: dict) -> dict:
    return {
        "review_type": review_type,
        "provider_family": provider_family,
        "model": None,
        "verdict": "UNAVAILABLE",
        "ticket_hash_reviewed": validation.get("ticket_hash"),
        "facts_hash_reviewed": validation.get("facts_hash"),
        "reviewed_at": _now(),
        "review_contract": "watch-ticket-independent-review-v2",
        "math_check": {},
        "semantic_contradictions": [],
        "missing_evidence": [],
        "stale_inputs": [],
        "risk_objections": [],
        "questions": [],
        "evidence_citations": [],
    }


def run_local_critic(symbol, ticket, facts, validation) -> dict:
    import local_llm
    packet = build_review_packet(symbol, ticket, facts, validation)
    base = _base("LOCAL_CRITIC", "LOCAL_OLLAMA", validation)
    result = local_llm.generate_local_only(_prompt(packet), system=_SYSTEM)
    if not result.get("ok"):
        base["error"] = result.get("error")
        return base
    base["model"] = result.get("model")
    return _finish(base, _parse(result.get("text")),
                   "local model returned incomplete or non-schema JSON")


def run_oauth_critic(lane: str, symbol, ticket, facts, validation) -> dict:
    """lane: grok | chatgpt — bounded OAuth critics, independently."""
    import llm_lane
    packet = build_review_packet(symbol, ticket, facts, validation)
    family = {"grok": "XAI", "chatgpt": "OPENAI"}[lane]
    base = _base(f"{lane.upper()}_OAUTH_CRITIC", family, validation)
    try:
        if not llm_lane.available(lane):
            base["error"] = f"{lane} lane unavailable"
            return base
        # Correct llm_lane contract: prompt first, lane keyword. No unsupported
        # max_tokens keyword; the previous call failed every OAuth review.
        output = llm_lane.generate(_SYSTEM + "\n\n" + _prompt(packet), lane=lane)
        text = output.get("text") if isinstance(output, dict) else str(output)
        base["model"] = (output.get("model") if isinstance(output, dict) else None) or lane
        return _finish(base, _parse(text),
                       f"{lane} returned incomplete or non-schema JSON")
    except Exception as exc:
        base["error"] = f"{type(exc).__name__}: {str(exc)[:140]}"
        return base


def run_free_reviews(symbol, ticket, facts, validation, *,
                     lanes=("local", "grok", "chatgpt")) -> dict:
    """Run selected critics; never call a paid lane and never fake consensus."""
    reviews = {}
    if "local" in lanes:
        reviews["local"] = run_local_critic(symbol, ticket, facts, validation)
    if "grok" in lanes:
        reviews["grok"] = run_oauth_critic("grok", symbol, ticket, facts, validation)
    if "chatgpt" in lanes:
        reviews["chatgpt"] = run_oauth_critic("chatgpt", symbol, ticket, facts, validation)
    completed = [review for review in reviews.values()
                 if review["verdict"] != "UNAVAILABLE"]
    families = {review["provider_family"] for review in completed}
    reviews["_meta"] = {
        "completed": len(completed),
        "independent_families": len(families),
        "consensus_possible": len(families) >= 2,
        "single_lane": len(completed) == 1,
        "review_contract": "watch-ticket-independent-review-v2",
        "paid_lane_called": False,
        "reviewed_at": _now(),
    }
    return reviews

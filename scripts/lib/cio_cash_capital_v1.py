"""Governed cash situation and advisory capital plan projections.

Observed cash never implies deployable cash. Dollar ranges remain unavailable until
the operator mandate is confirmed and read-only account evidence verifies investable
cash. These contracts emit advisory state only and contain no executable instructions.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUTHORITY = "READ_ONLY_ADVISORY"
CASH_SCHEMA = "CashDeploymentSituation@v1"
PLAN_SCHEMA = "CapitalDeploymentPlan@v1"
DEFAULT_STORE = "data/cio/cio_capital_plans.jsonl"

# Engine attention threshold — NOT operator policy. Used only to decide whether
# missing cash policy is worth a bounded POLICY_GAP operator question.
ATTENTION_CASH_PCT = 20.0
RISK_OFF_REGIMES = frozenset({
    "risk_off", "defensive", "bear", "crisis", "high_vol", "risk_off_defensive",
    "risk-off", "defensive_regime",
})
POLICY_CASH_FIELDS = ("cash_target_range_pct", "minimum_liquidity_reserve_usd")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _semantic(value: dict[str, Any]) -> dict[str, Any]:
    ignored = {"generated_at", "published_at", "version", "situation_version", "plan_version", "publication_version", "content_hash"}
    return {key: item for key, item in value.items() if key not in ignored}


def _confirmed_field(policy: dict[str, Any], name: str) -> Any:
    field = (policy.get("fields") or {}).get(name) or {}
    return field.get("value") if field.get("operator_confirmed") else None


# ── provenance at display ──────────────────────────────────────────────────
#
# Measured 2026-08-30 across 24 materially different situations — 1%/5%/20%
# cash, risk-on and risk-off, policy confirmed and not, thesis present and
# absent, reaching all four conclusions (DEPLOY_STAGED, HOLD_CASH, REBALANCE,
# RESEARCH_FIRST) — two fields never moved:
#
#   counter_case         one byte-identical sentence in all 24
#   supporting_evidence  [null, null, null, null, null]
#
# A counter-case is the argument against THIS recommendation on THIS data. A
# constant string in that slot is a disclaimer wearing a counter-case's label,
# and it reads to the operator as reasoning that was done. Five nulls rendered
# as a list of supporting evidence is the same failure in the other direction.
#
# Both now say what is true of the situation in front of them, and say nothing
# rather than something generic when there is nothing specific to say.

_COUNTER_CASE_BY_CONCLUSION = {
    "DEPLOY_STAGED": (
        "Cash above the policy ceiling is not itself a reason to deploy: the "
        "ceiling assumes opportunities worth funding, and none of this "
        "establishes that today's candidates are."
    ),
    "HOLD_CASH": (
        "Holding here costs the return the cash would have earned deployed, "
        "and a regime read is not a forecast — the same posture would have "
        "been wrong through most recoveries."
    ),
    "REBALANCE": (
        "Cash below the floor can be the correct posture when the positions "
        "holding that capital still earn it; restoring the floor by selling "
        "them trades a live thesis for a policy number."
    ),
    "RESEARCH_FIRST": (
        "Waiting for complete evidence has its own cost, and evidence that is "
        "incomplete for a structural reason will not become complete by "
        "waiting for it."
    ),
    "WAIT": (
        "Waiting is a position. If the condition being waited on is not "
        "named and dated, this is indefinite by default."
    ),
}


def _counter_case(
    *,
    conclusion: str,
    deviation_state: Any,
    regime_risk_off: Any,
    blockers: list[str],
) -> dict[str, Any]:
    """The argument against this conclusion, on this data — or an honest absence."""
    text = _COUNTER_CASE_BY_CONCLUSION.get(str(conclusion or ""))
    grounds: list[str] = []
    if deviation_state and deviation_state not in {"UNAVAILABLE", "POLICY_REQUIRED"}:
        grounds.append(f"cash is {deviation_state} the confirmed policy range")
    if regime_risk_off:
        grounds.append("the current regime reads risk-off")
    if blockers:
        grounds.append(f"{len(blockers)} blocking gap(s) remain: {', '.join(sorted(set(blockers))[:3])}")
    if text is None:
        return {
            "state": "NONE_SPECIFIC",
            "text": None,
            "against_conclusion": conclusion,
            "note": "no counter-case is stated for this conclusion; an absence, "
                    "not a generic one",
        }
    return {
        "state": "STATED",
        "text": text,
        "against_conclusion": conclusion,
        "grounds": grounds,
        "provenance": "TEMPLATE — one per conclusion, selected by this "
                      "situation's conclusion; the grounds are read from the "
                      "situation. Not model-written.",
    }


def _counter_case_text(**kw: Any) -> str | None:
    """The published string form: the conclusion-specific case, plus the grounds
    it was drawn from. Still a string, so every existing consumer is unaffected."""
    cc = _counter_case(**kw)
    if not cc.get("text"):
        return None
    grounds = cc.get("grounds") or []
    if not grounds:
        return str(cc["text"])
    return f"{cc['text']} (on this data: {'; '.join(grounds)})"


def _evidence_versions(
    policy: dict[str, Any],
    portfolio_state: dict[str, Any],
    market_context: dict[str, Any],
    seasonality: dict[str, Any],
    portfolio_thesis: dict[str, Any] | None,
) -> list[Any]:
    """The published list form, order-stable for positional readers."""
    return [
        (policy or {}).get("version"),
        (portfolio_state or {}).get("version"),
        (market_context or {}).get("version"),
        (seasonality or {}).get("version"),
        (portfolio_thesis or {}).get("thesis_version"),
    ]


_EVIDENCE_SOURCES = (
    ("policy", "version"),
    ("portfolio_state", "version"),
    ("market_context", "version"),
    ("seasonality", "version"),
    ("portfolio_thesis", "thesis_version"),
)


def _supporting_evidence(
    policy: dict[str, Any],
    portfolio_state: dict[str, Any],
    market_context: dict[str, Any],
    seasonality: dict[str, Any],
    portfolio_thesis: dict[str, Any] | None,
) -> dict[str, Any]:
    """Which inputs actually carried a version, and which did not.

    Was a bare list of five values, rendered as supporting evidence even when
    every one of them was null. A named absence is evidence; an unnamed null
    is not.
    """
    docs = {
        "policy": policy or {},
        "portfolio_state": portfolio_state or {},
        "market_context": market_context or {},
        "seasonality": seasonality or {},
        "portfolio_thesis": portfolio_thesis or {},
    }
    present: list[dict[str, Any]] = []
    missing: list[str] = []
    for name, key in _EVIDENCE_SOURCES:
        v = docs[name].get(key)
        if v:
            present.append({"source": name, "version": str(v)})
        else:
            missing.append(name)
    return {
        "state": "COMPLETE" if not missing else (
            "NONE" if not present else "PARTIAL"),
        "present": present,
        "unversioned_sources": missing,
        "counts": {"present": len(present), "missing": len(missing)},
    }


def independently_material_cash(
    cash_pct: Any,
    observed_cash: Any = None,
    total_value: Any = None,
    *,
    attention_pct: float = ATTENTION_CASH_PCT,
) -> bool:
    """True when cash is large enough to ask about missing policy.

    This is not a deployment recommendation and is not operator policy.
    """
    try:
        if cash_pct is not None and float(cash_pct) >= float(attention_pct):
            return True
    except (TypeError, ValueError):
        pass
    try:
        if observed_cash is not None and total_value not in (None, 0, 0.0):
            if (float(observed_cash) / float(total_value)) * 100.0 >= float(attention_pct):
                return True
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return False


def _regime_is_risk_off(market_context: dict[str, Any]) -> bool:
    fields = market_context.get("fields") or {}
    raw = (fields.get("regime") or {}).get("value") if isinstance(fields, dict) else None
    if raw is None:
        raw = market_context.get("regime")
    return str(raw or "").strip().lower() in RISK_OFF_REGIMES


def _missing_cash_policy_fields(policy: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if policy.get("status") != "CONFIRMED":
        missing.extend(list(POLICY_CASH_FIELDS))
        extra = [str(item) for item in (policy.get("missing_fields") or []) if item]
        return sorted(set(missing + extra))
    for name in POLICY_CASH_FIELDS:
        if _confirmed_field(policy, name) is None:
            missing.append(name)
    return missing


def _reserved_cash(portfolio_state: dict[str, Any]) -> float | None:
    accounts = portfolio_state.get("cash_accounts") or {}
    values = [row.get("reserved_cash_usd") for row in accounts.values() if isinstance(row, dict)]
    if not values or any(value is None for value in values):
        return None
    return round(sum(float(value) for value in values), 2)


def build_cash_deployment_situation(
    *,
    policy: dict[str, Any],
    portfolio_state: dict[str, Any],
    market_context: dict[str, Any],
    seasonality: dict[str, Any],
    portfolio_thesis: dict[str, Any] | None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = evaluated_at or datetime.now(timezone.utc)
    policy_range = _confirmed_field(policy, "cash_target_range_pct")
    minimum_reserve = _confirmed_field(policy, "minimum_liquidity_reserve_usd")
    observed_cash = portfolio_state.get("observed_cash_usd")
    investable_cash = portfolio_state.get("investable_cash_usd")
    cash_pct = ((portfolio_state.get("allocation") or {}).get("cash") or {}).get("pct")
    total_value = portfolio_state.get("total_portfolio_value_usd")
    reserved = _reserved_cash(portfolio_state)
    blockers: list[str] = []
    if policy.get("status") != "CONFIRMED" or policy_range is None or minimum_reserve is None:
        blockers.append("POLICY_REQUIRED")
    if investable_cash is None:
        blockers.append("INVESTABLE_CASH_UNVERIFIED")
    if portfolio_state.get("truth_quality") in {"CONFLICTED", "STALE", "UNAVAILABLE"}:
        blockers.append(f"PORTFOLIO_STATE_{portfolio_state.get('truth_quality')}")
    if market_context.get("truth_quality") != "VERIFIED":
        blockers.append(f"MARKET_CONTEXT_{market_context.get('truth_quality') or 'UNAVAILABLE'}")
    if not portfolio_thesis:
        blockers.append("PORTFOLIO_THESIS_UNAVAILABLE")
    elif portfolio_thesis.get("state") != "CURRENT":
        blockers.append(f"PORTFOLIO_THESIS_{portfolio_thesis.get('state') or 'UNAVAILABLE'}")

    if not isinstance(policy_range, dict) or policy_range.get("min") is None or policy_range.get("max") is None:
        policy_range = None
    deviation_pct = None
    deviation_state = "POLICY_REQUIRED" if policy_range is None else "UNAVAILABLE"
    if policy_range is not None and cash_pct is not None:
        low, high = float(policy_range["min"]), float(policy_range["max"])
        if float(cash_pct) > high:
            deviation_state = "ABOVE_RANGE"
            deviation_pct = round(float(cash_pct) - high, 4)
        elif float(cash_pct) < low:
            deviation_state = "BELOW_RANGE"
            deviation_pct = round(float(cash_pct) - low, 4)
        else:
            deviation_state = "IN_RANGE"
            deviation_pct = 0.0

    deployable_excess = None
    if not blockers and investable_cash is not None and total_value is not None and policy_range is not None:
        cash_ceiling = float(total_value) * float(policy_range["max"]) / 100.0
        deployable_excess = round(max(0.0, float(investable_cash) - cash_ceiling), 2)

    missing_policy = _missing_cash_policy_fields(policy)
    cash_attention = independently_material_cash(cash_pct, observed_cash, total_value)
    regime_risk_off = _regime_is_risk_off(market_context)

    if blockers:
        conclusion = "RESEARCH_FIRST"
    elif deviation_state == "ABOVE_RANGE" and (deployable_excess or 0) > 0:
        conclusion = "HOLD_CASH" if regime_risk_off else "DEPLOY_STAGED"
    elif deviation_state == "BELOW_RANGE":
        conclusion = "REBALANCE"
    elif deviation_state == "IN_RANGE":
        conclusion = "HOLD_CASH"
    else:
        conclusion = "WAIT"

    # POLICY_GAP: material cash without confirmed policy is an operator question,
    # not a silent suppress and not a deployment recommendation.
    policy_gap = bool(missing_policy) and cash_attention
    excess_material = (not blockers) and deviation_state in {"ABOVE_RANGE", "BELOW_RANGE"}
    if policy_gap:
        notify_class = "POLICY_GAP"
        notify_eligible = True
        suppression = None
        material = True
    elif excess_material:
        notify_class = "EXCESS_CASH" if deviation_state == "ABOVE_RANGE" else "ALLOCATION_DRIFT"
        notify_eligible = True
        suppression = None
        material = True
    elif deviation_state == "IN_RANGE" and not blockers:
        notify_class = "NO_MATERIAL_CHANGE"
        notify_eligible = False
        suppression = "CASH_WITHIN_POLICY"
        material = False
    elif "POLICY_REQUIRED" in blockers and not cash_attention:
        notify_class = "POLICY_GAP"
        notify_eligible = False
        suppression = "POLICY_REQUIRED_IMMATERIAL"
        material = False
    else:
        notify_class = "NO_MATERIAL_CHANGE"
        notify_eligible = False
        suppression = blockers[0] if blockers else "CASH_WITHIN_POLICY"
        material = False

    fields = market_context.get("fields") or {}
    payload = {
        "schema": CASH_SCHEMA,
        "authority": AUTHORITY,
        "generated_at": now.isoformat(),
        "state": "BLOCKED" if blockers else "CURRENT",
        "conclusion": conclusion,
        "verified_cash_usd": observed_cash if portfolio_state.get("truth_quality") == "VERIFIED" else None,
        "observed_cash_usd": observed_cash,
        "investable_cash_usd": investable_cash,
        "reserved_cash_usd": reserved,
        "minimum_liquidity_reserve_usd": minimum_reserve,
        "cash_pct": cash_pct,
        "policy_range_pct": policy_range,
        "deviation_state": deviation_state,
        "deviation_pct": deviation_pct,
        "deviation_duration_days": None,
        "deployable_excess_usd": deployable_excess,
        "cash_yield": {"state": "UNAVAILABLE", "value": None},
        "treasury_alternatives": {"state": "RESEARCH_REQUIRED", "items": []},
        "underweight_sleeves": list((portfolio_thesis or {}).get("underweight_sleeves") or []),
        "market_regime": ((fields.get("regime") or {}).get("value")),
        "rates_context": {
            "fed_funds_rate_pct": (fields.get("fed_funds_rate_pct") or {}).get("value"),
            "ten_two_spread_pct": (fields.get("ten_two_spread_pct") or {}).get("value"),
        },
        "valuation_context": (fields.get("valuation") or {}).get("value"),
        "breadth_context": (fields.get("breadth") or {}).get("value"),
        "volatility_context": (fields.get("vix_close") or {}).get("value"),
        "seasonality_state": seasonality.get("truth_quality"),
        "forward_event_context": {
            "macro": (fields.get("macro_calendar") or {}).get("value"),
            "portfolio_earnings": (fields.get("portfolio_earnings_calendar") or {}).get("value"),
        },
        # Shapes stay as published — `counter_case` a string, `supporting_evidence`
        # a list — because four consumers read them positionally and one does
        # `list(...)`, which on a dict silently yields the keys. The structure
        # goes in sibling keys instead.
        "supporting_evidence": _evidence_versions(
            policy, portfolio_state, market_context, seasonality, portfolio_thesis),
        "supporting_evidence_state": _supporting_evidence(
            policy, portfolio_state, market_context, seasonality, portfolio_thesis),
        "counter_case": _counter_case_text(
            conclusion=conclusion,
            deviation_state=deviation_state,
            regime_risk_off=regime_risk_off,
            blockers=blockers,
        ),
        "counter_case_provenance": _counter_case(
            conclusion=conclusion,
            deviation_state=deviation_state,
            regime_risk_off=regime_risk_off,
            blockers=blockers,
        ),
        "what_changes_the_plan": sorted(set(blockers + ["MATERIAL_MARKET_CONTEXT_CHANGE", "PORTFOLIO_THESIS_DELTA"])),
        "blockers": sorted(set(blockers)),
        "missing_policy_fields": missing_policy,
        "policy_gap": policy_gap,
        "regime_risk_off": regime_risk_off,
        "material": material,
        "situation_class": notify_class,
        "notification": {
            "eligible": notify_eligible,
            "class": notify_class,
            "operator_question": policy_gap,
            "suppression_reason": suppression,
        },
        "financial_action": False,
        "executable_order": None,
    }
    payload["content_hash"] = _hash(_semantic(payload))
    payload["version"] = "cash_situation_" + payload["content_hash"][:16]
    return payload


def build_capital_deployment_plan(
    *,
    situation: dict[str, Any],
    portfolio_thesis: dict[str, Any] | None,
    methodology_refs: list[str] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = evaluated_at or datetime.now(timezone.utc)
    conclusion = situation.get("conclusion") or "RESEARCH_FIRST"
    blocked = bool(situation.get("blockers"))
    excess = situation.get("deployable_excess_usd")
    underweight = list((portfolio_thesis or {}).get("underweight_sleeves") or [])
    do_now: list[dict[str, Any]] = []
    do_on_pullback: list[dict[str, Any]] = []
    wait: list[dict[str, Any]] = []
    research_first = [{"question": code, "reason": "BLOCKING_GAP"} for code in situation.get("blockers") or []]
    keep_cash: list[dict[str, Any]] = []
    avoid = [
        {"item": "UNVERIFIED_CAPITAL_DEPLOYMENT", "reason": "No deployment amount without verified investable cash and confirmed policy"},
        {"item": "EXECUTABLE_ORDERS", "reason": "READ_ONLY_ADVISORY"},
    ]

    if conclusion == "DEPLOY_STAGED" and excess is not None:
        if underweight:
            allocation_range = {"min_usd": 0.0, "max_usd": round(float(excess), 2)}
            do_now.append({
                "role": "UNDERWEIGHT_SLEEVE_REVIEW",
                "sleeves": underweight,
                "advisory_allocation_range": allocation_range,
                "entry_condition": "VALID_LIVING_THESIS_AND_CURRENT_EVIDENCE",
                "invalidation": "PORTFOLIO_THESIS_WEAKENS_OR_MARKET_CONTEXT_DEGRADES",
                "why_now": "Verified cash exceeds the confirmed policy ceiling.",
                "why_not_now": "Do not deploy where security-level thesis or valuation evidence is incomplete.",
            })
        else:
            research_first.append({"question": "IDENTIFY_CONFIRMED_UNDERWEIGHT_SLEEVES", "reason": "NO_POLICY_GAP_TARGET"})
    elif conclusion in {"RESEARCH_FIRST", "WAIT"}:
        keep_cash.append({"role": "OPTIONALITY", "amount_usd": situation.get("investable_cash_usd"), "reason": "Blocking evidence remains unresolved."})
    elif conclusion == "HOLD_CASH":
        if situation.get("regime_risk_off") and situation.get("deviation_state") == "ABOVE_RANGE":
            keep_cash.append({
                "role": "REGIME_DEFENSIVE_LIQUIDITY",
                "amount_usd": situation.get("investable_cash_usd"),
                "reason": "Verified cash exceeds policy, but the current market regime does not support staged deployment.",
            })
        else:
            keep_cash.append({
                "role": "POLICY_ALIGNED_LIQUIDITY",
                "amount_usd": situation.get("investable_cash_usd"),
                "reason": "Cash is inside the confirmed policy range.",
            })
    elif conclusion == "REBALANCE":
        wait.append({"condition": "CONFIRMED_REBALANCING_SOURCE", "reason": "Cash is below the confirmed range; this advisory contract does not create sale instructions."})

    if situation.get("forward_event_context", {}).get("macro") is None:
        wait.append({"condition": "FORWARD_MACRO_CALENDAR_AVAILABLE", "reason": "Event context is unavailable."})

    payload = {
        "schema": PLAN_SCHEMA,
        "authority": AUTHORITY,
        "generated_at": now.isoformat(),
        "state": "BLOCKED" if blocked else "CURRENT",
        "stance": conclusion,
        "available_capital_usd": situation.get("investable_cash_usd"),
        "reserved_capital_usd": situation.get("reserved_cash_usd"),
        "current_cash_pct": situation.get("cash_pct"),
        "target_cash_range_pct": situation.get("policy_range_pct"),
        "excess_or_deficit": {
            "state": situation.get("deviation_state"),
            "pct": situation.get("deviation_pct"),
            "deployable_excess_usd": excess,
        },
        "portfolio_gaps": underweight,
        "sleeve_priorities": underweight,
        "do_now": do_now,
        "do_on_pullback": do_on_pullback,
        "wait": wait,
        "research_first": research_first,
        "keep_cash_short_duration": keep_cash,
        "avoid": avoid,
        "methodology_used": sorted(set(methodology_refs or [])),
        "methodology_state": "AVAILABLE" if methodology_refs else "SOURCE_CLAIM_INCOMPLETE",
        "counter_case": situation.get("counter_case"),
        "what_changes_recommendation": situation.get("what_changes_the_plan") or [],
        "next_review": "ON_BLOCKER_RESOLUTION" if blocked else "WEEKLY_OR_MATERIAL_CHANGE",
        "notification": situation.get("notification"),
        "source_situation_version": situation.get("version"),
        "source_portfolio_thesis_version": (portfolio_thesis or {}).get("thesis_version"),
        "financial_action": False,
        "executable_order": None,
    }
    payload["content_hash"] = _hash(_semantic(payload))
    payload["version"] = "capital_plan_" + payload["content_hash"][:16]
    return payload


def load_latest_capital_record(store_path: str = DEFAULT_STORE) -> dict[str, Any] | None:
    path = Path(store_path)
    if not path.exists():
        return None
    latest = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("record_type") == "CAPITAL_PLAN_PUBLISHED":
            latest = row
    return latest


def reconcile_capital_plan(
    situation: dict[str, Any],
    plan: dict[str, Any],
    *,
    store_path: str = DEFAULT_STORE,
) -> dict[str, Any]:
    if situation.get("content_hash") != _hash(_semantic(situation)):
        raise ValueError("cash situation content_hash mismatch")
    if plan.get("content_hash") != _hash(_semantic(plan)):
        raise ValueError("capital plan content_hash mismatch")
    path = Path(store_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(path) + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o640)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        prior = load_latest_capital_record(store_path)
        if prior and (prior.get("plan") or {}).get("content_hash") == plan.get("content_hash"):
            return {"published": False, "reason": "NO_NEW_INFO", **prior}
        version = int(((prior or {}).get("plan") or {}).get("publication_version") or 0) + 1
        published_situation = dict(situation, situation_version=f"cash_situation@v{version}", published_at=_now())
        published_plan = dict(plan, plan_version=f"capital_plan@v{version}", publication_version=version, published_at=_now())
        record = {
            "record_type": "CAPITAL_PLAN_PUBLISHED",
            "recorded_at": _now(),
            "situation": published_situation,
            "plan": published_plan,
            "authority": AUTHORITY,
        }
        record["record_hash"] = _hash(record)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return {"published": True, "reason": "MATERIAL_OR_INITIAL", **record}
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

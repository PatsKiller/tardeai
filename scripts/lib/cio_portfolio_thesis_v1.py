"""Versioned CIOPortfolioThesis@v1 and PortfolioThesisDelta@v1."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "CIOPortfolioThesis@v1"
DELTA_SCHEMA = "PortfolioThesisDelta@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
DEFAULT_STORE = "data/cio/cio_portfolio_theses.jsonl"
DELTA_CLASSES = frozenset({"CONFIRMS", "STRENGTHENS", "WEAKENS", "INVALIDATES", "ROTATES", "NO_NEW_INFO", "CONFLICTED", "INSUFFICIENT_DATA"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content(thesis: dict[str, Any]) -> dict[str, Any]:
    ignored = {"generated_at", "published_at", "version", "thesis_version", "content_hash"}
    return {key: value for key, value in thesis.items() if key not in ignored}


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def load_symbol_thesis_refs(projection_path: str | Path, held_symbols: set[str]) -> list[dict[str, Any]]:
    """Load only held-symbol thesis identities; raw thesis prose stays in its canonical store."""
    try:
        document = json.loads(Path(projection_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    current = document.get("current") if isinstance(document, dict) else None
    if not isinstance(current, dict):
        return []
    wanted = {str(symbol).strip().upper() for symbol in held_symbols if str(symbol).strip()}
    result: list[dict[str, Any]] = []
    for key, value in current.items():
        if not isinstance(value, dict):
            continue
        symbol = str(value.get("symbol") or key.removeprefix("symbol_")).upper()
        if symbol not in wanted:
            continue
        result.append({
            "symbol": symbol,
            "thesis_id": value.get("thesis_id") or key,
            "thesis_version": value.get("thesis_version") or value.get("version_id"),
            "stance": value.get("stance") or value.get("state"),
            "portfolio_role": value.get("portfolio_role"),
        })
    return sorted(result, key=lambda row: row["symbol"])


def _allocation_posture(policy: dict[str, Any], portfolio: dict[str, Any], field_name: str, allocation_name: str) -> dict[str, Any]:
    field = (policy.get("fields") or {}).get(field_name) or {}
    actual = ((portfolio.get("allocation") or {}).get(allocation_name) or {}).get("pct")
    if not field.get("operator_confirmed"):
        return {"state": "POLICY_REQUIRED", "actual_pct": actual, "policy_range_pct": None}
    target = field.get("value") or {}
    if actual is None:
        state = "UNAVAILABLE"
    elif actual < float(target.get("min", 0)):
        state = "UNDERWEIGHT"
    elif actual > float(target.get("max", 100)):
        state = "OVERWEIGHT"
    else:
        state = "IN_RANGE"
    return {"state": state, "actual_pct": actual, "policy_range_pct": target}


def build_portfolio_thesis_candidate(
    *,
    policy: dict[str, Any],
    portfolio_state: dict[str, Any],
    market_context: dict[str, Any],
    seasonality: dict[str, Any],
    symbol_theses: list[dict[str, Any]] | None = None,
    feedback_refs: list[str] | None = None,
    outcome_refs: list[str] | None = None,
    methodology_refs: list[str] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = evaluated_at or datetime.now(timezone.utc)
    gaps: list[str] = []
    risks: list[str] = []
    policy_status = str(policy.get("status") or "POLICY_REQUIRED")
    portfolio_quality = str(portfolio_state.get("truth_quality") or "UNAVAILABLE")
    market_quality = str(market_context.get("truth_quality") or "UNAVAILABLE")
    seasonality_quality = str(seasonality.get("truth_quality") or "UNAVAILABLE")
    if policy_status != "CONFIRMED":
        gaps.append("OPERATOR_POLICY_REQUIRED")
    if portfolio_state.get("investable_cash_usd") is None:
        gaps.append("INVESTABLE_CASH_UNVERIFIED")
    if portfolio_quality in {"CONFLICTED", "UNAVAILABLE", "STALE"}:
        gaps.append(f"PORTFOLIO_STATE_{portfolio_quality}")
    if market_quality != "VERIFIED":
        gaps.append(f"MARKET_CONTEXT_{market_quality}")
    if seasonality_quality != "VERIFIED":
        gaps.append(f"SEASONALITY_{seasonality_quality}")
    if not methodology_refs:
        gaps.append("METHODOLOGY_CLAIMS_UNAVAILABLE")

    if portfolio_quality == "CONFLICTED":
        thesis_state = "CONFLICTED"
        posture = "RESEARCH_FIRST"
    elif gaps:
        thesis_state = "INSUFFICIENT_DATA"
        posture = "HOLD_CASH_RESEARCH_FIRST"
    else:
        thesis_state = "CURRENT"
        posture = "POLICY_ALIGNED_REVIEW"

    observed_cash = portfolio_state.get("observed_cash_usd")
    cash_pct = ((portfolio_state.get("allocation") or {}).get("cash") or {}).get("pct")
    market_regime = (((market_context.get("fields") or {}).get("regime") or {}).get("value"))
    if cash_pct is not None and cash_pct >= 30:
        risks.append("MATERIAL_CASH_OPPORTUNITY_COST")
    if portfolio_state.get("conflicted_position_count"):
        risks.append("POSITION_TRUTH_CONFLICT")
    if market_quality != "VERIFIED":
        risks.append("MARKET_CONTEXT_INCOMPLETE")

    refs = []
    for thesis in symbol_theses or []:
        if not isinstance(thesis, dict):
            continue
        refs.append({
            "symbol": thesis.get("symbol"),
            "thesis_id": thesis.get("thesis_id"),
            "thesis_version": thesis.get("thesis_version"),
            "stance": thesis.get("stance"),
            "portfolio_role": thesis.get("portfolio_role"),
        })
    refs.sort(key=lambda row: str(row.get("symbol") or ""))

    sleeve_postures = {
        "equity": _allocation_posture(policy, portfolio_state, "equity_range_pct", "equity"),
        "fixed_income": _allocation_posture(policy, portfolio_state, "fixed_income_range_pct", "fixed_income"),
        "alternatives": _allocation_posture(policy, portfolio_state, "alternatives_range_pct", "other"),
    }
    underweight_sleeves = sorted(name for name, row in sleeve_postures.items() if row["state"] == "UNDERWEIGHT")
    overweight_sleeves = sorted(name for name, row in sleeve_postures.items() if row["state"] == "OVERWEIGHT")

    candidate = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "generated_at": now.isoformat(),
        "thesis_id": "cio_portfolio",
        "state": thesis_state,
        "current_posture": posture,
        "cash_posture": {
            "observed_cash_usd": observed_cash,
            "investable_cash_usd": portfolio_state.get("investable_cash_usd"),
            "cash_pct": cash_pct,
            "policy_range_pct": ((policy.get("fields") or {}).get("cash_target_range_pct") or {}).get("value"),
            "state": "UNVERIFIED_INVESTABLE" if portfolio_state.get("investable_cash_usd") is None else "VERIFIED",
        },
        "equity_posture": sleeve_postures["equity"],
        "fixed_income_posture": sleeve_postures["fixed_income"],
        "growth_posture": {"state": "POLICY_REQUIRED" if policy_status != "CONFIRMED" else "REVIEW"},
        "income_posture": {"state": "POLICY_REQUIRED" if policy_status != "CONFIRMED" else "REVIEW"},
        "defensive_posture": {"state": "REVIEW", "market_regime": market_regime},
        "concentration_posture": {"state": "POLICY_REQUIRED" if policy_status != "CONFIRMED" else "REVIEW"},
        "tax_posture": {"state": "POLICY_REQUIRED" if policy_status != "CONFIRMED" else "REVIEW"},
        "market_regime": market_regime,
        "one_month_view": "INSUFFICIENT_DATA" if market_quality != "VERIFIED" else "CONTEXT_ONLY",
        "three_month_view": "INSUFFICIENT_DATA" if seasonality_quality != "VERIFIED" else "CONTEXT_ONLY",
        "quarter_view": "INSUFFICIENT_DATA" if seasonality_quality != "VERIFIED" else "CONTEXT_ONLY",
        "core_thesis": "Preserve optionality and close policy, cash, market, and methodology gaps before recommending deployment." if gaps else "Review capital against confirmed policy and current evidence; non-action remains valid.",
        "supporting_evidence": [
            {"kind": "portfolio_state", "version": portfolio_state.get("version"), "truth_quality": portfolio_quality},
            {"kind": "market_context", "version": market_context.get("version"), "truth_quality": market_quality},
            {"kind": "seasonality", "version": seasonality.get("version"), "truth_quality": seasonality_quality},
        ],
        "counter_thesis": "If verified investable cash is material and risk-on participation broadens, delaying deployment may create opportunity cost; policy confirmation and complete evidence are still required.",
        "risks": sorted(set(risks)),
        "opportunities": [],
        "underweight_sleeves": underweight_sleeves,
        "overweight_sleeves": overweight_sleeves,
        "cash_deployment_thesis": "POLICY_REQUIRED" if policy_status != "CONFIRMED" else "VERIFY_INVESTABLE_CASH",
        "deploy_more_conditions": ["CONFIRMED_POLICY", "VERIFIED_INVESTABLE_CASH", "CURRENT_MARKET_CONTEXT", "VALID_LIVING_THESES"],
        "deploy_less_conditions": ["MARKET_CONTEXT_DEGRADES", "VALUATION_HURDLE_NOT_MET", "FORWARD_EVENT_RISK"],
        "raise_cash_conditions": ["CONFIRMED_POLICY_REQUIRES", "MULTIPLE_THESIS_INVALIDATIONS", "MATERIAL_RISK_REGIME_SHIFT"],
        "what_changes_the_cio_mind": ["OPERATOR_POLICY_RATIFIED", "INVESTABLE_CASH_VERIFIED", "CONTRADICTORY_EVIDENCE", "BENCHMARKED_OUTCOMES"],
        "research_gaps": sorted(set(gaps)),
        "next_review": "AFTER_POLICY_AND_CASH_VERIFICATION" if gaps else "WEEKLY_OR_MATERIAL_CHANGE",
        "operator_policy_version": policy.get("version"),
        "operator_policy_hash": policy.get("content_hash"),
        "portfolio_state_version": portfolio_state.get("version"),
        "market_context_version": market_context.get("version"),
        "seasonality_version": seasonality.get("version"),
        "symbol_thesis_refs": refs,
        "feedback_refs": sorted(set(feedback_refs or [])),
        "outcome_refs": sorted(set(outcome_refs or [])),
        "methodology_refs": sorted(set(methodology_refs or [])),
        "financial_action": False,
    }
    candidate["content_hash"] = _hash(_content(candidate))
    return candidate


def classify_portfolio_thesis_delta(prior: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if candidate.get("content_hash") not in {None, _hash(_content(candidate))}:
        raise ValueError("candidate content_hash mismatch")
    candidate_hash = _hash(_content(candidate))
    prior_hash = _hash(_content(prior)) if prior else None
    if prior and candidate_hash == prior_hash:
        classification = "NO_NEW_INFO"
        reasons = ["IDENTICAL_SEMANTIC_CONTENT"]
    elif candidate.get("state") == "CONFLICTED":
        classification = "INVALIDATES" if prior and prior.get("state") == "CURRENT" else "CONFLICTED"
        reasons = ["CANONICAL_INPUT_CONFLICT"]
    elif candidate.get("state") == "INSUFFICIENT_DATA":
        classification = "INSUFFICIENT_DATA"
        reasons = list(candidate.get("research_gaps") or [])
    elif not prior:
        classification = "CONFIRMS"
        reasons = ["INITIAL_PORTFOLIO_THESIS"]
    elif prior.get("current_posture") != candidate.get("current_posture"):
        classification = "ROTATES"
        reasons = ["PORTFOLIO_POSTURE_CHANGED"]
    else:
        prior_gaps = set(prior.get("research_gaps") or [])
        current_gaps = set(candidate.get("research_gaps") or [])
        if len(current_gaps) < len(prior_gaps):
            classification = "STRENGTHENS"
            reasons = ["RESEARCH_GAPS_CLOSED"]
        elif len(current_gaps) > len(prior_gaps):
            classification = "WEAKENS"
            reasons = ["RESEARCH_GAPS_ADDED"]
        else:
            classification = "CONFIRMS"
            reasons = ["EVIDENCE_REFRESHED_WITHOUT_POSTURE_CHANGE"]
    if classification not in DELTA_CLASSES:
        raise AssertionError(classification)
    return {
        "schema": DELTA_SCHEMA,
        "authority": AUTHORITY,
        "classification": classification,
        "reason_codes": reasons,
        "prior_thesis_version": prior.get("thesis_version") if prior else None,
        "prior_content_hash": prior_hash,
        "candidate_content_hash": candidate_hash,
        "material": classification not in {"NO_NEW_INFO", "CONFIRMS"},
        "financial_action": False,
    }


def load_latest_portfolio_thesis(store_path: str = DEFAULT_STORE) -> dict[str, Any] | None:
    path = Path(store_path)
    if not path.exists():
        return None
    latest = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("record_type") == "PORTFOLIO_THESIS_PUBLISHED" and isinstance(row.get("thesis"), dict):
            latest = row["thesis"]
    return latest


def reconcile_portfolio_thesis(candidate: dict[str, Any], *, store_path: str = DEFAULT_STORE) -> dict[str, Any]:
    path = Path(store_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(path) + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o640)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        prior = load_latest_portfolio_thesis(store_path)
        delta = classify_portfolio_thesis_delta(prior, candidate)
        if delta["classification"] == "NO_NEW_INFO":
            return {"published": False, "thesis": prior, "delta": delta, "authority": AUTHORITY}
        version = int(prior.get("version") or 0) + 1 if prior else 1
        thesis = dict(candidate)
        thesis.update({"version": version, "thesis_version": f"cio_portfolio@v{version}", "published_at": _now()})
        record = {
            "record_type": "PORTFOLIO_THESIS_PUBLISHED",
            "recorded_at": _now(),
            "thesis": thesis,
            "delta": delta,
        }
        record["record_hash"] = _hash(record)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return {"published": True, "thesis": thesis, "delta": delta, "authority": AUTHORITY}
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

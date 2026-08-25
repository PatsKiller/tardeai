"""CIOSituationState@v1 — deterministic portfolio situation engine.

Answers: what material situation deserves the operator's attention now?

Detection is pure Python. Narrative synthesis lives in cio_advisory_synthesis.
READ_ONLY_ADVISORY. MEMORY_BEHAVIOR_INFLUENCE=0. Never emits an executable order.

Reuses CashDeploymentSituation@v1 for cash math. Does not duplicate S1–S8 plan
catalog types; those remain draft-plan identities. This contract is the office
attention layer above them.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from scripts.lib.cio_cash_capital_v1 import (
    ATTENTION_CASH_PCT,
    AUTHORITY as CASH_AUTHORITY,
    build_cash_deployment_situation,
    independently_material_cash,
)

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CIOSituationState@v1"
SCAN_SCHEMA = "OfficeSituationScan@v1"
MEMORY_BEHAVIOR_INFLUENCE = 0

SITUATION_CLASSES = (
    "EXCESS_CASH",
    "ALLOCATION_DRIFT",
    "CONCENTRATION",
    "THESIS_DETERIORATION",
    "THESIS_IMPROVEMENT",
    "MARKET_REGIME_CHANGE",
    "SEASONAL_SETUP",
    "CATALYST_APPROACHING",
    "REENTRY_READY",
    "RESEARCH_GAP_RESOLVED",
    "CONTRADICTION",
    "POLICY_GAP",
    "OUTCOME_MATURITY",
    "NO_MATERIAL_CHANGE",
)

# Engine attention thresholds — not operator policy.
ATTENTION_CONCENTRATION_PCT = 15.0
ATTENTION_ALLOCATION_DRIFT_PCT = 5.0
CATALYST_HORIZON_DAYS = 10

LEGACY_PLAN_TYPE = {
    "EXCESS_CASH": "S5_CASH_DEPLOYMENT",
    "ALLOCATION_DRIFT": "S5_CASH_DEPLOYMENT",
    "CONCENTRATION": "S6_CONCENTRATION_OR_DISPOSITION",
    "REENTRY_READY": "S3_REENTRY_CANDIDATE",
    "MARKET_REGIME_CHANGE": "S8_DEFENSIVE_REGIME",
    "SEASONAL_SETUP": "S4_SECTOR_ROTATION",
    "CATALYST_APPROACHING": "S1_POSITION_LIFECYCLE",
    "THESIS_DETERIORATION": "S1_POSITION_LIFECYCLE",
    "THESIS_IMPROVEMENT": "S1_POSITION_LIFECYCLE",
    "POLICY_GAP": "S0_OPERATOR_CONVERSE",
}

NOTIFY = "NOTIFY"
SUPPRESS = "SUPPRESS"
DEFER = "DEFER"


def _now(evaluated_at: datetime | None = None) -> datetime:
    return evaluated_at or datetime.now(timezone.utc)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _confirmed_field(policy: dict[str, Any], name: str) -> Any:
    field = (policy.get("fields") or {}).get(name) or {}
    if not isinstance(field, dict):
        return None
    return field.get("value") if field.get("operator_confirmed") else None


def _concentration_limit(policy: dict[str, Any]) -> float | None:
    hierarchy = _confirmed_field(policy, "concentration_hierarchy")
    if isinstance(hierarchy, dict):
        for key in ("max_single_name_pct", "max_single_position_pct", "max_name_pct"):
            n = _num(hierarchy.get(key))
            if n is not None:
                return n
    direct = _confirmed_field(policy, "max_single_position_pct")
    return _num(direct)


def _sleeve_range(policy: dict[str, Any], field_name: str) -> tuple[float, float] | None:
    raw = _confirmed_field(policy, field_name)
    if isinstance(raw, dict) and raw.get("min") is not None and raw.get("max") is not None:
        return float(raw["min"]), float(raw["max"])
    return None


def _holdings(portfolio_state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = portfolio_state.get("holdings") or portfolio_state.get("positions") or []
    if isinstance(rows, dict):
        out = []
        for sym, row in rows.items():
            if isinstance(row, dict):
                item = dict(row)
                item.setdefault("symbol", sym)
                out.append(item)
        return out
    return [r for r in rows if isinstance(r, dict)]


def _guid(row: dict[str, Any]) -> str | None:
    for key in ("security_guid", "guid", "identity_guid", "listing_guid"):
        value = row.get(key)
        if value:
            return str(value)
    return None


def situation_id() -> str:
    return f"sit_{uuid.uuid4().hex[:16]}"


def build_situation_state(
    *,
    situation_class: str,
    portfolio_id: str,
    affected_guids: list[str] | None,
    materiality: str,
    support: list[Any],
    counterevidence: list[Any],
    policy_references: list[str],
    prior_state: Any,
    new_state: Any,
    what_changed: str,
    confidence: float,
    freshness: str,
    notification_eligibility: str,
    suppression_reason: str | None,
    extra: dict[str, Any] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if situation_class not in SITUATION_CLASSES:
        raise ValueError(f"unknown_situation_class:{situation_class}")
    now = _now(evaluated_at)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "situation_id": situation_id(),
        "situation_class": situation_class,
        "portfolio_id": portfolio_id,
        "affected_guids": list(affected_guids or []),
        "materiality": materiality,
        "support": list(support or []),
        "counterevidence": list(counterevidence or []),
        "policy_references": list(policy_references or []),
        "prior_state": prior_state,
        "new_state": new_state,
        "what_changed": what_changed,
        "confidence": float(confidence),
        "freshness": freshness,
        "notification_eligibility": notification_eligibility,
        "suppression_reason": suppression_reason,
        "legacy_plan_type": LEGACY_PLAN_TYPE.get(situation_class),
        "authority": AUTHORITY,
        "memory_behavior_influence": MEMORY_BEHAVIOR_INFLUENCE,
        "financial_action": False,
        "executable_order": None,
        "generated_at": now.isoformat(),
    }
    if extra:
        payload.update(extra)
    payload["fingerprint"] = _hash({
        "situation_class": situation_class,
        "portfolio_id": portfolio_id,
        "affected_guids": payload["affected_guids"],
        "new_state": new_state,
        "what_changed": what_changed,
        "notification_eligibility": notification_eligibility,
        "suppression_reason": suppression_reason,
    })
    return payload


def _notify_or_defer(*, eligible: bool, defer: bool, reason: str | None) -> tuple[str, str | None]:
    if defer:
        return DEFER, reason or "NEED_DATA"
    if eligible:
        return NOTIFY, None
    return SUPPRESS, reason or "NOT_MATERIAL"


def detect_cash(office: dict[str, Any], *, evaluated_at: datetime | None = None) -> list[dict[str, Any]]:
    cash = build_cash_deployment_situation(
        policy=office.get("policy") or {},
        portfolio_state=office.get("portfolio_state") or {},
        market_context=office.get("market_context") or {},
        seasonality=office.get("seasonality") or {},
        portfolio_thesis=office.get("portfolio_thesis"),
        evaluated_at=evaluated_at,
    )
    klass = str(cash.get("situation_class") or "NO_MATERIAL_CHANGE")
    if klass not in SITUATION_CLASSES:
        klass = "NO_MATERIAL_CHANGE"
    note = cash.get("notification") or {}
    eligibility, suppression = _notify_or_defer(
        eligible=bool(note.get("eligible")),
        defer="INVESTABLE_CASH_UNVERIFIED" in (cash.get("blockers") or []) and not cash.get("policy_gap"),
        reason=note.get("suppression_reason"),
    )
    if cash.get("policy_gap"):
        klass = "POLICY_GAP"
        eligibility = NOTIFY
        suppression = None
    prior = (office.get("prior_situations") or {}).get("cash")
    sit = build_situation_state(
        situation_class=klass,
        portfolio_id=str(office.get("portfolio_id") or "primary"),
        affected_guids=["cash:book"],
        materiality="HIGH" if cash.get("material") else "NONE",
        support=cash.get("supporting_evidence") or [],
        counterevidence=[cash.get("counter_case")] if cash.get("counter_case") else [],
        policy_references=cash.get("missing_policy_fields") or [],
        prior_state=prior,
        new_state={
            "conclusion": cash.get("conclusion"),
            "cash_pct": cash.get("cash_pct"),
            "deviation_state": cash.get("deviation_state"),
            "deployable_excess_usd": cash.get("deployable_excess_usd"),
            "regime_risk_off": cash.get("regime_risk_off"),
        },
        what_changed="cash_posture" if cash.get("material") else "NO_NEW_INFO",
        confidence=0.9 if cash.get("material") else 0.7,
        freshness="CURRENT" if (office.get("portfolio_state") or {}).get("truth_quality") == "VERIFIED" else "STALE",
        notification_eligibility=eligibility,
        suppression_reason=suppression,
        extra={"cash_situation": cash, "cio_conclusion": cash.get("conclusion")},
        evaluated_at=evaluated_at,
    )
    return [sit]


def detect_concentration(office: dict[str, Any], *, evaluated_at: datetime | None = None) -> list[dict[str, Any]]:
    policy = office.get("policy") or {}
    limit = _concentration_limit(policy)
    out: list[dict[str, Any]] = []
    for row in _holdings(office.get("portfolio_state") or {}):
        weight = _num(row.get("weight_pct") or row.get("portfolio_weight_pct"))
        if weight is None:
            continue
        guid = _guid(row)
        symbol = str(row.get("symbol") or row.get("ticker") or "").upper()
        if guid is None and not symbol:
            continue
        identity = guid or f"UNRESOLVED:{symbol or 'unknown'}"
        if limit is None:
            if weight >= ATTENTION_CONCENTRATION_PCT:
                eligibility, suppression = NOTIFY, None
                klass = "POLICY_GAP"
                materiality = "HIGH"
            else:
                continue
        elif weight > float(limit):
            eligibility, suppression = NOTIFY, None
            klass = "CONCENTRATION"
            materiality = "HIGH"
        else:
            continue
        out.append(build_situation_state(
            situation_class=klass,
            portfolio_id=str(office.get("portfolio_id") or "primary"),
            affected_guids=[identity],
            materiality=materiality,
            support=[{"symbol": symbol, "weight_pct": weight, "limit_pct": limit}],
            counterevidence=[],
            policy_references=["concentration_hierarchy"] if limit is None else ["concentration_hierarchy"],
            prior_state=None,
            new_state={"symbol": symbol, "weight_pct": weight, "limit_pct": limit, "identity": identity},
            what_changed=f"{symbol} weight {weight:.1f}% vs policy {limit if limit is not None else 'UNCONFIRMED'}",
            confidence=0.85,
            freshness="CURRENT",
            notification_eligibility=eligibility,
            suppression_reason=suppression,
            extra={
                "cio_conclusion": "POLICY_QUESTION" if klass == "POLICY_GAP" else "REVIEW_CONCENTRATION",
                "identity_unresolved": guid is None,
            },
            evaluated_at=evaluated_at,
        ))
    return out


def detect_allocation_drift(office: dict[str, Any], *, evaluated_at: datetime | None = None) -> list[dict[str, Any]]:
    policy = office.get("policy") or {}
    allocation = ((office.get("portfolio_state") or {}).get("allocation") or {})
    mapping = {
        "equity": "equity_range_pct",
        "fixed_income": "fixed_income_range_pct",
        "alternatives": "alternatives_range_pct",
    }
    missing = []
    drifts = []
    for sleeve, field in mapping.items():
        rng = _sleeve_range(policy, field)
        pct = _num((allocation.get(sleeve) or {}).get("pct") if isinstance(allocation.get(sleeve), dict) else allocation.get(sleeve))
        if rng is None:
            if pct is not None:
                missing.append(field)
            continue
        if pct is None:
            continue
        low, high = rng
        if pct > high + 1e-9 or pct < low - 1e-9:
            drifts.append({"sleeve": sleeve, "pct": pct, "min": low, "max": high})
    if missing and independently_material_cash(
        ((office.get("portfolio_state") or {}).get("allocation") or {}).get("cash", {}).get("pct")
        if isinstance(((office.get("portfolio_state") or {}).get("allocation") or {}).get("cash"), dict)
        else None
    ):
        # sleeve policy missing is only a POLICY_GAP when something else is already material;
        # cash attention is a proxy for "the book is worth asking about".
        return [build_situation_state(
            situation_class="POLICY_GAP",
            portfolio_id=str(office.get("portfolio_id") or "primary"),
            affected_guids=["allocation:book"],
            materiality="MEDIUM",
            support=missing,
            counterevidence=[],
            policy_references=missing,
            prior_state=None,
            new_state={"missing_fields": missing},
            what_changed="allocation policy unconfirmed",
            confidence=0.7,
            freshness="CURRENT",
            notification_eligibility=NOTIFY,
            suppression_reason=None,
            extra={"cio_conclusion": "POLICY_QUESTION"},
            evaluated_at=evaluated_at,
        )]
    if not drifts:
        return []
    return [build_situation_state(
        situation_class="ALLOCATION_DRIFT",
        portfolio_id=str(office.get("portfolio_id") or "primary"),
        affected_guids=["allocation:book"],
        materiality="HIGH",
        support=drifts,
        counterevidence=[],
        policy_references=[mapping[d["sleeve"]] for d in drifts],
        prior_state=None,
        new_state={"drifts": drifts},
        what_changed="; ".join(f"{d['sleeve']} {d['pct']:.1f}% outside {d['min']}-{d['max']}" for d in drifts),
        confidence=0.88,
        freshness="CURRENT",
        notification_eligibility=NOTIFY,
        suppression_reason=None,
        extra={"cio_conclusion": "REVIEW_ALLOCATION"},
        evaluated_at=evaluated_at,
    )]


def detect_thesis_deltas(office: dict[str, Any], *, evaluated_at: datetime | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cognition = office.get("ticker_cognition") or {}
    for key, row in cognition.items():
        if not isinstance(row, dict):
            continue
        delta = str(row.get("thesis_delta") or row.get("curation_delta") or "").upper()
        guid = _guid(row) or (None if key.startswith("UNRESOLVED") else key)
        symbol = str(row.get("symbol") or "").upper()
        identity = guid or f"UNRESOLVED:{symbol or key}"
        if delta in {"DETERIORATE", "DETERIORATION", "MATERIAL_NEGATIVE", "DOWN"}:
            klass = "THESIS_DETERIORATION"
            conclusion = "REVIEW_HOLDING"
        elif delta in {"IMPROVE", "IMPROVEMENT", "MATERIAL_POSITIVE", "UP"}:
            klass = "THESIS_IMPROVEMENT"
            conclusion = "REVIEW_OPPORTUNITY"
        else:
            continue
        out.append(build_situation_state(
            situation_class=klass,
            portfolio_id=str(office.get("portfolio_id") or "primary"),
            affected_guids=[identity],
            materiality="HIGH",
            support=[row.get("support") or row.get("summary") or delta],
            counterevidence=[row.get("counterevidence")] if row.get("counterevidence") else [],
            policy_references=[],
            prior_state=row.get("prior_thesis"),
            new_state={"symbol": symbol, "delta": delta, "research_complete": bool(row.get("research_complete"))},
            what_changed=f"{symbol or key} {delta}",
            confidence=float(row.get("confidence") or 0.8),
            freshness=str(row.get("freshness") or "CURRENT"),
            notification_eligibility=NOTIFY,
            suppression_reason=None,
            extra={"cio_conclusion": conclusion, "identity_unresolved": guid is None},
            evaluated_at=evaluated_at,
        ))
    return out


def detect_market_and_seasonality(office: dict[str, Any], *, evaluated_at: datetime | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    market = office.get("market_context") or {}
    prior = (office.get("prior_situations") or {}).get("market_regime")
    fields = market.get("fields") or {}
    regime = (fields.get("regime") or {}).get("value") if isinstance(fields.get("regime"), dict) else market.get("regime")
    prior_regime = prior if not isinstance(prior, dict) else prior.get("regime")
    if regime and prior_regime and str(regime) != str(prior_regime):
        out.append(build_situation_state(
            situation_class="MARKET_REGIME_CHANGE",
            portfolio_id=str(office.get("portfolio_id") or "primary"),
            affected_guids=["market:book"],
            materiality="HIGH",
            support=[{"prior": prior_regime, "new": regime}],
            counterevidence=[],
            policy_references=[],
            prior_state=prior_regime,
            new_state={"regime": regime},
            what_changed=f"regime {prior_regime} → {regime}",
            confidence=0.8,
            freshness="CURRENT" if market.get("truth_quality") == "VERIFIED" else "PARTIAL",
            notification_eligibility=NOTIFY,
            suppression_reason=None,
            extra={"cio_conclusion": "REASSESS_POSTURE"},
            evaluated_at=evaluated_at,
        ))
    season = office.get("seasonality") or {}
    if season.get("material_setup") or season.get("setup"):
        if season.get("material_change") or season.get("material_setup"):
            out.append(build_situation_state(
                situation_class="SEASONAL_SETUP",
                portfolio_id=str(office.get("portfolio_id") or "primary"),
                affected_guids=["seasonality:book"],
                materiality="MEDIUM",
                support=[season.get("setup") or season.get("benchmark")],
                counterevidence=[],
                policy_references=[],
                prior_state=(office.get("prior_situations") or {}).get("seasonality"),
                new_state={"setup": season.get("setup"), "window": season.get("window")},
                what_changed=str(season.get("what_changed") or season.get("setup") or "seasonal setup"),
                confidence=0.7,
                freshness=str(season.get("truth_quality") or "UNAVAILABLE"),
                notification_eligibility=NOTIFY if season.get("truth_quality") == "VERIFIED" else DEFER,
                suppression_reason=None if season.get("truth_quality") == "VERIFIED" else "SEASONALITY_UNVERIFIED",
                extra={"cio_conclusion": "CONSIDER_SEASONAL_CONTEXT"},
                evaluated_at=evaluated_at,
            ))
    return out


def detect_catalysts_and_reentry(office: dict[str, Any], *, evaluated_at: datetime | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in office.get("catalysts") or []:
        if not isinstance(row, dict):
            continue
        days = _num(row.get("days_to_event") or row.get("horizon_days"))
        if days is None or days > CATALYST_HORIZON_DAYS:
            continue
        symbol = str(row.get("symbol") or "").upper()
        guid = _guid(row) or f"UNRESOLVED:{symbol or 'catalyst'}"
        out.append(build_situation_state(
            situation_class="CATALYST_APPROACHING",
            portfolio_id=str(office.get("portfolio_id") or "primary"),
            affected_guids=[guid],
            materiality="MEDIUM",
            support=[row],
            counterevidence=[],
            policy_references=[],
            prior_state=None,
            new_state={"symbol": symbol, "days_to_event": days, "event": row.get("event")},
            what_changed=f"{symbol} catalyst in {days:.0f}d",
            confidence=0.75,
            freshness="CURRENT",
            notification_eligibility=NOTIFY,
            suppression_reason=None,
            extra={"cio_conclusion": "PREPARE_FOR_CATALYST"},
            evaluated_at=evaluated_at,
        ))
    for row in office.get("opportunities") or []:
        if not isinstance(row, dict):
            continue
        if not (row.get("research_complete") and row.get("priority") in {"HIGH", "high", 1, "1"}):
            continue
        symbol = str(row.get("symbol") or "").upper()
        guid = _guid(row) or f"UNRESOLVED:{symbol or 'opportunity'}"
        out.append(build_situation_state(
            situation_class="REENTRY_READY",
            portfolio_id=str(office.get("portfolio_id") or "primary"),
            affected_guids=[guid],
            materiality="HIGH",
            support=[row.get("thesis") or "research_complete"],
            counterevidence=[],
            policy_references=[],
            prior_state=None,
            new_state={"symbol": symbol, "research_complete": True, "priority": row.get("priority")},
            what_changed=f"{symbol} re-entry research complete",
            confidence=0.8,
            freshness="CURRENT",
            notification_eligibility=NOTIFY,
            suppression_reason=None,
            extra={"cio_conclusion": "REVIEW_REENTRY"},
            evaluated_at=evaluated_at,
        ))
    return out


def detect_gaps_contradictions_outcomes(office: dict[str, Any], *, evaluated_at: datetime | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in office.get("research_gaps") or []:
        if not isinstance(row, dict):
            continue
        if row.get("resolved") or row.get("state") == "RESOLVED":
            symbol = str(row.get("symbol") or "").upper()
            guid = _guid(row) or f"UNRESOLVED:{symbol or 'gap'}"
            out.append(build_situation_state(
                situation_class="RESEARCH_GAP_RESOLVED",
                portfolio_id=str(office.get("portfolio_id") or "primary"),
                affected_guids=[guid],
                materiality="MEDIUM",
                support=[row],
                counterevidence=[],
                policy_references=[],
                prior_state="OPEN",
                new_state="RESOLVED",
                what_changed=f"{symbol} research gap resolved",
                confidence=0.8,
                freshness="CURRENT",
                notification_eligibility=NOTIFY,
                suppression_reason=None,
                extra={"cio_conclusion": "INCORPORATE_NEW_EVIDENCE"},
                evaluated_at=evaluated_at,
            ))
        elif row.get("critical") or row.get("severity") == "CRITICAL":
            # Unresolved critical evidence is a NEED_DATA defer, not a silent drop.
            symbol = str(row.get("symbol") or "book").upper()
            guid = _guid(row) or f"UNRESOLVED:{symbol}"
            out.append(build_situation_state(
                situation_class="NO_MATERIAL_CHANGE",
                portfolio_id=str(office.get("portfolio_id") or "primary"),
                affected_guids=[guid],
                materiality="MEDIUM",
                support=[],
                counterevidence=[row],
                policy_references=[],
                prior_state=None,
                new_state={"need_data": True, "gap": row.get("field") or row.get("reason")},
                what_changed="NEED_DATA",
                confidence=0.6,
                freshness="STALE",
                notification_eligibility=DEFER,
                suppression_reason="NEED_DATA",
                extra={"cio_conclusion": "NEED_DATA", "need_data": True},
                evaluated_at=evaluated_at,
            ))
    for row in office.get("contradictions") or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "book").upper()
        guid = _guid(row) or f"UNRESOLVED:{symbol}"
        out.append(build_situation_state(
            situation_class="CONTRADICTION",
            portfolio_id=str(office.get("portfolio_id") or "primary"),
            affected_guids=[guid],
            materiality="HIGH",
            support=row.get("support") or [],
            counterevidence=row.get("counterevidence") or [row],
            policy_references=[],
            prior_state=None,
            new_state={"symbol": symbol, "conflict": row.get("summary")},
            what_changed=str(row.get("summary") or "conflicting evidence"),
            confidence=0.65,
            freshness="CURRENT",
            notification_eligibility=NOTIFY,
            suppression_reason=None,
            extra={"cio_conclusion": "DO_NOT_ACT_WHILE_CONFLICTED"},
            evaluated_at=evaluated_at,
        ))
    for row in office.get("outcomes") or []:
        if not isinstance(row, dict):
            continue
        if row.get("mature") or (isinstance(row.get("outcome_ids"), list) and len(row["outcome_ids"]) >= 5):
            out.append(build_situation_state(
                situation_class="OUTCOME_MATURITY",
                portfolio_id=str(office.get("portfolio_id") or "primary"),
                affected_guids=[str(row.get("subject_guid") or "outcome:book")],
                materiality="LOW",
                support=[row],
                counterevidence=[],
                policy_references=[],
                prior_state="OBSERVING",
                new_state="LESSON_CANDIDATE",
                what_changed="outcome sample matured",
                confidence=0.6,
                freshness="CURRENT",
                notification_eligibility=SUPPRESS,
                suppression_reason="LESSON_CANDIDATE_NOT_POLICY",
                extra={"cio_conclusion": "RECORD_LESSON_CANDIDATE", "memory_behavior_influence": 0},
                evaluated_at=evaluated_at,
            ))
    return out


def _dedupe_policy_gaps(situations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated POLICY_GAP rows into one bounded operator question."""
    gaps = [s for s in situations if s.get("situation_class") == "POLICY_GAP"]
    others = [s for s in situations if s.get("situation_class") != "POLICY_GAP"]
    if not gaps:
        return situations
    fields: list[str] = []
    guids: list[str] = []
    support: list[Any] = []
    for gap in gaps:
        fields.extend(str(x) for x in (gap.get("policy_references") or []))
        guids.extend(str(x) for x in (gap.get("affected_guids") or []))
        support.extend(gap.get("support") or [])
    fields = sorted(set(fields))
    primary = dict(gaps[0])
    primary["affected_guids"] = sorted(set(guids))
    primary["policy_references"] = fields
    primary["support"] = support
    primary["what_changed"] = "policy inputs unconfirmed: " + ", ".join(fields)
    primary["new_state"] = {"missing_fields": fields}
    primary["fingerprint"] = _hash({
        "situation_class": "POLICY_GAP",
        "missing_fields": fields,
        "guids": primary["affected_guids"],
    })
    return others + [primary]


def detect_office_situations(office: dict[str, Any], *, evaluated_at: datetime | None = None) -> dict[str, Any]:
    """Deterministic office scan. No LLM. No broker writes."""
    portfolio = office.get("portfolio_state") or {}
    stale = str(portfolio.get("truth_quality") or "").upper() in {"STALE", "UNAVAILABLE", "CONFLICTED"}
    rows: list[dict[str, Any]] = []
    rows.extend(detect_cash(office, evaluated_at=evaluated_at))
    rows.extend(detect_concentration(office, evaluated_at=evaluated_at))
    rows.extend(detect_allocation_drift(office, evaluated_at=evaluated_at))
    rows.extend(detect_thesis_deltas(office, evaluated_at=evaluated_at))
    rows.extend(detect_market_and_seasonality(office, evaluated_at=evaluated_at))
    rows.extend(detect_catalysts_and_reentry(office, evaluated_at=evaluated_at))
    rows.extend(detect_gaps_contradictions_outcomes(office, evaluated_at=evaluated_at))
    rows = _dedupe_policy_gaps(rows)

    if stale:
        for row in rows:
            if row.get("notification_eligibility") == NOTIFY and row.get("situation_class") != "POLICY_GAP":
                row["notification_eligibility"] = DEFER
                row["suppression_reason"] = "STALE_FINANCIAL_TRUTH"

    material = [
        r for r in rows
        if r.get("situation_class") != "NO_MATERIAL_CHANGE" or r.get("need_data") or r.get("extra", {}).get("need_data")
        or r.get("cio_conclusion") == "NEED_DATA"
    ]
    # Drop pure no-change cash rows when another material situation exists.
    if any(r.get("situation_class") not in {"NO_MATERIAL_CHANGE"} for r in rows):
        rows = [r for r in rows if r.get("situation_class") != "NO_MATERIAL_CHANGE" or r.get("cio_conclusion") == "NEED_DATA"]

    if not rows or all(r.get("situation_class") == "NO_MATERIAL_CHANGE" and r.get("cio_conclusion") != "NEED_DATA" for r in rows):
        rows = [build_situation_state(
            situation_class="NO_MATERIAL_CHANGE",
            portfolio_id=str(office.get("portfolio_id") or "primary"),
            affected_guids=[],
            materiality="NONE",
            support=[],
            counterevidence=[],
            policy_references=[],
            prior_state=office.get("prior_situations"),
            new_state="UNCHANGED",
            what_changed="NO_NEW_INFO",
            confidence=0.95,
            freshness="CURRENT",
            notification_eligibility=SUPPRESS,
            suppression_reason="NO_MATERIAL_CHANGE",
            extra={"cio_conclusion": "NO_ACTION", "llm_required": False},
            evaluated_at=evaluated_at,
        )]

    notify = [r for r in rows if r.get("notification_eligibility") == NOTIFY]
    suppress = [r for r in rows if r.get("notification_eligibility") == SUPPRESS]
    defer = [r for r in rows if r.get("notification_eligibility") == DEFER]
    return {
        "schema": SCAN_SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MEMORY_BEHAVIOR_INFLUENCE,
        "financial_action": False,
        "executable_order": None,
        "portfolio_id": office.get("portfolio_id") or "primary",
        "situations": rows,
        "material_count": len([r for r in rows if r.get("situation_class") != "NO_MATERIAL_CHANGE"]),
        "notification_decision": NOTIFY if notify else (DEFER if defer else SUPPRESS),
        "notify": notify,
        "suppress": suppress,
        "defer": defer,
        "llm_required": bool(notify),
        "classes": sorted({str(r.get("situation_class")) for r in rows}),
    }

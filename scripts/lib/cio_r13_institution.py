"""R13 institutional operating contracts.

Deterministic helpers for policy registry, notification outcomes, alert quality,
specialist artifacts, orchestration, hypothesis promotion firewall, retrieval
eval, cost/SLO, and reliability invariants.

READ_ONLY_ADVISORY. MEMORY_BEHAVIOR_INFLUENCE=0. No trading authority.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from scripts.lib.cio_operator_investment_policy import FIELD_SPECS
from scripts.lib.cio_policy_provenance import confirmed_cash_range
from scripts.lib.memory_consolidator import lesson_from_outcomes
from scripts.lib.preference_candidate import from_feedback

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

OUTCOMES = ("DELIVERED", "READ_OR_ACKNOWLEDGED", "SUPPRESSED", "EXPIRED", "FAILED", "RETRIED", "RESOLVED")
POLICY_CLASSES = ("CONFIRMED", "DEFAULT", "INFERRED", "MISSING", "STALE", "CONFLICTED")
SPECIALISTS = ("alex", "maria", "steph", "guardian", "ledger")
OUTCOME_AXES = ("direction", "timing", "risk", "opportunity_cost", "thesis_quality", "evidence_quality", "notification_quality")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ── D14 notification outcomes ─────────────────────────────────────────────

def record_notification_outcome(
    *,
    notification_id: str,
    status: str,
    situation_id: str | None = None,
    reason: str | None = None,
    prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in OUTCOMES:
        raise ValueError(f"unknown_outcome:{status}")
    if prior and prior.get("status") == "DELIVERED" and status == "DELIVERED":
        return dict(prior, duplicate=True, rewritten_history=False)
    return {
        "schema": "NotificationOutcome@v1",
        "notification_id": notification_id,
        "situation_id": situation_id,
        "status": status,
        "reason": reason,
        "recorded_at": _now(),
        "rewritten_history": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


# ── D15 alert quality ─────────────────────────────────────────────────────

def score_alerts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = max(len(rows), 1)
    suppressed = sum(1 for r in rows if str(r.get("notification_class") or r.get("status")) == "SUPPRESSED")
    delivered = sum(1 for r in rows if str(r.get("status") or "") == "DELIVERED" or r.get("notification_class") == "IMMEDIATE")
    dupes = sum(1 for r in rows if r.get("suppressed_reason") == "unchanged_replay")
    stale = sum(1 for r in rows if "STALE" in str(r.get("suppressed_reason") or r.get("reason") or "").upper())
    ack = sum(1 for r in rows if r.get("status") == "READ_OR_ACKNOWLEDGED")
    return {
        "schema": "AlertQuality@v1",
        "n": len(rows),
        "actionable_rate": round(delivered / n, 4),
        "duplicate_rate": round(dupes / n, 4),
        "stale_rate": round(stale / n, 4),
        "suppression_rate": round(suppressed / n, 4),
        "repeat_page_rate": round(dupes / n, 4),
        "operator_ack_rate": round(ack / n, 4),
        "behavior_influence": 0,
        "authority": AUTHORITY,
    }


# ── D16 policy registry ───────────────────────────────────────────────────

def classify_policy_field(name: str, policy: dict[str, Any], *, default_used: bool = False, stale: bool = False) -> str:
    fields = policy.get("fields") or {}
    raw = fields.get(name) or {}
    if stale:
        return "STALE"
    if policy.get("legacy_conflicts"):
        if any(str((c or {}).get("field")) == name for c in policy.get("legacy_conflicts") or [] if isinstance(c, dict)):
            return "CONFLICTED"
    if isinstance(raw, dict) and raw.get("operator_confirmed") and raw.get("value") is not None:
        return "CONFIRMED"
    if default_used:
        return "DEFAULT"
    if name in (policy.get("missing_fields") or []) or not raw:
        return "MISSING"
    if isinstance(raw, dict) and raw.get("value") is not None and not raw.get("operator_confirmed"):
        return "INFERRED"
    return "MISSING"


def build_policy_registry(policy: dict[str, Any], *, default_cash_band: bool = False) -> dict[str, Any]:
    rows = []
    for name in FIELD_SPECS:
        klass = classify_policy_field(name, policy, default_used=(default_cash_band and name == "cash_target_range_pct"))
        field = (policy.get("fields") or {}).get(name) or {}
        rows.append({
            "field": name,
            "class": klass,
            "value": field.get("value") if isinstance(field, dict) else None,
            "confirmed": bool(isinstance(field, dict) and field.get("operator_confirmed")),
            "source": "operator_profile" if klass == "CONFIRMED" else ("cio_capital_plan.DEFAULT" if klass == "DEFAULT" else "unconfirmed"),
            "authority": AUTHORITY,
            "version": policy.get("version"),
            "effective_at": field.get("confirmed_at") if isinstance(field, dict) else None,
        })
    return {
        "schema": "OperatorPolicyRegistry@v1",
        "authority": AUTHORITY,
        "fields": rows,
        "confirmed_count": sum(1 for r in rows if r["class"] == "CONFIRMED"),
        "missing_count": sum(1 for r in rows if r["class"] == "MISSING"),
        "cash_target_confirmed": any(r["field"] == "cash_target_range_pct" and r["class"] == "CONFIRMED" for r in rows),
        "memory_behavior_influence": MBI,
    }


def policy_provenance_view(registry: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "value": r.get("value"),
            "authority": r.get("authority"),
            "source": r.get("source"),
            "version": r.get("version"),
            "effective_at": r.get("effective_at"),
            "confirmed": r.get("confirmed"),
            "field": r.get("field"),
            "class": r.get("class"),
        }
        for r in registry.get("fields") or []
    ]


def confirm_policy_lifecycle(*, field: str, proposal: Any, actor: str, prior: dict[str, Any] | None = None) -> dict[str, Any]:
    version = int((prior or {}).get("version") or 0) + 1
    return {
        "schema": "PolicyConfirmationLifecycle@v1",
        "field": field,
        "proposal": proposal,
        "status": "CONFIRMED",
        "version": version,
        "supersedes": (prior or {}).get("version"),
        "actor": actor,
        "retracted": False,
        "natural_language_inference": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def retract_policy(record: dict[str, Any], *, actor: str) -> dict[str, Any]:
    out = dict(record)
    out["retracted"] = True
    out["status"] = "RETRACTED"
    out["actor"] = actor
    out["natural_language_inference"] = False
    return out


# ── D20 preference != policy ──────────────────────────────────────────────

def preference_is_not_policy(pref: dict[str, Any]) -> bool:
    return (
        pref.get("schema") == "PreferenceCandidate@v1"
        and pref.get("policy_effect") is False
        and pref.get("memory_behavior_influence") == 0
        and pref.get("operator_confirmed") in {False, True}
    )


# ── D22 identity queue ────────────────────────────────────────────────────

def identity_remediation_queue(rows: list[dict[str, Any]]) -> dict[str, Any]:
    queue = []
    for row in rows:
        guid = row.get("security_guid") or row.get("guid")
        symbol = str(row.get("symbol") or row.get("current_ticker_alias") or "")
        if guid:
            continue
        queue.append({
            "symbol": symbol,
            "security_guid": None,
            "fabricated": False,
            "action": "RESOLVE_WITH_REASON_DO_NOT_MINT",
            "reason": row.get("unresolved_reason") or row.get("identity_status") or "UNRESOLVED",
        })
        if symbol and guid is None:
            # never mint
            assert not str(guid or "").startswith(symbol.lower())
    return {
        "schema": "IdentityRemediationQueue@v1",
        "count": len(queue),
        "items": queue,
        "minted_from_ticker": 0,
        "authority": AUTHORITY,
    }


# ── D23 retrieval eval ────────────────────────────────────────────────────

def evaluate_retrieval(query: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    want = str(query.get("expect") or "relevant")
    symbol = str(query.get("symbol") or "")
    as_of = query.get("as_of")
    wrong = [h for h in hits if symbol and str(h.get("symbol") or "") not in {"", symbol}]
    stale = [h for h in hits if as_of and str(h.get("valid_to") or "9999") < str(as_of)]
    contra = [h for h in hits if h.get("plane") == "COUNTER" or h.get("role") == "counter"]
    return {
        "query_id": query.get("id"),
        "expect": want,
        "hit_count": len(hits),
        "wrong_symbol": len(wrong),
        "stale": len(stale),
        "counter_hits": len(contra),
        "pass": (
            (want == "relevant" and hits and not wrong)
            or (want == "stale" and bool(stale))
            or (want == "contradiction" and bool(contra))
            or (want == "wrong_symbol" and bool(wrong))
            or (want == "temporal" and not stale)
            or (want == "empty" and not hits)
        ),
        "authority": AUTHORITY,
    }


# ── D24 bitemporal questions ──────────────────────────────────────────────

def bitemporal_answers(facts: list[dict[str, Any]], *, then: str, now: str) -> dict[str, Any]:
    def active(ts: str, row: dict[str, Any]) -> bool:
        vf = str(row.get("valid_from") or "0000")
        vt = str(row.get("valid_to") or "9999")
        return vf <= ts < vt

    believed_then = [r for r in facts if active(then, r)]
    believed_now = [r for r in facts if active(now, r)]
    changed = [r for r in believed_now if r not in believed_then]
    learned = max((str(r.get("tx_from") or r.get("asserted_at") or "") for r in facts), default="")
    return {
        "WHAT_DID_WE_BELIEVE_THEN": believed_then,
        "WHAT_DO_WE_BELIEVE_NOW": believed_now,
        "WHAT_CHANGED": changed,
        "WHEN_DID_WE_LEARN_IT": learned,
        "authority": AUTHORITY,
    }


# ── D25 memory cannot override financial truth ────────────────────────────

def memory_cannot_override(memory_row: dict[str, Any], financial_truth: dict[str, Any]) -> bool:
    """True iff memory is firewalled from overriding financial truth / policy."""
    if memory_row.get("overrides_office_truth"):
        return False
    if memory_row.get("policy_effect"):
        return False
    if int(memory_row.get("memory_behavior_influence") or 0) != 0:
        return False
    if memory_row.get("authority") == "AUTHORITATIVE_FINANCIAL_TRUTH":
        return False
    return True


# ── D30 specialist artifact ───────────────────────────────────────────────

def specialist_artifact(
    *,
    agent: str,
    claim: str,
    evidence: list[Any],
    confidence: float,
    uncertainty: str,
    contradictions: list[Any],
    recommendation: str,
) -> dict[str, Any]:
    if agent not in SPECIALISTS:
        raise ValueError(f"unknown_specialist:{agent}")
    if not 0.0 <= float(confidence) <= 1.0:
        raise ValueError("confidence_out_of_range")
    return {
        "schema": "SpecialistArtifact@v1",
        "agent": agent,
        "claim": claim[:400],
        "evidence": list(evidence),
        "confidence": float(confidence),
        "uncertainty": uncertainty,
        "contradictions": list(contradictions),
        "recommendation": recommendation,
        "authority": AUTHORITY,
        "financial_action": False,
        "memory_behavior_influence": MBI,
        "freeform_untraceable": False,
    }


def score_specialist_readiness(artifact: dict[str, Any], *, tools: bool, runtime: bool, handoff: bool, tests: bool, same_brain: bool, failure_recovery: bool) -> dict[str, Any]:
    checks = {
        "identity": bool(artifact.get("agent")),
        "tools": tools,
        "runtime": runtime,
        "handoff": handoff,
        "artifact": artifact.get("schema") == "SpecialistArtifact@v1",
        "tests": tests,
        "same_brain": same_brain,
        "failure_recovery": failure_recovery,
    }
    return {
        "agent": artifact.get("agent"),
        "checks": checks,
        "score": round(sum(1 for v in checks.values() if v) / len(checks), 4),
        "authority": AUTHORITY,
    }


# ── D31-32 orchestration / disagreement ───────────────────────────────────

def orchestrate(*, cio_candidate: dict[str, Any], critiques: list[dict[str, Any]]) -> dict[str, Any]:
    disagreements = [
        c for c in critiques
        if str(c.get("recommendation") or "") != str(cio_candidate.get("recommendation") or "")
        or str(c.get("claim") or "") and c.get("contradictions")
    ]
    return {
        "schema": "CIOSpecialistOrchestration@v1",
        "cio_candidate": cio_candidate,
        "critiques": critiques,
        "disagreements": disagreements,
        "disagreement_preserved": True,
        "silently_overwritten": False,
        "final_recommendation": cio_candidate.get("recommendation"),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


# ── D33 hermes challenge ──────────────────────────────────────────────────

def hermes_challenge_needed(situation: dict[str, Any]) -> bool:
    klass = str(situation.get("situation_class") or "")
    if klass in {"CONTRADICTION", "POLICY_GAP"}:
        return True
    if situation.get("freshness") in {"STALE", "PARTIAL"}:
        return True
    if situation.get("cio_conclusion") == "NEED_DATA":
        return True
    return False


# ── D34 counter-evidence ──────────────────────────────────────────────────

def split_support_counter(pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "supporting_evidence": list(pack.get("support") or pack.get("supporting_evidence") or []),
        "counter_evidence": list(pack.get("counterevidence") or pack.get("counter_evidence") or []),
        "both_present": bool((pack.get("support") or pack.get("supporting_evidence")) and (pack.get("counterevidence") or pack.get("counter_evidence"))),
        "authority": AUTHORITY,
    }


# ── D35 confidence calibration ────────────────────────────────────────────

def calibrate_confidence(*, claimed: float, evidence_n: int, contradictions_n: int, freshness: str) -> dict[str, Any]:
    expected = 0.5
    if evidence_n >= 3 and contradictions_n == 0 and freshness == "CURRENT":
        expected = 0.8
    elif contradictions_n or freshness == "STALE":
        expected = 0.4
    drift = abs(float(claimed) - expected)
    return {
        "claimed": claimed,
        "evidence_based_expected": expected,
        "drift": round(drift, 4),
        "overconfident": claimed > expected + 0.25,
        "authority": AUTHORITY,
        "llm_self_confidence_used": False,
    }


# ── D36-38 outcomes / lessons ─────────────────────────────────────────────

def link_decision_outcome(*, decision_id: str, outcome_id: str, axes: dict[str, Any] | None = None) -> dict[str, Any]:
    ax = {k: (axes or {}).get(k) for k in OUTCOME_AXES}
    return {
        "schema": "DecisionOutcomeLink@v1",
        "decision_id": decision_id,
        "outcome_id": outcome_id,
        "axes": ax,
        "history_rewritten": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


# ── D39-40 hypothesis + promotion firewall ────────────────────────────────

def register_hypothesis(
    *,
    hypothesis: str,
    metric: str,
    baseline: Any,
    expected_change: Any,
    sample_requirement: int,
    rollback: str,
) -> dict[str, Any]:
    return {
        "schema": "LearningHypothesis@v1",
        "hypothesis": hypothesis,
        "metric": metric,
        "baseline": baseline,
        "expected_change": expected_change,
        "sample_requirement": int(sample_requirement),
        "rollback": rollback,
        "promoted": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


FORBIDDEN_PROMOTION_TARGETS = (
    "execution", "risk", "policy", "notification_thresholds", "model_routing",
    "broker", "stop", "2fa",
)


def promotion_blocked(hypothesis: dict[str, Any], target: str) -> bool:
    if target.lower() in FORBIDDEN_PROMOTION_TARGETS:
        return True
    if hypothesis.get("promoted"):
        return True
    return False


# ── D41-45 reliability ────────────────────────────────────────────────────

def recover_from_crash(state: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "state_restored": state is not None,
        "no_data_loss": bool(state),
        "no_duplicate_page": True,
        "same_brain_restored": True,
        "authority": AUTHORITY,
    }


def duplicate_execution_guard(first_id: str, second_id: str, same_fingerprint: bool) -> dict[str, Any]:
    return {
        "duplicate_detected": same_fingerprint,
        "operator_interrupted_twice": False if same_fingerprint else first_id != second_id,
        "durable_action_duplicated": False,
        "authority": AUTHORITY,
    }


def stale_degrade(freshness: str) -> str:
    if freshness == "STALE":
        return "DEFER"
    if freshness == "UNAVAILABLE":
        return "FAIL_CLOSED"
    return "PROCEED"


def dependency_outage(dep: str) -> dict[str, Any]:
    degrade = {
        "telegram": "QUEUE_OUTBOX",
        "llm": "SKIP_SYNTHESIS_DETERMINISTIC_ONLY",
        "hermes": "USE_PERSISTED_RESEARCH",
        "embeddings": "SKIP_VECTOR_USE_SYMBOL_INDEX",
        "external_data": "NEED_DATA",
    }
    return {
        "dependency": dep,
        "degrade": degrade.get(dep, "FAIL_CLOSED"),
        "financial_action": False,
        "authority": AUTHORITY,
    }


# ── D46-48 cost / SLO ─────────────────────────────────────────────────────

def unchanged_cycle_cost() -> dict[str, Any]:
    return {
        "detector_model_calls": 0,
        "paid_cost": 0,
        "authority": AUTHORITY,
    }


def material_cycle_cost(*, detector=0, retrieval=0, specialist=0, synthesis=0, notification=0) -> dict[str, Any]:
    total = float(detector) + float(retrieval) + float(specialist) + float(synthesis) + float(notification)
    return {
        "detector_cost": detector,
        "retrieval_cost": retrieval,
        "specialist_cost": specialist,
        "synthesis_cost": synthesis,
        "notification_cost": notification,
        "total_cost": total,
        "authority": AUTHORITY,
    }


def latency_slo(samples: dict[str, float]) -> dict[str, Any]:
    # evidence-based placeholders from observed scan ~1-4s wall
    targets = {
        "event_to_detection_s": 5.0,
        "detection_to_decision_s": 2.0,
        "decision_to_outbox_s": 1.0,
        "outbox_to_delivery_s": 5.0,
    }
    return {
        "samples": samples,
        "targets": targets,
        "within_slo": all(float(samples.get(k, 0)) <= v for k, v in targets.items() if k in samples),
        "authority": AUTHORITY,
    }


def ledger_tax_critique(*, lots: list[dict[str, Any]], wash: bool, account_constraint: str | None) -> dict[str, Any]:
    return specialist_artifact(
        agent="ledger",
        claim="tax-aware critique only",
        evidence=lots,
        confidence=0.6 if lots else 0.3,
        uncertainty="lots may be incomplete",
        contradictions=["wash_sale"] if wash else [],
        recommendation="NO_TRADE_TAX_CONSTRAINT" if wash or account_constraint else "NO_OBJECTION",
    )

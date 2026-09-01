"""Standing and new CIO decisions share one operator contract.

Missing fields are explicit. Confidence is never fabricated.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

ACTIONS = (
    "HOLD", "WAIT", "WATCH", "REVIEW", "TRIM", "REENTER", "AVOID", "NO_ACTION",
    "HOLD_CASH", "INSUFFICIENT_DATA",
)
URGENCY = ("NOW", "TODAY", "NEXT_SESSION", "WATCH_ONLY", "NONE")

REQUIRED_FIELDS = (
    "decision_id",
    "entity",
    "decision",
    "urgency",
    "what_changed",
    "why_it_matters",
    "operator_action",
    "confidence",
    "supporting_evidence",
    "counter_evidence",
    "blocking_conditions",
    "data_quality",
    "created_at",
    "last_confirmed_at",
    "next_review_at",
)

COMPLETE = "OPERATOR_PRODUCT_COMPLETE"
PARTIAL = "OPERATOR_PRODUCT_PARTIAL"
INVALID = "OPERATOR_PRODUCT_INVALID"

NOT_PROVIDED = "NOT_PROVIDED"
PROVIDED = "PROVIDED"

# Wave 3b — standing cadence is a constant, not a dated catalyst judgment.
# When the producer supplies no next_review, do not leave this sentence in a
# register that implies a per-name review date (A6 / Part 2 §5.1).
STANDING_CADENCE_TEMPLATE = (
    "next material generation or next session — standing cadence, not a dated catalyst"
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _map_action(raw: str) -> str:
    a = str(raw or "").upper().replace(" ", "_")
    aliases = {
        "RE_ENTER": "REENTER", "HOLD_POSTURE": "HOLD", "WAIT": "WAIT",
        "DO_NOW": "REVIEW", "WATCH_CLOSELY": "WATCH", "HOLD_CASH": "HOLD_CASH",
    }
    a = aliases.get(a, a)
    return a if a in ACTIONS else "REVIEW"


def _urgency_for(action: str, priority: str | None) -> str:
    if action in {"HOLD", "HOLD_CASH", "NO_ACTION"}:
        return "NONE"
    if action in {"WATCH", "WAIT"}:
        return "WATCH_ONLY"
    if str(priority or "").upper() == "HIGH" or action in {"TRIM", "REENTER", "AVOID"}:
        return "NOW" if action in {"TRIM", "AVOID"} else "NEXT_SESSION"
    return "NEXT_SESSION"


def _explicit(value: Any, *, empty: str) -> tuple[Any, str]:
    if value is None:
        return empty, NOT_PROVIDED
    if isinstance(value, str) and not value.strip():
        return empty, NOT_PROVIDED
    if isinstance(value, (list, dict)) and not value:
        return empty, NOT_PROVIDED
    return value, PROVIDED


def normalize_decision(row: dict[str, Any], *, generation_id: str | None = None,
                       as_of: str | None = None) -> dict[str, Any]:
    action = _map_action(row.get("recommended_action") or row.get("action") or row.get("cio_decision") or row.get("title"))
    entity = row.get("symbol") or row.get("entity") or "PORTFOLIO"
    why = (row.get("description") or row.get("rationale") or row.get("why_it_matters") or "").strip()
    what = (row.get("title") or row.get("what_changed") or row.get("action") or "").strip()
    if action in {"HOLD", "HOLD_CASH"} and not why:
        action = "INSUFFICIENT_DATA"
        why = (
            "HOLD was indicated but the producer did not supply why it remains correct. "
            "Treated as INSUFFICIENT_DATA — not a silent empty HOLD."
        )
        what = what or "Standing posture lacks supporting narrative"
    elif action in {"HOLD", "HOLD_CASH"}:
        if "remain" not in why.lower() and "intact" not in why.lower() and "hold" not in why.lower():
            why = f"HOLD remains correct: {why}"

    urgency = _urgency_for(action, row.get("priority"))
    created = row.get("created_at") or as_of or _now()
    confirmed = row.get("last_confirmed_at") or as_of or created

    conf_raw = row.get("confidence")
    if conf_raw is None:
        confidence, conf_status = None, NOT_PROVIDED
        confidence_text = "not provided — no numeric score this generation (not fabricated)"
    else:
        try:
            confidence, conf_status = float(conf_raw), PROVIDED
            confidence_text = str(confidence)
        except (TypeError, ValueError):
            confidence, conf_status = None, NOT_PROVIDED
            confidence_text = "not provided — unparseable score (not fabricated)"

    counter, counter_status = _explicit(
        row.get("counter_evidence") or row.get("counter") or row.get("counterpoint"),
        empty="none cited — what would invalidate this is not in the producer payload this generation",
    )
    support, support_status = _explicit(
        row.get("supporting_evidence") or row.get("evidence_refs") or why,
        empty="producer did not attach supporting evidence refs",
    )
    blockers, block_status = _explicit(
        row.get("blockers") or row.get("blocking_conditions") or [],
        empty=[],
    )
    if block_status == NOT_PROVIDED:
        blockers = []
        block_status = PROVIDED  # explicit empty list = none blocking
    nrev, nrev_status = _explicit(
        row.get("next_review") or row.get("next_review_at"),
        empty=STANDING_CADENCE_TEMPLATE,
    )
    # 2026-08-31 (A2): this defaulted to "OK". An absent field must never render
    # as an affirmative all-clear -- the brief printed "Data quality: OK" under
    # every decision in a document whose own holdings verdict was ATTENTION with
    # REPRICE_AHEAD_OF_POSITIONS and CASH_TOTAL_DISAGREEMENT. None here lets the
    # renderer say "not computed", which is true, instead of "OK", which was not.
    dq = row.get("data_quality")

    payload = f"{entity}|{action}|{generation_id or ''}|{what}"
    did = row.get("decision_id") or ("dec_" + hashlib.sha256(payload.encode()).hexdigest()[:16])

    if action == "INSUFFICIENT_DATA":
        dq = "INSUFFICIENT_DATA"

    # W3 3b — demote standing cadence off the dated-catalyst judgment fields.
    # Value remains on standing_cadence_template (class T). next_review*_at stay
    # present for REQUIRED_FIELDS / completeness, but only as the demoted
    # pointer when no producer date was supplied.
    if nrev_status == NOT_PROVIDED:
        dated_catalyst = False
        next_review_role = "standing_cadence_template"
        standing_cadence = STANDING_CADENCE_TEMPLATE
        # Keep the sentence available under the honest template name; clear the
        # judgment-shaped aliases so cards that prefer next_review do not treat
        # a constant as a per-name dated catalyst. Completeness accepts the
        # demotion via standing_cadence_template + field_status (below).
        nrev_display = None
    else:
        dated_catalyst = True
        next_review_role = "dated_catalyst"
        standing_cadence = None
        nrev_display = nrev

    return {
        "decision_id": did,
        "entity": entity,
        "symbol": entity if entity != "PORTFOLIO" else row.get("symbol"),
        "decision": action,
        "cio_decision": action,
        "urgency": urgency,
        "what_changed": what or "CIO standing observation",
        "why_it_matters": why or "Producer did not supply why this matters.",
        "operator_action": urgency,
        "what_should_i_do": urgency,
        "confidence": confidence,
        "confidence_status": conf_status,
        "confidence_text": confidence_text,
        "supporting_evidence": support,
        "counter_evidence": counter,
        "blocking_conditions": blockers if isinstance(blockers, list) else [blockers],
        "data_quality": dq,
        "created_at": created,
        "last_confirmed_at": confirmed,
        "next_review_at": nrev_display,
        "next_review": nrev_display,
        "standing_cadence_template": standing_cadence,
        "next_review_role": next_review_role,
        "next_review_is_dated_catalyst": dated_catalyst,
        "next_review_class": "T" if not dated_catalyst else "A",
        "field_status": {
            "confidence": conf_status,
            "supporting_evidence": support_status,
            "counter_evidence": counter_status,
            "blocking_conditions": block_status,
            "next_review_at": nrev_status,
        },
        "source": "cio.product.current",
        "generation_id": generation_id,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def completeness(product: dict[str, Any]) -> dict[str, Any]:
    if not product or product.get("available") is False:
        return {
            "grade": INVALID,
            "missing": ["available_product"],
            "authority": AUTHORITY,
            "financial_action": False,
        }
    missing: list[str] = []
    partial: list[str] = []
    decisions = list(product.get("decisions") or product.get("entries") or [])
    if not decisions:
        missing.append("decisions")
    for i, d in enumerate(decisions):
        if not isinstance(d, dict):
            missing.append(f"decisions[{i}]")
            continue
        for f in REQUIRED_FIELDS:
            if f not in d:
                missing.append(f"decisions[{i}].{f}")
                continue
            v = d.get(f)
            if f == "confidence" and v is None:
                if d.get("confidence_status") == NOT_PROVIDED and d.get("confidence_text"):
                    partial.append(f"decisions[{i}].confidence")
                else:
                    missing.append(f"decisions[{i}].confidence")
            elif f == "next_review_at" and (v is None or v == ""):
                # W3 3b — demoted standing cadence is partial, not missing.
                fs = (d.get("field_status") or {}).get("next_review_at")
                if (
                    fs == NOT_PROVIDED
                    and d.get("standing_cadence_template")
                    and d.get("next_review_role") == "standing_cadence_template"
                ):
                    partial.append(f"decisions[{i}].next_review_at")
                else:
                    missing.append(f"decisions[{i}].{f}")
            elif f != "confidence" and (v is None or v == ""):
                missing.append(f"decisions[{i}].{f}")
        fs = d.get("field_status") or {}
        if any(s == NOT_PROVIDED for s in fs.values()):
            partial.append(d.get("decision_id") or f"decisions[{i}]")
    if missing:
        grade = INVALID
    elif partial:
        grade = PARTIAL
    else:
        grade = COMPLETE
    return {
        "grade": grade,
        "missing": missing[:40],
        "partial": partial[:40],
        "decision_n": len(decisions),
        "authority": AUTHORITY,
        "financial_action": False,
    }

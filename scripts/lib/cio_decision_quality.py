"""cio_decision_quality.py — phase-aware CIO Decision Quality acceptance.

CDQ acceptance gates are evaluated per PR phase. Each phase profile declares
which gates are REQUIRED, CONTRACT_ONLY, or NOT_IN_SCOPE:

  * REQUIRED      — must be PASS. FAIL or NOT_IN_SCOPE here fails the profile.
  * CONTRACT_ONLY — declared but not yet enforceable in this phase; FAIL here
                    fails the profile, NOT_IN_SCOPE/PASS are tolerated.
  * NOT_IN_SCOPE  — explicitly out of scope for this phase; never counted as
                    PASS and never counted toward profile completion.

A profile passes only when every REQUIRED gate is PASS and no CONTRACT_ONLY
gate is FAIL. NOT_IN_SCOPE is a statement of scope, not evidence of success.

Authority: READ_ONLY_ADVISORY. Pure evaluators only — no network, no broker
orders, no Telegram sends.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
CDQ_VERSION = "cio_decision_quality_1.0.0"

VALID_STATUS = ("PASS", "FAIL", "NOT_IN_SCOPE")

# ─────────────────────────────────────────────────────────────────────────────
# Gate registry (PR1 decision-truth + cross-cutting CDQ-25..29)
# ─────────────────────────────────────────────────────────────────────────────

GATES: dict[str, str] = {
    # PR1 — Decision Truth & Identity
    "PR1_STANDING_CURRENT_PARITY": (
        "standing view and current action are distinct and consistent across "
        "web + Telegram"
    ),
    "PR1_ACTIONABILITY": (
        "stale / risk text can never render ACT NOW; ACT_NOW requires explicit "
        "act_now=True or ACT_NOW label"
    ),
    "PR1_SIZING_ZERO": (
        "no verified sizing objective => recommended delta $0; 10% tranche is "
        "scenario-only"
    ),
    "PR1_DIGEST_409": (
        "DIGEST_CAPABLE decisions require the exact input+evidence digest pair; "
        "missing or wrong digest => 409"
    ),
    "PR1_REENTRY_CANONICAL": (
        "canonical re-entry lifecycle; READY_TO_REVIEW is never RE_ENTER"
    ),
    # Cross-cutting (user-added)
    "CDQ-25": "all production CIO writers/readers execute from approved CURRENT release",
    "CDQ-26": "no live CIO process or scheduled job resolves to deprecated project tree",
    "CDQ-27": "no fallback/scenario-only trim contributes to prospective capital sources",
    "CDQ-28": "operator feedback sample count is disjoint from measured outcome sample count",
    "CDQ-29": "exactly one runtime path owns outcome maturation for each case generation",
    # Tightened capital invariant (PR2)
    "CAPITAL_ACT_NOW_ZERO": (
        "ACT_NOW=0 globally implies deploy_now=0 AND no conditional/prospective "
        "source labeled AVAILABLE_NOW AND no candidate use presented as an "
        "authorized recommendation"
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# Phase profiles
# ─────────────────────────────────────────────────────────────────────────────

PROFILES: dict[str, dict[str, frozenset[str]]] = {
    "PR1_DECISION_TRUTH": {
        "required": frozenset({
            "PR1_STANDING_CURRENT_PARITY",
            "PR1_ACTIONABILITY",
            "PR1_SIZING_ZERO",
            "PR1_DIGEST_409",
            "PR1_REENTRY_CANONICAL",
            "CDQ-27",
        }),
        "contract_only": frozenset({
            "CDQ-25",
            "CDQ-26",
            "CAPITAL_ACT_NOW_ZERO",
        }),
        "not_in_scope": frozenset({
            "CDQ-28",
            "CDQ-29",
        }),
    },
}

PROFILE_IDS = tuple(PROFILES.keys())


def evaluate_profile(
    profile_id: str,
    results: dict[str, str],
) -> dict[str, Any]:
    """Evaluate a phase profile from a {gate_id: status} map.

    Returns a verdict record with per-gate status, required/contract_only
    aggregation, and an overall `pass` boolean. NOT_IN_SCOPE never counts as
    PASS and never satisfies a REQUIRED gate.
    """
    profile = PROFILES.get(profile_id)
    if profile is None:
        raise ValueError(f"unknown CDQ profile: {profile_id}")

    required = profile["required"]
    contract_only = profile["contract_only"]
    not_in_scope = profile["not_in_scope"]

    normalized: dict[str, str] = {}
    for gid, status in results.items():
        st = str(status or "FAIL").upper()
        normalized[gid] = st if st in VALID_STATUS else "FAIL"

    required_fail: list[str] = []
    for gid in sorted(required):
        st = normalized.get(gid, "NOT_IN_SCOPE")
        if st != "PASS":
            required_fail.append(f"{gid}:{st}")

    contract_fail: list[str] = []
    for gid in sorted(contract_only):
        st = normalized.get(gid, "NOT_IN_SCOPE")
        if st == "FAIL":
            contract_fail.append(f"{gid}:FAIL")

    # NOT_IN_SCOPE gates that are neither required nor contract are declared.
    declared = set(required) | set(contract_only) | set(not_in_scope)
    undeclared = sorted(set(normalized) - declared)

    ok = (not required_fail) and (not contract_fail)

    return {
        "profile": profile_id,
        "version": CDQ_VERSION,
        "authority": AUTHORITY,
        "pass": ok,
        "required": sorted(required),
        "contract_only": sorted(contract_only),
        "not_in_scope": sorted(not_in_scope),
        "required_fail": required_fail,
        "contract_fail": contract_fail,
        "undeclared_gates": undeclared,
        "gates": {gid: normalized.get(gid, "NOT_IN_SCOPE") for gid in sorted(declared)},
        "not_in_scope_counts_as_pass": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pure PR1 evaluators (decision truth & identity)
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_pr1_actionability(decision: dict[str, Any]) -> tuple[str, list[str]]:
    """PR1_ACTIONABILITY — fail-closed: stale/conflict override ACT_NOW.

    Returns (status, violations). PASS only when:
      * a blocking freshness/conflict state never renders "high" (even if
        act_now=True or ACT_NOW label is present — the contradiction case);
      * an explicit ACT_NOW (with no blocking state) renders "high";
      * otherwise risk text / nothing never renders "high".
    """
    from scripts.lib.cio_command_center import _actionability_urgency, _freshness_flag
    label = str(decision.get("action_label") or "").upper()
    freshness = _freshness_flag(decision)
    blocking = {"STALE_REFRESH_REQUIRED", "REVALIDATE", "DATA_CONFLICT"}
    is_blocking = label in blocking or freshness in blocking or freshness in {"STALE", "EXPIRED"}
    explicit_act = decision.get("act_now") is True or label == "ACT_NOW"
    urgency = _actionability_urgency(decision)
    violations: list[str] = []
    if is_blocking:
        if urgency == "high":
            violations.append("blocking freshness/conflict still rendered high urgency")
    elif explicit_act:
        if urgency != "high":
            violations.append("explicit ACT_NOW did not map to high urgency")
    elif urgency == "high":
        violations.append("high urgency without explicit ACT_NOW")
    status = "PASS" if not violations else "FAIL"
    return status, violations


def evaluate_pr1_sizing_zero(
    positions: list[dict[str, Any]],
    *,
    portfolio_value: float,
    policy_cap_pct: float,
    fire_pct: float,
) -> tuple[str, list[str]]:
    """PR1_SIZING_ZERO — a below-policy/fire advisory TRIM yields $0 delta.

    Returns (status, violations). Each violation names a symbol that still
    emitted a non-zero recommended delta without a verified objective.
    """
    from scripts.lib.cio_institutional_sizing import recommend_trim
    violations: list[str] = []
    for p in positions:
        mv = float(p.get("market_value_usd") or p.get("current_value_usd") or 0.0)
        weight = (mv / portfolio_value * 100.0) if portfolio_value else 0.0
        if weight >= policy_cap_pct or weight >= fire_pct:
            # Above policy/fire is a real objective; skip the no-objective check.
            continue
        rec = recommend_trim(
            market_value_usd=mv,
            weight_pct=weight,
            portfolio_value_usd=portfolio_value,
            policy_cap_pct=policy_cap_pct,
            fire_pct=fire_pct,
            advisory_trim=True,
        )
        delta = float(rec.get("recommended_delta_usd") or 0.0)
        if delta != 0.0:
            violations.append(
                f"{p.get('symbol')}: below policy/fire advisory TRIM emitted "
                f"{delta} delta (method={rec.get('method')})"
            )
    status = "PASS" if not violations else "FAIL"
    return status, violations


def evaluate_pr1_digest_409(catalog_digest: str, supplied_digest: Optional[str]) -> tuple[str, list[str]]:
    """PR1_DIGEST_409 — DIGEST_CAPABLE requires exact pair; missing => reject.

    Returns (status, violations). A missing supplied digest for a non-empty
    catalog digest must be rejected (fail-closed), never accepted.
    """
    from scripts.api_v3_cio import _digests_match
    violations: list[str] = []
    if catalog_digest and not supplied_digest:
        if _digests_match(supplied_digest or "", catalog_digest):
            violations.append("missing supplied digest accepted for DIGEST_CAPABLE")
    if supplied_digest and supplied_digest != catalog_digest and catalog_digest:
        if _digests_match(supplied_digest, catalog_digest):
            violations.append("wrong supplied digest accepted for DIGEST_CAPABLE")
    status = "PASS" if not violations else "FAIL"
    return status, violations


def evaluate_pr1_reentry_canonical() -> tuple[str, list[str]]:
    """PR1_REENTRY_CANONICAL — desk readiness never grants RE_ENTER authority.

    Exercises the real transforms (stance_from_queue_item + resolve_display_stance)
    against both state-only records and the label/why-now bypasses. Only an
    explicit governed ``verdict="RE_ENTER"`` may produce STANCE_RE_ENTER.

    Returns (status, violations).
    """
    from scripts.lib.cio_decision_semantics import (
        REENTRY_LIFECYCLE,
        resolve_display_stance,
        stance_from_queue_item,
    )
    violations: list[str] = []
    if "RE_ENTER" not in REENTRY_LIFECYCLE:
        violations.append("REENTRY_LIFECYCLE missing RE_ENTER terminal state")

    # State-only records: never RE_ENTER.
    for state in ("READY TO REVIEW", "NEAR ENTRY", "OVERSOLD REVIEW", "DESK READY"):
        got = stance_from_queue_item({"symbol": "TST", "state": state})
        if got == "RE_ENTER":
            violations.append(f"{state!r} mapped to RE_ENTER")

    # Label bypass: readiness + "Re-enter" directive_label/note must stay REVIEW.
    for label in ("Re-enter ADBE", "RE-ENTER ADBE", "Reenter ADBE"):
        got = stance_from_queue_item({
            "symbol": "TST", "state": "READY TO REVIEW", "directive_label": label,
        })
        if got == "RE_ENTER":
            violations.append(f"READY TO REVIEW + label {label!r} mapped to RE_ENTER")
        got2 = stance_from_queue_item({
            "symbol": "TST", "state": "NEAR ENTRY", "note": label,
        })
        if got2 == "RE_ENTER":
            violations.append(f"NEAR ENTRY + note {label!r} mapped to RE_ENTER")

    # why_now bypass: free-text "re-enter" is non-authoritative for a REVIEW
    # standing stance.
    for why in ("ready to re-enter ADBE", "consider re-enter on trigger"):
        got = resolve_display_stance("REVIEW", why)
        if got == "RE_ENTER":
            violations.append(f"resolve_display_stance(REVIEW, {why!r}) -> RE_ENTER")

    # Only an explicit governed verdict=RE_ENTER grants RE_ENTER.
    got = stance_from_queue_item({
        "symbol": "TST", "state": "READY TO REVIEW", "verdict": "RE_ENTER",
    })
    if got != "RE_ENTER":
        violations.append("explicit verdict=RE_ENTER did not produce RE_ENTER")

    status = "PASS" if not violations else "FAIL"
    return status, violations


def evaluate_pr1_standing_current_parity() -> tuple[str, list[str]]:
    """PR1_STANDING_CURRENT_PARITY — canonical input through all four surfaces.

    Builds a capital plan, propagates it through CIO NOW, the institutional
    report, and the real Telegram material-scan path, then compares them with
    the existing ``compare_plan_home_report_telegram`` material parity contract
    (decision ID, both digests, action/standing stance, recommended dollars).

    Also exercises the real Telegram ``classify_actionability`` /
    ``format_cio_message`` path for the stale/conflict contradiction case.

    Returns (status, violations).
    """
    from datetime import datetime, timezone

    from scripts.lib import cio_capital_plan as cp
    from scripts.lib import cio_command_center as cc
    from scripts.lib import cio_report_v2 as r
    from scripts.lib.cio_alex_telegram import (
        classify_actionability,
        format_cio_message,
    )
    from scripts.lib.cio_decision_parity import compare_plan_home_report_telegram
    from scripts.lib.cio_material_scan import _canonical_decisions

    now = datetime(2026, 8, 14, 21, 0, 0, tzinfo=timezone.utc)
    plan = cp.build_capital_plan(
        portfolio_value=1_282_425.99,
        cash_total=578_107.50,
        positions=[
            {"symbol": "SCHD", "market_value": 225_789.79,
             "account": "schwab_rollover_ira", "weight_pct": 17.58},
            {"symbol": "V", "market_value": 70_000.0,
             "account": "schwab_rollover_ira", "weight_pct": 5.0},
        ],
        queue={"items": [
            {"symbol": "SCHD", "verdict": "TRIM", "directive_label": "Advisory TRIM — SCHD"},
            {"symbol": "V", "verdict": None, "directive_label": "Advisory TRIM — V"},
        ]},
        concentration_fire_pct=16.5,
        max_single_name_pct=12.0,
        now=now,
    )
    positions = plan["position_decisions"]
    cio_now = cc.build_cio_now(
        position_decisions=positions,
        portfolio_value=plan["portfolio_value_usd"],
    )
    report = r.build_report_v2(
        part_b_ctx={
            "portfolio": {
                "total_value": plan["portfolio_value_usd"],
                "cash_value": plan["cash_total_usd"],
            },
        },
        part_a_inputs={"capital_plan": plan},
        source_sha="cdq_parity",
        now=now,
    )

    violations: list[str] = []

    # 1) Four-surface material parity via the real Telegram path.
    telegram_decisions = _canonical_decisions(plan)
    telegram_payload = {"decisions": telegram_decisions}
    cmp = compare_plan_home_report_telegram(
        plan=plan,
        cio_home=cio_now,
        report=report,
        telegram_payload=telegram_payload,
    )
    if not cmp.get("ok"):
        violations.append(
            "four_surface_parity failed: "
            f"missing={len(cmp.get('missing_from_surface') or [])} "
            f"extra={len(cmp.get('extra_on_surface') or [])} "
            f"field={len(cmp.get('field_mismatch') or [])} "
            f"digest={len(cmp.get('digest_mismatch') or [])}"
        )

    # 2) Real Telegram contradiction: act_now=True + DATA_CONFLICT → no MY CALL.
    conflict = {
        "decision_id": "dec_parity_conflict",
        "symbol": "SCHD",
        "stance_code": "RE_ENTER",
        "action": "RE_ENTER",
        "act_now": True,
        "action_label": "DATA_CONFLICT",
        "recommended_delta_usd": 0.0,
        "why_now": "conflicting input: act_now with DATA_CONFLICT",
        "decision_input_digest": "in",
        "decision_evidence_digest": "ev",
    }
    cls = classify_actionability(conflict)
    if cls.get("act_now"):
        violations.append("DATA_CONFLICT + act_now=True still act_now")
    if "MY CALL" in format_cio_message(conflict):
        violations.append("DATA_CONFLICT + act_now=True rendered MY CALL")

    # 3) Real Telegram standing RE_ENTER alone never implies ACT_NOW.
    reenter_only = {
        "decision_id": "dec_parity_reenter",
        "symbol": "X",
        "stance_code": "RE_ENTER",
        "action": "RE_ENTER",
        "recommended_delta_usd": 5000.0,
        "why_now": "standing re-enter, no explicit act_now",
    }
    if classify_actionability(reenter_only).get("act_now"):
        violations.append("RE_ENTER alone implied ACT_NOW")
    if "MY CALL" in format_cio_message(reenter_only):
        violations.append("RE_ENTER alone rendered MY CALL")

    # 4) Real Telegram fresh RE_ENTER + act_now=True still produces MY CALL.
    fresh = {
        "decision_id": "dec_parity_fresh",
        "symbol": "X",
        "stance_code": "RE_ENTER",
        "action": "RE_ENTER",
        "act_now": True,
        "recommended_delta_usd": 5000.0,
        "why_now": "fresh re-enter with explicit act_now",
    }
    if not classify_actionability(fresh).get("act_now"):
        violations.append("fresh RE_ENTER + act_now=True not act_now")
    if "MY CALL" not in format_cio_message(fresh):
        violations.append("fresh RE_ENTER + act_now=True missing MY CALL")

    status = "PASS" if not violations else "FAIL"
    return status, violations


def evaluate_cdq27_scenario_only_zero(
    positions: list[dict[str, Any]],
    queue: dict[str, Any],
) -> tuple[str, list[str]]:
    """CDQ-27 — no fallback/scenario-only trim contributes to capital sources.

    Returns (status, violations). Uses the capital-sources builder with and
    without portfolio context to prove the trim yields $0 either way.
    """
    from scripts.lib.cio_capital_plan import build_capital_sources
    violations: list[str] = []
    for context in ({"portfolio_value": 0.0}, {}):
        src = build_capital_sources(positions, queue=queue, **context)
        if float(src.get("trims_usd") or 0.0) != 0.0:
            violations.append(
                f"trims_usd={src.get('trims_usd')} with context={context}"
            )
        if float(src.get("total_prospective_raise_usd") or 0.0) != 0.0:
            violations.append(
                f"prospective raise={src.get('total_prospective_raise_usd')} "
                f"with context={context}"
            )
    status = "PASS" if not violations else "FAIL"
    return status, violations

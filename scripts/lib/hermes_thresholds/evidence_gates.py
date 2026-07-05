"""Sample-size and confidence gates for learned threshold proposals."""
from __future__ import annotations

from typing import Any

ALLOWED_ACTIONS = (
    "observe_only",
    "propose_only",
    "operator_approval_required",
    "auto_apply_inside_rails",
)

EXECUTION_BLOCKED_ACTIONS = frozenset({
    "broker_write",
    "live_order",
    "oco_enable",
    "stop_placement",
    "position_liquidation",
    "strategy_promotion_live",
    "2fa_bypass",
    "execution_gate_override",
})


def _cfg_gates(cfg: dict[str, Any]) -> dict[str, Any]:
    return (cfg.get("evidence_gates") or {})


def minimum_required_sample(cfg: dict[str, Any], threshold_id: str | None = None) -> int:
    gates = _cfg_gates(cfg)
    per = (gates.get("per_threshold") or {}).get(threshold_id or "")
    if per is not None:
        return int(per)
    return int(gates.get("minimum_required_sample", 14))


def minimum_regime_count(cfg: dict[str, Any]) -> int:
    return int(_cfg_gates(cfg).get("minimum_regime_count", 2))


def minimum_confidence_for_learned(cfg: dict[str, Any]) -> str:
    return str(_cfg_gates(cfg).get("minimum_confidence_for_learned", "medium"))


def _conf_rank(tier: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(str(tier).lower(), 0)


def evaluate_evidence_gates(
    *,
    sample_size: int,
    lookback_days: int,
    regime_count: int,
    confidence: str,
    cfg: dict[str, Any],
    threshold_id: str | None = None,
    review_mode: bool = True,
    direction: str | None = None,
    inside_rails: bool = True,
) -> dict[str, Any]:
    """Return gate verdict and allowed_action for a proposal."""
    gates = _cfg_gates(cfg)
    min_sample = minimum_required_sample(cfg, threshold_id)
    min_regime = minimum_regime_count(cfg)
    min_conf = minimum_confidence_for_learned(cfg)

    blocked_reasons: list[str] = []
    if sample_size < min_sample:
        blocked_reasons.append(f"sample_size {sample_size} < minimum {min_sample}")
    if regime_count < min_regime:
        blocked_reasons.append(f"regime_count {regime_count} < minimum {min_regime}")
    if _conf_rank(confidence) < _conf_rank(min_conf):
        blocked_reasons.append(f"confidence {confidence} < minimum {min_conf}")

    gates_pass = len(blocked_reasons) == 0
    can_learn = gates_pass

    if not gates_pass:
        allowed_action = "observe_only" if sample_size < min_sample // 2 else "propose_only"
    elif review_mode:
        allowed_action = "operator_approval_required"
    elif inside_rails and direction in ("tighten", "loosen"):
        auto_conf = str(gates.get("auto_apply_min_confidence", "high"))
        if _conf_rank(confidence) >= _conf_rank(auto_conf):
            allowed_action = "auto_apply_inside_rails"
        else:
            allowed_action = "operator_approval_required"
    else:
        allowed_action = "operator_approval_required"

    return {
        "sample_size": sample_size,
        "lookback_days": lookback_days,
        "regime_count": regime_count,
        "confidence": confidence,
        "minimum_required_sample": min_sample,
        "minimum_regime_count": min_regime,
        "minimum_confidence_for_learned": min_conf,
        "gates_pass": gates_pass,
        "can_be_called_learned": can_learn,
        "allowed_action": allowed_action,
        "blocked_reason": "; ".join(blocked_reasons) if blocked_reasons else None,
        "advisory_only": True,
    }


def enrich_proposal_evidence_gates(
    proposal: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Attach evidence gate fields to a threshold proposal."""
    evidence = dict(proposal.get("evidence") or {})
    regime = evidence.get("regime_breakdown") or {}
    sample_size = int(evidence.get("sample_days") or evidence.get("sample_size") or regime.get("total_days") or 0)
    lookback = int(evidence.get("lookback_days") or (cfg.get("learning") or {}).get("analysis_window_days", 30))
    regime_count = max(
        1,
        int(bool(regime.get("high_vol_days"))) + int(bool(regime.get("regime_stable", True))),
    )
    if regime.get("high_vol_days") and regime.get("total_days"):
        regime_count = max(regime_count, 2 if int(regime["high_vol_days"]) > 0 else 1)

    confidence = str(evidence.get("confidence") or "low")
    learning = cfg.get("learning") or {}
    gates = evaluate_evidence_gates(
        sample_size=sample_size,
        lookback_days=lookback,
        regime_count=regime_count,
        confidence=confidence,
        cfg=cfg,
        threshold_id=proposal.get("threshold_id"),
        review_mode=bool(learning.get("review_mode", True)),
        direction=proposal.get("direction"),
        inside_rails=True,
    )
    evidence["evidence_gates"] = gates
    evidence.update({k: gates[k] for k in (
        "sample_size", "lookback_days", "regime_count", "confidence",
        "minimum_required_sample", "allowed_action",
    )})
    if gates.get("blocked_reason"):
        evidence["blocked_reason"] = gates["blocked_reason"]

    out = dict(proposal)
    out["evidence"] = evidence
    out["evidence_gates"] = gates
    out["can_be_called_learned"] = gates["can_be_called_learned"]
    out["allowed_action"] = gates["allowed_action"]
    if not gates["can_be_called_learned"]:
        out["learning_status"] = "insufficient_evidence"
    return out


def check_hermes_action_allowed(action_type: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Hard governance: Hermes cannot touch execution-facing surfaces."""
    action = str(action_type or "").lower().strip()
    if action in EXECUTION_BLOCKED_ACTIONS:
        return {
            "allowed": False,
            "action_type": action,
            "reason": "execution_facing_blocked",
            "advisory_only": True,
        }

    scope_actions = {"tighten_scope", "widen_scope", "scope_budget_change", "retire_source", "strategy_config_change"}
    if action in scope_actions:
        requires_approval = action in {
            "scope_budget_change", "retire_source", "strategy_config_change", "widen_scope",
        }
        return {
            "allowed": True,
            "action_type": action,
            "requires_operator_approval": requires_approval or action != "tighten_scope",
            "advisory_only": True,
        }

    if action in ("raise_threshold", "lower_threshold", "threshold_proposal"):
        ctx = context or {}
        gates = ctx.get("evidence_gates") or {}
        allowed_action = gates.get("allowed_action", "operator_approval_required")
        auto_ok = allowed_action == "auto_apply_inside_rails"
        return {
            "allowed": True,
            "action_type": action,
            "requires_operator_approval": not auto_ok,
            "allowed_action": allowed_action,
            "advisory_only": True,
        }

    return {"allowed": True, "action_type": action, "advisory_only": True}
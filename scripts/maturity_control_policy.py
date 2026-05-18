#!/usr/bin/env python3
"""maturity_control_policy.py — Pure maturity scoring and readiness rules.

No DB writes. No side effects. No strategy activation. No trading.
"""
from datetime import datetime, timezone

A5_END_DATE = "2026-05-22"


def classify_area_status(score: float, blockers: list = None) -> dict:
    if blockers:
        return {"status": "blocked", "score": score, "blockers": blockers}
    if score >= 8:
        return {"status": "healthy", "score": score}
    if score >= 6:
        return {"status": "warning", "score": score}
    return {"status": "attention_required", "score": score}


def classify_live_readiness(inputs: dict) -> dict:
    blockers = []
    if inputs.get("alpaca_mode") != "paper":
        blockers.append("ALPACA_MODE must be paper during validation")
    if not inputs.get("a5_complete"):
        blockers.append("A-5 observation not complete")
    if inputs.get("backup_readiness", 0) < 7:
        blockers.append(f"Backup readiness {inputs.get('backup_readiness', 0)}/10 (need 7+)")
    if inputs.get("closed_trades", 0) < 100:
        blockers.append(f"Only {inputs.get('closed_trades', 0)} closed trades (need 100+)")
    if inputs.get("win_rate", 0) < 0.55:
        blockers.append(f"Win rate {inputs.get('win_rate', 0):.0%} (need 55%+)")
    blockers.append("Live trading requires explicit operator approval")
    return {"status": "blocked", "blockers": blockers, "decision_allowed": False}


def classify_strategy_decision_readiness(inputs: dict) -> dict:
    blockers = []
    if not inputs.get("a5_complete"):
        blockers.append("A-5 observation not complete")
    if inputs.get("strategies_decision_ready", 0) == 0:
        blockers.append("No strategies at decision_ready status")
    if inputs.get("closed_trades", 0) < 20:
        blockers.append(f"Only {inputs.get('closed_trades', 0)} closed trades (need 20+)")
    return {"status": "blocked" if blockers else "allowed", "blockers": blockers,
            "decision_allowed": len(blockers) == 0, "recommendation_status": "human_review_only"}


def classify_agent_learning_readiness(inputs: dict) -> dict:
    evidence = inputs.get("evidence_quality", "none")
    if evidence in ("none", "weak"):
        return {"status": "blocked", "blockers": [f"Evidence quality: {evidence}"],
                "auto_learning_allowed": False}
    return {"status": "warning" if evidence == "preliminary" else "allowed",
            "blockers": [], "auto_learning_allowed": False}  # Always manual


def classify_backup_readiness(inputs: dict) -> dict:
    score = inputs.get("backup_score", 0)
    blockers = []
    if not inputs.get("offsite_configured"):
        blockers.append("P0: No offsite backup configured")
    if not inputs.get("restore_drill_passed"):
        blockers.append("No restore drill executed")
    return classify_area_status(score, blockers if blockers else None)


def recommended_next_actions(inputs: dict) -> list:
    actions = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if now < A5_END_DATE:
        actions.append({"action": "Continue A-5 observation", "status": "waiting",
                       "reason": f"Window ends {A5_END_DATE}"})
    else:
        actions.append({"action": "Run final A-5 review", "status": "allowed"})
    if not inputs.get("offsite_configured"):
        actions.append({"action": "Configure rclone for BR-2", "status": "operator_required"})
    actions.append({"action": "Monday A-5 observation check", "status": "allowed"})
    return actions

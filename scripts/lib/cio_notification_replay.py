"""cio_notification_replay.py — deterministic CIO Telegram signal-over-spam replay.

Builds the Aug-17-style operator-history fixture (no live credentials) and runs
it through the notification gate. Reports raw evaluations vs. immediate /
digest / command-center-only / suppressed counts.

READ_ONLY_ADVISORY. Never sends Telegram.
"""
from __future__ import annotations

from typing import Any

from scripts.lib.cio_notification_signal import (
    NotificationStateStore,
    replay_decisions,
)


def _cash(digest: str) -> dict[str, Any]:
    return {
        "decision_id": f"dec_cash_{digest}",
        "symbol": "CASH",
        "action": "HOLD_CASH",
        "stance_code": "HOLD_CASH",
        "standing_recommendation": "HOLD_CASH",
        "current_action": "HOLD_CASH",
        "act_now": False,
        "actionability": "NO_ACTION",
        "delta_usd": 0.0,
        "why_now": "Cash above band; no governed deployment actionable now.",
        "cash_posture": {"cash_posture_status": "ABOVE_BAND"},
        "cash_posture_status": "ABOVE_BAND",
        "capital": {"free_investable": 322000, "deploy_now": 0, "remain_cash": 256000},
        "decision_evidence_digest": digest,
    }


def _reentry(ready: tuple[str, ...]) -> dict[str, Any]:
    return {
        "decision_id": "dec_reentry_x",
        "symbol": "REENTRY",
        "action": "WAIT",
        "stance_code": "WAIT",
        "standing_recommendation": "WAIT",
        "current_action": "WAIT",
        "act_now": False,
        "actionability": "NO_ACTION",
        "delta_usd": 0.0,
        "why_now": f"Re-entry WAIT; ready={','.join(ready)} but no governed RE_ENTER.",
        "ready": list(ready),
        "decision_evidence_digest": ",".join(ready),
    }


def _schd(digest: str, *, disposition: str | None = None) -> dict[str, Any]:
    d = {
        "decision_id": f"dec_schd_{digest}",
        "symbol": "SCHD",
        "action": "TRIM",
        "stance_code": "TRIM",
        "standing_recommendation": "TRIM",
        "current_action": "DATA_CONFLICT",
        "act_now": False,
        "actionability": "DATA_CONFLICT",
        "weight_pct": 17.6,
        "delta_usd": -44334,
        "why_now": "TRIM — SCHD concentration above single-name cap; data conflicted.",
        "decision_evidence_digest": digest,
    }
    if disposition:
        d["operator_disposition"] = {"disposition": disposition}
    return d


def build_aug17_replay() -> list[dict[str, Any]]:
    """Deterministic Aug-17-shaped fixture (18 timer cycles × 3 families).

    Includes: cash small-drift cycles, re-entry READY churn, SCHD blocked TRIM
    repeats, an operator REJECT on SCHD, a deferred review, a governed RE_ENTER
    transition, a genuine ACT_NOW transition, and a changed-since-REJECT
    reopen. 60 raw decisions total — historically 54 pages.
    """
    decisions: list[dict[str, Any]] = [
        _schd("e0", disposition="REJECT"),
    ]
    for i in range(18):
        decisions.append(_cash(f"c{i}"))
        decisions.append(_reentry(("AMD", "NVDA")))
        decisions.append(_schd(f"s{i}", disposition="REJECT"))
    decisions.append({
        "decision_id": "dec_defer_1",
        "symbol": "BOOK",
        "action": "WAIT",
        "standing_recommendation": "WAIT",
        "current_action": "WAIT",
        "act_now": False,
        "delta_usd": 0.0,
        "why_now": "deferred review due",
        "next_review": "2026-08-18",
    })
    decisions.append({
        "decision_id": "dec_reentry_governed",
        "symbol": "REENTRY",
        "action": "RE_ENTER",
        "stance_code": "RE_ENTER",
        "standing_recommendation": "RE_ENTER",
        "current_action": "RE_ENTER",
        "act_now": True,
        "actionability": "ACT_NOW",
        "delta_usd": 25000.0,
        "why_now": "AMD candidate-specific governed RE_ENTER verdict cleared.",
        "ready": ["AMD"],
    })
    decisions.append({
        "decision_id": "dec_schd_now",
        "symbol": "SCHD",
        "action": "TRIM",
        "stance_code": "TRIM",
        "standing_recommendation": "TRIM",
        "current_action": "TRIM",
        "act_now": True,
        "actionability": "ACT_NOW",
        "weight_pct": 17.6,
        "delta_usd": -44334,
        "why_now": "Concentration data conflict cleared; trim is now actionable.",
    })
    decisions.append({
        **{
            "decision_id": "dec_schd_reopen",
            "symbol": "SCHD",
            "action": "TRIM",
            "stance_code": "TRIM",
            "standing_recommendation": "TRIM",
            "current_action": "TRIM",
            "act_now": True,
            "actionability": "ACT_NOW",
            "weight_pct": 17.6,
            "delta_usd": -44334,
            "why_now": "Changed since REJECT: challenge review now materially supports trim.",
        },
        "operator_disposition": {"disposition": "REJECT"},
    })
    return decisions


def run_aug17_replay(store: NotificationStateStore | None = None) -> dict[str, Any]:
    return replay_decisions(build_aug17_replay(), store=store)

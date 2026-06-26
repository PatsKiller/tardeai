#!/usr/bin/env python3
"""Current execution-state source of truth — fail-closed aggregate.

CLI:
  python scripts/execution_state.py --json
  python scripts/execution_state.py --markdown > docs/CURRENT_EXECUTION_STATE.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

REQUIRED_LIVE_GATES = [
    "global_live_allowed", "broker_policy_enabled", "db_operator_arm_enabled",
    "strategy_enabled", "account_allowlisted", "product_allowed", "proposal_exists",
    "authoritative_trade_plan", "fresh_market_data", "risk_preflight_hard_pass",
    "desk_queue_approved", "operator_2fa_confirmed", "kill_switches_clear",
    "broker_ack_required",
]


def _iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _repo_dirty() -> tuple[int | None, int | None]:
    try:
        proc = subprocess.run(
            ["python3", "scripts/repo_hygiene_report.py", "--json"],
            cwd=ROOT, text=True, capture_output=True, timeout=30,
        )
        if proc.returncode not in (0, 2):
            return None, None
        data = json.loads(proc.stdout)
        return data.get("dirty_count"), data.get("live_broker_dirty_count", 0)
    except Exception:
        return None, None


def _live_unlock_status() -> dict[str, Any]:
    """Mirror execution_guard standing locks — env OR session OR standing DB unlock + broker_live_enabled."""
    out: dict[str, Any] = {
        "live_unlocked": False,
        "env_flag": os.getenv("BROKER_LIVE_ENABLED", "false").lower() == "true",
        "session_armed": False,
        "standing_unlock": False,
        "broker_live_enabled": False,
        "standing_approvals": 0,
        "unlock_via": None,
        "inspect_error": None,
    }
    try:
        from brokers.execution_guard import _live_future_unlocked
        out["live_unlocked"] = bool(_live_future_unlocked())
    except Exception as e:
        out["inspect_error"] = str(e)[:120]
        return out
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("SELECT value FROM system_controls WHERE key='broker_live_enabled'")
        r = cur.fetchone()
        out["broker_live_enabled"] = bool(r and str(r[0]).lower() == "true")
        cur.execute("SELECT value FROM system_controls WHERE key='schwab_pilot_standing_unlock'")
        st = cur.fetchone()
        out["standing_unlock"] = bool(st and str(st[0]).lower() == "true")
        cur.execute("SELECT value FROM system_controls WHERE key='pilot_armed_until'")
        sr = cur.fetchone()
        if sr and sr[0]:
            try:
                exp = dt.datetime.fromisoformat(str(sr[0]))
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=dt.timezone.utc)
                out["session_armed"] = exp > dt.datetime.now(dt.timezone.utc)
            except Exception:
                out["session_armed"] = False
        cur.execute("SELECT count(*) FROM broker_live_approvals WHERE revoked_at IS NULL")
        out["standing_approvals"] = int(cur.fetchone()[0] or 0)
    except Exception as e:
        out["inspect_error"] = str(e)[:120]
    if out["live_unlocked"]:
        if out["standing_unlock"]:
            out["unlock_via"] = "standing_db_unlock"
        elif out["session_armed"]:
            out["unlock_via"] = "pilot_armed_until"
        elif out["env_flag"]:
            out["unlock_via"] = "BROKER_LIVE_ENABLED"
    return out


def _path_status() -> dict[str, Any]:
    """Per-path live eligibility after global unlock (each still needs per-order 2FA)."""
    paths: dict[str, Any] = {}
    try:
        from brokers.execution_guard import _options_unlocked, _protective_unlocked
        paths["options"] = {"live_eligible": bool(_options_unlocked())}
        paths["protective_stops"] = {"live_eligible": bool(_protective_unlocked())}
    except Exception as e:
        paths["inspect_error"] = str(e)[:120]
    try:
        import options_pilot_arm as opa
        paths["options"] = {**(paths.get("options") or {}), **opa.status()}
    except Exception:
        pass
    return paths


def _current_blockers(live: dict, paths: dict) -> list[str]:
    """Hard blockers only — missing standing unlock is NOT a blocker when live_unlocked is true."""
    blockers: list[str] = []
    if live.get("inspect_error"):
        blockers.append(f"cannot inspect live unlock state — fail closed: {live['inspect_error']}")
    elif not live.get("live_unlocked"):
        blockers.append(
            "live path locked — need standing DB unlock (schwab_pilot_standing_unlock) "
            "or pilot_armed_until or BROKER_LIVE_ENABLED, plus broker_live_enabled + standing approval"
        )
    try:
        from brokers.kill_switches import list_active
        for row in list_active():
            if row.get("level") in ("global", "live_submit") or row.get("fail_closed"):
                blockers.append(f"kill_switch active: {row.get('level')} — {row.get('reason')}")
    except Exception:
        blockers.append("kill_switch inspect failed — fail closed")
    return blockers


def live_trading_labels() -> dict[str, Any]:
    """Canonical split: Alpaca autonomous gate vs Schwab operator+2FA path."""
    live = _live_unlock_status()
    paths = _path_status()
    autonomous_allowed = False
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute(
            "SELECT live_trading_allowed FROM paper_validation_policy WHERE active=true ORDER BY id DESC LIMIT 1"
        )
        r = cur.fetchone()
        autonomous_allowed = bool(r and r[0])
    except Exception:
        pass
    operator_allowed = bool(live.get("live_unlocked"))
    options_live = bool(
        (paths.get("options") or {}).get("live_eligible")
        or (paths.get("options") or {}).get("armed_for_execution")
    )
    operator_submit = operator_allowed and (
        options_live or (paths.get("protective_stops") or {}).get("live_eligible")
    )
    unlock_via = live.get("unlock_via")
    return {
        "autonomous_live_trading_allowed": autonomous_allowed,
        "operator_live_via_2fa_allowed": operator_allowed,
        "operator_approved_live_submit_possible": operator_submit,
        "per_order_2fa_required": True,
        "unlock_via": unlock_via,
        "autonomous_status_label": (
            "AUTHORIZED" if autonomous_allowed else "BLOCKED — paper validation gate not passed"
        ),
        "operator_status_label": (
            f"ENABLED via {unlock_via or 'standing unlock'} — per-order 2FA required; not autonomous"
            if operator_allowed
            else "LOCKED — standing operator unlock required before 2FA can arm submit"
        ),
    }


def build_state() -> dict[str, Any]:
    """Single JSON object — reconciles live architecture built vs autonomous prohibition."""
    live = _live_unlock_status()
    paths = _path_status()
    blockers = _current_blockers(live, paths)
    dirty, live_dirty = _repo_dirty()
    release_notes: list[str] = []
    if live_dirty and live_dirty > 0:
        release_notes.append(f"live-adjacent dirty files: {live_dirty} (release gate only)")

    labels = live_trading_labels()
    live_unlocked = bool(live.get("live_unlocked"))
    operator_possible = bool(labels.get("operator_approved_live_submit_possible"))

    return {
        "live_architecture_built": True,
        "live_trading_global_allowed": live_unlocked,
        "paper_mode": not live_unlocked,
        "autonomous_live_trading_allowed": labels.get("autonomous_live_trading_allowed"),
        "autonomous_live_submit_allowed": False,
        "operator_live_via_2fa_allowed": labels.get("operator_live_via_2fa_allowed"),
        "operator_approved_live_submit_possible": operator_possible,
        "operator_status_label": labels.get("operator_status_label"),
        "autonomous_status_label": labels.get("autonomous_status_label"),
        "per_order_2fa_required": True,
        "live_unlock": live,
        "live_paths": paths,
        "required_live_gates": REQUIRED_LIVE_GATES,
        "current_blockers": blockers,
        "release_notes": release_notes,
        "repo_dirty_count": dirty,
        "live_adjacent_dirty_count": live_dirty,
        "generated_at": _iso(),
        "llm_role": "advisory_only",
        "broker_truth": "schwab_pilot_orders and broker ack required before live state",
        "operator_flow": ["Auto-prepare", "Operator approve", "2FA confirm", "Broker submit"],
        "execution_model": (
            "Live Schwab submit is ENABLED via standing operator unlock — "
            "every order still requires desk approval (where applicable) and per-trade 2FA. "
            "Not autonomous."
        ),
    }


def to_markdown(state: dict) -> str:
    lines = [
        "# Current Execution State",
        "",
        f"Generated: {state.get('generated_at')}",
        "",
        "## Summary",
        "",
        f"- **Live architecture built:** {state.get('live_architecture_built')}",
        f"- **Live trading globally allowed:** {state.get('live_trading_global_allowed')}",
        f"- **Paper mode:** {state.get('paper_mode')}",
        f"- **Autonomous live (Alpaca gate):** {state.get('autonomous_status_label') or state.get('autonomous_live_trading_allowed')}",
        f"- **Autonomous live submit allowed:** {state.get('autonomous_live_submit_allowed')}",
        f"- **Operator live via 2FA:** {state.get('operator_status_label') or state.get('operator_live_via_2fa_allowed')}",
        f"- **Operator-approved live submit possible:** {state.get('operator_approved_live_submit_possible')}",
        f"- **Per-order 2FA required:** {state.get('per_order_2fa_required', True)}",
        "",
        state.get("execution_model")
        or "Live architecture is built. Autonomous submit is off; operator 2FA unlocks each order.",
        "",
        f"Unlock via: `{((state.get('live_unlock') or {}).get('unlock_via') or 'none')}`",
        "",
        "LLMs are advisory only — they never replace operator 2FA or desk approval.",
        "",
        "## Required live gates",
        "",
    ]
    for g in state.get("required_live_gates") or []:
        lines.append(f"- `{g}`")
    lines.extend(["", "## Current blockers", ""])
    blockers = state.get("current_blockers") or []
    if blockers:
        for b in blockers:
            lines.append(f"- {b}")
    else:
        lines.append("- None detected (operator approval + 2FA still required per order)")
    lines.extend([
        "",
        "## Repo hygiene",
        "",
        f"- Dirty file count: {state.get('repo_dirty_count')}",
        f"- Live-adjacent dirty count: {state.get('live_adjacent_dirty_count')}",
        "",
        "## Operator flow",
        "",
        " → ".join(state.get("operator_flow") or []),
        "",
        "*This document is generated by `python scripts/execution_state.py --markdown`. Do not claim autonomous live trading.*",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    state = build_state()
    if args.markdown:
        print(to_markdown(state))
    else:
        print(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
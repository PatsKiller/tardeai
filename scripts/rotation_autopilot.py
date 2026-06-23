#!/usr/bin/env python3
"""rotation_autopilot.py — Autonomous trend/rotation response (no operator drive).

Watches IWM vs SPY relative strength and persisted state for regime switches.
When small-cap rotation activates, strengthens, or needs refresh, automatically:
  1. Runs small_cap_rotation_bridge (watchlist + qualified intel + signal sync)
  2. Runs auto_proposal_generator for newly synced signals
  3. Alerts once on activation / fade (Telegram, advisory)

Invoked by:
  - warm_caches.py (every ~8 min — lightweight transition check)
  - market-hours cron via linux_launchers/run_rotation_autopilot.sh (every 15 min)
  - inference_layer_engine.py (after FeatureLayer detects rotation)
  - trade_ai_orchestrator.py stage 18e2 (unchanged — same bridge, shared logic)

Usage:
    .venv/bin/python scripts/rotation_autopilot.py --tick
    .venv/bin/python scripts/rotation_autopilot.py --tick --force-bridge
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("rotation_autopilot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

STATE_PATH = PROJECT_ROOT / "data" / "runtime" / "rotation_autopilot_state.json"
AUDIT_PATH = PROJECT_ROOT / "data" / "runtime" / "rotation_autopilot_latest.json"

MIN_BRIDGE_INTERVAL_MIN = 30
STRENGTH_DELTA_TRIGGER = 0.12
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except Exception:
        return None


def load_state() -> Dict[str, Any]:
    try:
        if STATE_PATH.exists():
            return json.loads(STATE_PATH.read_text())
    except Exception:
        pass
    return {}


def save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now().isoformat()
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


def detect_transition(prev: Dict[str, Any], rotation: Dict[str, Any]) -> Dict[str, Any]:
    prev_sig = prev.get("signal")
    curr_sig = rotation.get("signal")
    prev_str = float(prev.get("strength") or 0)
    curr_str = float(rotation.get("strength") or 0)
    return {
        "changed": prev_sig != curr_sig,
        "activated": prev_sig != "small_cap_outperform" and curr_sig == "small_cap_outperform",
        "deactivated": prev_sig == "small_cap_outperform" and curr_sig != "small_cap_outperform",
        "strengthened": (
            curr_sig == "small_cap_outperform"
            and prev_sig == "small_cap_outperform"
            and curr_str - prev_str >= STRENGTH_DELTA_TRIGGER
        ),
        "prior_signal": prev_sig,
        "prior_strength": prev_str,
    }


def _session_allows_action() -> Tuple[bool, str]:
    try:
        from market_session import current_market_session, is_trading_day

        if not is_trading_day():
            return False, "not_trading_day"
        session = current_market_session()
        if session in ("premarket", "regular"):
            return True, session
        return False, session
    except Exception:
        return True, "unknown_session"


def should_run_bridge(
    state: Dict[str, Any],
    rotation: Dict[str, Any],
    transition: Dict[str, Any],
    *,
    force: bool = False,
) -> Tuple[bool, str]:
    if force:
        return True, "forced"
    if rotation.get("signal") != "small_cap_outperform":
        return False, "rotation_inactive"

    if transition.get("activated"):
        return True, "activated"
    if transition.get("strengthened"):
        return True, "strengthened"

    last = _parse_ts(state.get("last_bridge_at"))
    if not last:
        return True, "first_active_run"

    age_min = (_now() - last).total_seconds() / 60.0
    if age_min >= MIN_BRIDGE_INTERVAL_MIN:
        return True, f"refresh_{int(age_min)}m"

    return False, f"throttled_{int(age_min)}m"


def _send_rotation_alert(kind: str, rotation: Dict[str, Any], bridge: Dict[str, Any]) -> bool:
    """One-shot advisory alert on activation or fade."""
    try:
        from telegram_alert import send_telegram
    except Exception:
        return False

    rs = rotation.get("rs_1d") or rotation.get("rs_5d") or rotation.get("rs_20d")
    rs_txt = f"{rs:+.2f}%" if rs is not None else "n/a"

    if kind == "activated":
        wl = bridge.get("watchlist_promoted", 0)
        ps = len(bridge.get("proposal_symbols") or [])
        pc = int((bridge.get("proposals") or {}).get("proposals_created") or 0)
        msg = (
            f"📊 *Small-cap rotation ON* (autonomous)\n"
            f"IWM leading SPY ({rs_txt} RS)\n"
            f"{rotation.get('explain', '')}\n"
            f"Auto-screened: {wl} watchlist · {ps} proposal-tier · {pc} proposals created\n"
            f"_No action needed — screening + proposals ran automatically._"
        )
    elif kind == "deactivated":
        msg = (
            f"📉 *Small-cap rotation faded* (autonomous)\n"
            f"{rotation.get('explain', 'IWM no longer leading SPY')}\n"
            f"_Watchlist items kept; new adds paused until signal returns._"
        )
    else:
        return False

    try:
        return bool(send_telegram(msg))
    except Exception as exc:
        log.debug("telegram alert skipped: %s", exc)
        return False


def run_autopilot_tick(
    *,
    force_bridge: bool = False,
    dry_run: bool = False,
    run_label: Optional[str] = None,
    trigger: str = "tick",
) -> Dict[str, Any]:
    """Single autonomous check — safe to call from cron/warm_caches/inference."""
    import market_rotation_signals as mrs

    prev = load_state()
    rotation = mrs.detect_small_cap_rotation()
    transition = detect_transition(prev, rotation)
    allows, session = _session_allows_action()

    result: Dict[str, Any] = {
        "ok": True,
        "trigger": trigger,
        "session": session,
        "action_allowed": allows,
        "rotation": rotation,
        "transition": transition,
        "bridge_ran": False,
        "bridge_reason": None,
        "bridge": {},
        "proposals": {},
        "alert_sent": False,
        "dry_run": dry_run,
        "at": _now().isoformat(),
    }

    run_bridge, bridge_reason = should_run_bridge(
        prev, rotation, transition, force=force_bridge,
    )
    result["bridge_reason"] = bridge_reason

    # Always persist latest signal snapshot (even when throttled)
    new_state = {
        **prev,
        "signal": rotation.get("signal"),
        "strength": rotation.get("strength"),
        "rs_1d": rotation.get("rs_1d"),
        "rs_5d": rotation.get("rs_5d"),
        "rs_20d": rotation.get("rs_20d"),
        "explain": rotation.get("explain"),
        "last_check_at": _now().isoformat(),
    }
    if transition.get("activated"):
        new_state["activated_at"] = _now().isoformat()

    # Trend *switches* run immediately; routine refresh only during premarket/regular.
    urgent = bridge_reason in ("activated", "strengthened", "forced", "first_active_run")
    may_execute = urgent or allows

    if run_bridge and may_execute and rotation.get("signal") == "small_cap_outperform":
        if dry_run:
            log.info("[dry-run] would run bridge: %s", bridge_reason)
            result["bridge_ran"] = True
        else:
            from small_cap_rotation_bridge import get_conn, run_rotation_bridge

            conn = get_conn()
            try:
                bridge = run_rotation_bridge(
                    conn, run_label=run_label, dry_run=False, force=False,
                )
                result["bridge"] = bridge
                result["bridge_ran"] = True
                new_state["last_bridge_at"] = _now().isoformat()
                props = bridge.get("proposals") or {}
                log.info(
                    "Bridge (%s): %d watchlist, %d proposal-tier, %s signals, %s proposals",
                    bridge_reason,
                    bridge.get("watchlist_promoted", 0),
                    len(bridge.get("proposal_symbols") or []),
                    (bridge.get("proposal_sync") or {}).get("sync_inserted"),
                    props.get("proposals_created"),
                )
                result["proposals"] = props
            finally:
                conn.close()

        if result.get("bridge_ran") and not dry_run:
            act_at = _parse_ts(new_state.get("activated_at") or prev.get("activated_at"))
            last_alert = _parse_ts(prev.get("last_activation_alert_at"))
            if act_at and (not last_alert or last_alert < act_at):
                if _send_rotation_alert("activated", rotation, result.get("bridge") or {}):
                    new_state["last_activation_alert_at"] = _now().isoformat()
                    result["alert_sent"] = True

    elif transition.get("deactivated") and not dry_run:
        last_fade_alert = _parse_ts(prev.get("last_deactivation_alert_at"))
        if not last_fade_alert or (_now() - last_fade_alert).total_seconds() > 3600 * 6:
            if _send_rotation_alert("deactivated", rotation, {}):
                new_state["last_deactivation_alert_at"] = _now().isoformat()
                result["alert_sent"] = True

    if not dry_run:
        save_state(new_state)
        try:
            AUDIT_PATH.write_text(json.dumps(result, indent=2, default=str))
        except Exception:
            pass

    if not run_bridge:
        log.debug("Bridge skipped: %s (session=%s)", bridge_reason, session)
    elif not may_execute:
        log.debug("Rotation active but session=%s — refresh deferred (urgent=%s)", session, urgent)

    return result


def main():
    ap = argparse.ArgumentParser(description="Rotation autopilot — autonomous trend-switch response")
    ap.add_argument("--tick", action="store_true", help="Run one autonomous check (cron default)")
    ap.add_argument("--force-bridge", action="store_true", help="Run bridge even if throttled")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run-label", type=str, default=None)
    ap.add_argument("--trigger", type=str, default="cli")
    args = ap.parse_args()

    if not args.tick and not args.force_bridge:
        ap.print_help()
        return 0

    result = run_autopilot_tick(
        force_bridge=args.force_bridge,
        dry_run=args.dry_run,
        run_label=args.run_label,
        trigger=args.trigger,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
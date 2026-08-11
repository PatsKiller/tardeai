#!/usr/bin/env python3
"""cio_reactive_cycle.py — Event + goal reactive wake cycle (READ_ONLY_ADVISORY).

Runs frequently (systemd timer) as a safety net *beside* the 30-min heartbeat.
Does NOT trade or mutate risk/broker state.

Cycle:
  1. Poll CIOEventBus for each agent subscription
  2. Enqueue wake jobs (deduped) into CIOWakeJobStore
  3. Enqueue goal-due wakes via CIOWakeDispatcher.enqueue_goal_wakes
  4. Optional: poll_and_dispatch (creates CIO runs when run_store available)
  5. Advance event-bus cursors only after successful enqueue/skip

Kill switch: data/runtime/CIO_REACTIVE_DISABLED
Enable flag: env CIO_REACTIVE_WAKES=1 (default on when kill switch absent)

Usage:
  .venv/bin/python scripts/cio_reactive_cycle.py --once
  .venv/bin/python scripts/cio_reactive_cycle.py --once --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

os.chdir(ROOT)

KILL = ROOT / "data" / "runtime" / "CIO_REACTIVE_DISABLED"
STATUS_PATH = ROOT / "data" / "runtime" / "cio_reactive_cycle_last.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enabled() -> bool:
    if KILL.exists():
        return False
    return os.environ.get("CIO_REACTIVE_WAKES", "1").strip().lower() not in (
        "0", "false", "off", "no",
    )


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def run_once(*, max_wakes: int = 12, dispatch: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ts": _now(),
        "authority": "READ_ONLY_ADVISORY",
        "enabled": _enabled(),
        "event_enqueued": [],
        "event_skipped": [],
        "cursor_advanced": [],
        "goal_enqueue": {},
        "dispatch": {},
        "errors": [],
    }
    if not out["enabled"]:
        out["errors"].append("reactive wakes disabled (kill switch or CIO_REACTIVE_WAKES=0)")
        return out

    try:
        from scripts.lib.cio_event_bus import (
            CIOEventBus,
            AGENT_EVENT_ROUTING,
            EVENT_PRIORITY,
        )
    except Exception as exc:
        out["errors"].append(f"event_bus_import: {exc}")
        return out

    try:
        from scripts.lib.cio_wake_jobs import CIOWakeJobStore
    except Exception as exc:
        out["errors"].append(f"wake_store_import: {exc}")
        return out

    bus = CIOEventBus()
    wake_store = CIOWakeJobStore()
    hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    enqueued_n = 0
    recent_types: list[str] = []

    for agent_id, event_types in AGENT_EVENT_ROUTING.items():
        try:
            events = bus.poll(consumer=f"reactive:{agent_id}", event_types=list(event_types))
        except Exception as exc:
            out["errors"].append(f"poll:{agent_id}:{exc}")
            continue
        if not events:
            continue
        last_id = None
        for ev in events:
            if enqueued_n >= max_wakes:
                break
            et = getattr(ev, "event_type", None) or (ev.get("event_type") if isinstance(ev, dict) else None)
            eid = getattr(ev, "event_id", None) or (ev.get("event_id") if isinstance(ev, dict) else None)
            if not et or not eid:
                continue
            recent_types.append(str(et))
            wake_job_id = f"wake_ev_{agent_id}_{_hash(eid)}_{hour}"
            # Dedup: if already in store as pending/active, skip
            try:
                existing = wake_store.get_wake_job(wake_job_id) if hasattr(wake_store, "get_wake_job") else None
                if existing and existing.get("current_status") in (
                    "PENDING", "CLAIMED", "DISPATCHED", "IN_FLIGHT", "ACKNOWLEDGED",
                ):
                    out["event_skipped"].append({"wake_job_id": wake_job_id, "reason": "already_active"})
                    last_id = eid
                    continue
            except Exception:
                pass

            priority = EVENT_PRIORITY.get(str(et), "NORMAL")
            reason = str(et).upper().replace(".", "_")
            wake_payload = {
                "wake_job_id": wake_job_id,
                "trigger_type": "EVENT_BUS",
                "trigger_ref": eid,
                "trigger_hash": _hash(f"{agent_id}:{eid}"),
                "reason_codes": ["EVENT_BUS", reason],
                "required_domains": ["portfolio"],
                "wake_intent": "NEW_RUN",
                "idempotency_key": wake_job_id,
                "context": {
                    "target_agent": agent_id,
                    "event_type": et,
                    "event_id": eid,
                    "priority": priority,
                    "authority": "READ_ONLY_ADVISORY",
                },
            }
            try:
                wake_store.enqueue(
                    wake_payload,
                    actor_id="cio_reactive_cycle",
                    actor_type="system",
                    authority="READ_ONLY_ADVISORY",
                )
                out["event_enqueued"].append({
                    "agent_id": agent_id,
                    "event_type": et,
                    "event_id": eid,
                    "wake_job_id": wake_job_id,
                })
                enqueued_n += 1
            except Exception as exc:
                # treat duplicate as skip
                msg = str(exc)
                if "already" in msg.lower() or "duplicate" in msg.lower() or "exists" in msg.lower():
                    out["event_skipped"].append({"wake_job_id": wake_job_id, "reason": msg[:120]})
                else:
                    out["errors"].append(f"enqueue:{wake_job_id}:{msg[:160]}")
            last_id = eid

        if last_id:
            try:
                bus.advance_cursor(f"reactive:{agent_id}", last_id)
                out["cursor_advanced"].append({"consumer": f"reactive:{agent_id}", "event_id": last_id})
            except Exception as exc:
                out["errors"].append(f"cursor:{agent_id}:{exc}")

    # Goal-due / event-linked wakes
    try:
        from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher
        disp = CIOWakeDispatcher(wake_store=wake_store)
        out["goal_enqueue"] = disp.enqueue_goal_wakes(
            max_new=max(1, max_wakes // 2),
            recent_event_types=list(set(recent_types)) or None,
        )
        if dispatch:
            out["dispatch"] = disp.poll_and_dispatch(max_dispatches=max_wakes)
    except Exception as exc:
        out["errors"].append(f"dispatcher:{exc}")

    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(out, indent=2, default=str))
    except Exception:
        pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", default=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-wakes", type=int, default=12)
    ap.add_argument("--no-dispatch", action="store_true")
    args = ap.parse_args()
    res = run_once(max_wakes=args.max_wakes, dispatch=not args.no_dispatch)
    if args.json:
        print(json.dumps(res, indent=2, default=str))
    else:
        print(f"[{res['ts']}] reactive cycle enabled={res['enabled']}")
        print(f"  event_enqueued={len(res['event_enqueued'])} skipped={len(res['event_skipped'])}")
        ge = res.get("goal_enqueue") or {}
        print(f"  goal_enqueued={len(ge.get('enqueued') or [])} blocked={len(ge.get('blocked_not_ready') or [])}")
        d = res.get("dispatch") or {}
        print(f"  dispatched={d.get('dispatched_count', 0)} errors={len(res.get('errors') or [])}")
        for e in (res.get("errors") or [])[:5]:
            print(f"  ERR: {e}")
    return 0 if not res.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())

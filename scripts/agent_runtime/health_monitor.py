#!/usr/bin/env python3
"""Read-only health monitor for the governed Agent Runtime.

Checks local readiness and operations surfaces, detects failed/stuck runs, and
writes one non-secret observation for Command Center and the system health
agent. It has no dispatch, provider, scheduler, or financial authority.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "http://127.0.0.1:7777"
DEFAULT_STATE = "~/.local/state/tradeai/agent-runtime-health.json"


def _get_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    with urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} from {url}")
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid JSON object from {url}")
    return payload


def collect(base_url: str) -> dict[str, Any]:
    observed_at = datetime.now(timezone.utc).isoformat()
    checks: list[dict[str, Any]] = []
    state = "HEALTHY"

    try:
        readiness = _get_json(f"{base_url}/api/v3/agent-runtime/readiness")
        wiring = readiness.get("wiring") or {}
        read_state = (wiring.get("read_api") or {}).get("state")
        dispatch_state = (wiring.get("dispatch") or {}).get("state")
        wiring_ok = read_state == "CONNECTED" and dispatch_state == "WIRED"
        checks.append({
            "check": "wiring",
            "status": "PASS" if wiring_ok else "FAIL",
            "read_api": read_state,
            "dispatch": dispatch_state,
        })
        if not wiring_ok:
            state = "DEGRADED"
    except Exception as exc:
        checks.append({"check": "wiring", "status": "FAIL", "detail": str(exc)})
        state = "DEGRADED"

    installed = active = 0
    try:
        operations = _get_json(f"{base_url}/api/v3/agent-runtime/operations")
        agents = operations.get("agents") or []
        installed = sum(1 for row in agents if row.get("timer_state") in {"ACTIVE", "INACTIVE"})
        active = sum(1 for row in agents if row.get("timer_state") == "ACTIVE")
        checks.append({
            "check": "scheduler",
            "status": "PASS" if installed == active else "WARN",
            "installed_timers": installed,
            "active_timers": active,
            "detail": (
                "No timers installed; execution is manual/event-queue only."
                if installed == 0
                else f"{active}/{installed} installed timers active."
            ),
        })
        if installed and active != installed and state == "HEALTHY":
            state = "DEGRADED"
        blocked_sources = [
            row.get("source_id")
            for row in (operations.get("sources") or [])
            if row.get("state") == "BLOCKED_SOURCE"
        ]
        queue_posture = operations.get("queue_posture") or {}
        checks.append({
            "check": "trigger_sources",
            "status": "PASS" if not blocked_sources else "WARN",
            "blocked": blocked_sources,
            "available": bool(queue_posture.get("available")),
        })
        if blocked_sources and state == "HEALTHY":
            state = "DEGRADED"
        stale_queues = [
            row.get("agent_id")
            for row in agents
            if int(row.get("queue_depth") or 0) > 0 and row.get("source_state") == "BLOCKED_SOURCE"
        ]
        checks.append({
            "check": "trigger_queue",
            "status": "PASS" if not stale_queues else "WARN",
            "stale_agent_queues": stale_queues,
        })
        if stale_queues and state == "HEALTHY":
            state = "DEGRADED"
    except Exception as exc:
        checks.append({"check": "scheduler", "status": "FAIL", "detail": str(exc)})
        state = "DEGRADED"

    try:
        runs = _get_json(f"{base_url}/api/v3/agent-runtime/runs?limit=200")
        rows = runs.get("data") or []
        failed = sum(1 for row in rows if str(row.get("status") or "").upper() in {"FAILED", "DEADLINE_EXCEEDED"})
        running = sum(1 for row in rows if str(row.get("status") or "").upper() in {"RUNNING", "RETRIEVING", "REASONING"})
        checks.append({
            "check": "runs",
            "status": "PASS" if failed == 0 else "WARN",
            "sample_size": len(rows),
            "failed": failed,
            "running": running,
        })
        if failed and state == "HEALTHY":
            state = "DEGRADED"
    except Exception as exc:
        checks.append({"check": "runs", "status": "FAIL", "detail": str(exc)})
        state = "DEGRADED"

    mode = "SCHEDULED" if installed else "MANUAL_DISPATCH_ONLY"
    return {
        "contract": "agent-runtime-health-v1",
        "observed_at": observed_at,
        "state": state,
        "execution_mode": mode,
        "detail": (
            f"Agent Runtime {state.lower()}; {active}/{installed} installed timers active. "
            "Monitor is read-only and never dispatches work."
        ),
        "authority": {
            "dispatch": False,
            "provider_call": False,
            "service_control": False,
            "financial_action": False,
        },
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("AGENT_RUNTIME_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--state-file",
        default=os.environ.get("AGENT_RUNTIME_HEALTH_STATE_FILE", DEFAULT_STATE),
    )
    args = parser.parse_args()
    payload = collect(args.base_url.rstrip("/"))
    path = Path(args.state_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    print(json.dumps(payload, separators=(",", ":")))
    # A degraded runtime is a valid monitor observation, not a monitor crash.
    # Consumers alert on payload.state; systemd should only fail when collection
    # itself could not produce an observation.
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (URLError, OSError, ValueError, RuntimeError) as exc:
        print(f"agent-runtime health monitor failed: {exc}", file=sys.stderr)
        raise SystemExit(2)

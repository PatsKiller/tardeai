#!/usr/bin/env python3
"""Get runtime status for all timers/services. Callable from API or CLI."""
import json, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone

def get_timer_status():
    """Get next/last run for all user timers."""
    timers = {}
    try:
        r = subprocess.run(
            ["systemctl", "--user", "list-timers", "--all", "--no-pager", "--output=json"],
            capture_output=True, text=True, timeout=5
        )
        # Fallback: parse plain output
        r2 = subprocess.run(
            ["systemctl", "--user", "list-timers", "--all", "--no-pager"],
            capture_output=True, text=True, timeout=5
        )
        for line in r2.stdout.strip().splitlines()[1:]:
            if ".timer" not in line:
                continue
            parts = line.split()
            timer_name = next((p for p in parts if ".timer" in p), None)
            service_name = next((p for p in parts if ".service" in p), None)
            if not timer_name:
                continue
            stem = timer_name.replace(".timer", "")
            # Get detailed status
            try:
                s = subprocess.run(
                    ["systemctl", "--user", "show", timer_name,
                     "--property=NextElapseUSecRealtime,LastTriggerUSec,Result"],
                    capture_output=True, text=True, timeout=3
                )
                props = {}
                for pl in s.stdout.strip().splitlines():
                    if "=" in pl:
                        k, v = pl.split("=", 1)
                        props[k] = v.strip()

                # Get service status
                svc = subprocess.run(
                    ["systemctl", "--user", "show", service_name or f"{stem}.service",
                     "--property=ActiveState,Result,ExecMainStartTimestamp,ExecMainExitTimestamp"],
                    capture_output=True, text=True, timeout=3
                )
                for pl in svc.stdout.strip().splitlines():
                    if "=" in pl:
                        k, v = pl.split("=", 1)
                        props[f"svc_{k}"] = v.strip()

                timers[stem] = {
                    "next_run": props.get("NextElapseUSecRealtime", ""),
                    "last_trigger": props.get("LastTriggerUSec", ""),
                    "timer_result": props.get("Result", ""),
                    "service_state": props.get("svc_ActiveState", ""),
                    "service_result": props.get("svc_Result", ""),
                    "last_start": props.get("svc_ExecMainStartTimestamp", ""),
                    "last_exit": props.get("svc_ExecMainExitTimestamp", ""),
                }
            except Exception:
                timers[stem] = {"error": "status unavailable"}
    except Exception as e:
        return {"error": str(e)}
    return timers


if __name__ == "__main__":
    if "--json" in sys.argv:
        status = get_timer_status()
        print(json.dumps(status, indent=2))
    else:
        status = get_timer_status()
        now = datetime.now()
        for name, s in sorted(status.items()):
            state = s.get("service_state", "?")
            result = s.get("service_result", "?")
            next_run = s.get("next_run", "?")
            last = s.get("last_trigger", "?")
            icon = "🟢" if result == "success" else "🔴" if result == "failed" else "⚪"
            print(f"  {icon} {name:45s} state={state:10s} result={result:8s} next={next_run}")

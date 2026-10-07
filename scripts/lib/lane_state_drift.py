"""Registry state vs host state (2026-10-07).

`check_lane_registry` proves every scheduled job has a row; it cannot see a row whose STATE is
wrong. Measured on served c5de69ee9: `contradiction-adjudicator` (timer enabled, fires daily) and
`maturity-remeasure` (cron line present, writes weekly) were both declared NEVER_SCHEDULED and the
gate said "clean". This module classifies each lane's declared state against what the host runs,
reusing the n8n packet's classifier (scripts/lib/n8n_lane_host_conflict.py), and never changes
either side.
"""
from __future__ import annotations

import subprocess
from typing import Any, Callable, Optional

try:
    from scripts.lib import n8n_lane_host_conflict as HC
except ImportError:  # pragma: no cover - sys.path shape under cron
    import n8n_lane_host_conflict as HC  # type: ignore

CONFLICT_CODES = frozenset({
    HC.ENABLED_WHILE_DECLARED_RETIRED,
    HC.ENABLED_WHILE_DECLARED_NEVER_SCHEDULED,
    HC.CRON_PRESENT_WHILE_DECLARED_NEVER_SCHEDULED,
})
NOT_MEASURED = "NOT_MEASURED"


def timer_state(unit: str, *, run=subprocess.run) -> Optional[dict[str, Any]]:
    """{unit_file_state, sub_state, next_elapse, recurring} from systemctl, or None when unreadable."""
    try:
        out = run(["systemctl", "--user", "show", unit, "-p", "UnitFileState", "-p", "SubState",
                   "-p", "NextElapseUSecRealtime", "-p", "TimersCalendar"],
                  capture_output=True, text=True, timeout=10).stdout
    except Exception:  # noqa: BLE001
        return None
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if not props:
        return None
    return {
        "unit_file_state": props.get("UnitFileState", ""),
        "sub_state": props.get("SubState", ""),
        "next_elapse": props.get("NextElapseUSecRealtime", ""),
        "recurring": "OnCalendar" in props.get("TimersCalendar", "") or "OnUnitActiveSec" in out,
    }


def classify_lanes(lanes: list[dict[str, Any]], *, cron_rows: list[dict[str, Any]],
                   timer_state_fn: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
                   host_state: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """One row per lane: {lane_id, kind, declared_state, code, evidence}.

    ``host_state`` (CI / tests) is {"timers": {unit: state-dict}} captured elsewhere; without it and
    without a live ``timer_state_fn`` a systemd lane is NOT_MEASURED, never ALIGNED.
    """
    timers = (host_state or {}).get("timers") or {}
    cron_text = "\n".join(str(c.get("expression") or "") for c in cron_rows)
    out: list[dict[str, Any]] = []
    for lane in lanes:
        sched = lane.get("scheduler") or {}
        kind = str(sched.get("kind") or "none")
        declared = str(lane.get("state") or "")
        row = {"lane_id": lane.get("lane_id"), "kind": kind, "declared_state": declared, "code": HC.UNCLASSIFIED, "evidence": {}}
        if kind == "systemd":
            unit = str(sched.get("expression") or "")
            st = timers.get(unit) if unit in timers else (timer_state_fn(unit) if timer_state_fn else None)
            if not st:
                row["code"] = NOT_MEASURED
                row["evidence"] = {"unit": unit, "reason": "timer state unavailable"}
            else:
                row["code"] = HC.classify_timer(declared_state=declared, unit_file_state=st.get("unit_file_state", ""),
                                                sub_state=st.get("sub_state", ""), next_elapse=st.get("next_elapse"),
                                                recurring=bool(st.get("recurring", True)))
                row["evidence"] = {"unit": unit, **{k: st.get(k) for k in ("unit_file_state", "sub_state", "next_elapse")}}
        elif kind == "cron":
            marker = str(sched.get("match") or "")
            present = bool(marker) and marker in cron_text
            row["code"] = HC.classify_cron(declared_state=declared, command_present=present)
            row["evidence"] = {"match": marker, "command_present": present}
        out.append(row)
    return out


def conflicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("code") in CONFLICT_CODES]

"""Host-side watch of the n8n alerting path: P1 when the incident router errors or stops (operator 2026-10-10).

Why: n8n workflow errors reach the host through the incident router (`tradeai-incident-router` is every generic
workflow's errorWorkflow and the only caller of the relay's POST /event). Its OWN failures have no error workflow,
so they never reach /event, and an n8n outage stops every workflow at once. Neither is visible from inside n8n.

This module reads only host-side files the relay already writes ($TRADEAI_STATE_ROOT/data/runtime/n8n_relay/
relay_log.jsonl), never n8n, its database or the network, and is called by scripts/incident_notifier.py (host cron,
so the P1 path does not depend on n8n, AGENTS.md §24.1 proposed) and by the incident fan-in (for the SIEM row).

Findings (all P1, source `n8n_alert_path`):
  * tradeai-incident-router:error    in the last ERROR_MIN: a relay /due line attributed to the incident router
                                     (lanes == its lane filter) was REFUSED, or a POST /event line (only the incident
                                     router calls /event) was not ACCEPTED — that execution stops in error.
  * tradeai-incident-router:stalled  the incident router (`* * * * *`) has no /due line for STALL_MIN although it
                                     had one in the last SEEN_H hours (it was running and stopped).
  * n8n-schedule:due_refused         a source=schedule /due line from a relay without lane attribution (no `lanes`
                                     key: dispatcher, incident router or heartbeat watcher) was REFUSED in ERROR_MIN.
  * n8n-schedule:stalled             no source=schedule /due line at all for STALL_MIN although there were some in
                                     the last SEEN_H hours: n8n, the relay or every scheduled workflow stopped.

Limits (say them, AGENTS.md "Detector shape"): an incident-router execution that fails AFTER a successful /due (in a
Code or IF node, with no relay call failing) is invisible here; the n8n `execution_entity` read that would see it is
an operator option, not wired. A deliberate deactivation of the workflows reads as stalled for SEEN_H hours.

Env: TRADEAI_ALERT_PATH_WATCH=0 opts out; TRADEAI_ALERT_PATH_STALL_MIN (10), TRADEAI_ALERT_PATH_ERROR_MIN (15),
TRADEAI_ALERT_PATH_SEEN_H (24). AUTHORITY: READ_ONLY_ADVISORY. No send, no write.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

SOURCE = "n8n_alert_path"
RELAY_LOG_REL = "data/runtime/n8n_relay/relay_log.jsonl"
INCIDENT_ROUTER = "tradeai-incident-router"
# The incident router's GET /due lane filter (docs/implementation/n8n-maturity/workflows/tradeai-incident-router.json;
# a drift test pins it). No other generic workflow asks for these lanes.
INCIDENT_ROUTER_LANES = frozenset({"n8n-incident-fanin", "incident-notifier"})
DEFAULT_STALL_MIN = 10.0
DEFAULT_ERROR_MIN = 15.0
DEFAULT_SEEN_H = 24.0
TAIL_BYTES = 4_000_000


def _num(env: dict, name: str, default: float) -> float:
    try:
        v = float(env.get(name) or default)
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def _ts(value: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _tail(path: Path, max_bytes: int = TAIL_BYTES) -> list[dict]:
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            chunk = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    out = []
    for line in chunk.splitlines()[1 if size > max_bytes else 0:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _finding(item: str, detail: str, detected_at: datetime) -> dict[str, Any]:
    return {"source": SOURCE, "item": item, "severity": "P1", "detail": detail[:160], "artifact_rel": RELAY_LOG_REL,
            "store": "data/runtime", "detected_at": detected_at.isoformat()}


def findings(root: Path, now: datetime, env: Optional[dict] = None) -> tuple[list[dict[str, Any]], str]:
    """(P1 findings, note). Read-only over the relay log; a missing log is a note, never a finding."""
    env = os.environ if env is None else env
    if str(env.get("TRADEAI_ALERT_PATH_WATCH", "1")) == "0":
        return [], "unavailable:disabled_by_env"
    stall = timedelta(minutes=_num(env, "TRADEAI_ALERT_PATH_STALL_MIN", DEFAULT_STALL_MIN))
    err = timedelta(minutes=_num(env, "TRADEAI_ALERT_PATH_ERROR_MIN", DEFAULT_ERROR_MIN))
    seen = timedelta(hours=_num(env, "TRADEAI_ALERT_PATH_SEEN_H", DEFAULT_SEEN_H))
    path = root / RELAY_LOG_REL
    if not path.exists():
        return [], "relay_log:absent"
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    router_last: Optional[datetime] = None
    sched_last: Optional[datetime] = None
    router_errors: list[tuple[datetime, str]] = []
    sched_errors: list[tuple[datetime, str]] = []
    attributed = 0
    for r in _tail(path):
        at = _ts(r.get("at"))
        if at is None or at > now + timedelta(minutes=5) or now - at > seen:
            continue
        op = r.get("op")
        state = str(r.get("state") or "")
        reason = str(r.get("reason") or "")
        if op == "due":
            lanes = r.get("lanes")
            is_router = isinstance(lanes, list) and frozenset(map(str, lanes)) == INCIDENT_ROUTER_LANES
            attributed += isinstance(lanes, list)
            if r.get("source") == "schedule":
                sched_last = max(sched_last or at, at)
            if is_router:
                router_last = max(router_last or at, at)
            if state != "OK" and now - at <= err:
                if is_router:
                    router_errors.append((at, f"/due {state} {reason}"))
                elif r.get("source") == "schedule" and "lanes" not in r:
                    sched_errors.append((at, f"/due {state} {reason}"))
        elif op == "event":                          # cadence comes from attributed /due lines only
            if state != "ACCEPTED" and now - at <= err:
                router_errors.append((at, f"/event {state} {reason}"))
    out: list[dict[str, Any]] = []
    if router_errors:
        router_errors.sort()
        last_at, last_why = router_errors[-1]
        out.append(_finding(f"{INCIDENT_ROUTER}:error",
                            f"{len(router_errors)} failed relay call(s) by the incident router in {err.seconds // 60} min, "
                            f"last {last_at:%H:%MZ} {last_why}; its own errors never reach /event", router_errors[0][0]))
    if router_last is not None and now - router_last > stall:
        out.append(_finding(f"{INCIDENT_ROUTER}:stalled",
                            f"incident router silent {int((now - router_last).total_seconds() // 60)} min (last /due "
                            f"{router_last:%H:%MZ}; runs every minute): n8n errors cannot reach the operator", day0))
    if sched_errors:
        sched_errors.sort()
        last_at, last_why = sched_errors[-1]
        out.append(_finding("n8n-schedule:due_refused",
                            f"{len(sched_errors)} refused source=schedule /due in {err.seconds // 60} min, last "
                            f"{last_at:%H:%MZ} {last_why} (dispatcher/incident-router/heartbeat; relay without lane "
                            f"attribution)", sched_errors[0][0]))
    if sched_last is not None and now - sched_last > stall:
        out.append(_finding("n8n-schedule:stalled",
                            f"no source=schedule /due for {int((now - sched_last).total_seconds() // 60)} min (last "
                            f"{sched_last:%H:%MZ}): n8n, the relay or every scheduled workflow stopped", day0))
    note = (f"ok:{len(out)}:router_last={router_last.isoformat() if router_last else None}:"
            f"schedule_last={sched_last.isoformat() if sched_last else None}:attributed_due_rows={attributed}")
    return out, note

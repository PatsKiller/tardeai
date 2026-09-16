"""One alert lifecycle for the scheduled condition monitors.

WHY
---
Seven scheduled monitors each re-implemented the same eleven lines:

    fingerprint = {...}
    previous = json.loads(STATE_PATH.read_text()).get("fingerprint", {})
    if fingerprint == previous:
        print("  alert: suppressed — unchanged since the last run.")
        return

So the same defect was written seven times. **A permanently broken condition
alerts exactly once and is then silent forever**, because "unchanged" is treated
as "not worth saying" with no upper bound on the silence. Measured 2026-09-16:
`check_expected_services` had been suppressing a FAILED path unit since 00:13;
`check_data_source_health` had been suppressing finnhub's 401 for 51 days.

And none of the seven wrote a row anyone could acknowledge: 7,830 `alert_events`
rows, 100% `lifecycle_state='active'`, 0 with a `telegram_message_id`.

WHAT THIS IS
------------
The suppression decision moves to `alert_condition_state` — already live with
1,279 conditions and seven other consumers — and this module adds the two things
a monitor needs around it:

    evaluate()   ask the shared state machine what this observation is
    commit()     persist it: an alert_events row carrying the Telegram message
                 id, and, on recovery, resolve the rows this condition opened

BEHAVIOUR (OPERATIONS.md:71-75, the throttle the health agent already uses)
--------------------------------------------------------------------------
    new          first time this condition is bad                  → notify
    reversed     the finding set CHANGED (escalation)              → notify
    heartbeat    still bad, and `min_realert_minutes` has elapsed  → notify
    ongoing      still bad, inside the window                      → silent
    recovered    was bad, now healthy                              → notify + resolve

`min_realert_minutes` is 360 because OPERATIONS.md §3 already specifies 360 for
exactly this throttle. It is not a new number.

COMMIT IS AFTER THE SEND, DELIBERATELY
--------------------------------------
Every one of the seven monitors has a test named
`test_a_send_failure_does_not_advance_state`, and they are right: advancing the
state before the transport is confirmed loses the alert entirely — the next run
sees "unchanged" and says nothing. `evaluate()` therefore snapshots the store,
and `rollback()` puts it back when the send fails.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_LIB = Path(__file__).resolve().parent
_SCRIPTS = _LIB.parent
if str(_LIB) not in sys.path:
    # APPEND. Prepending would put scripts/lib ahead of scripts/ for every
    # process that imports this module, and several names exist in both
    # (research_lane_health is a monitor AND a library) — so `import
    # research_lane_health` would silently get the wrong one.
    sys.path.append(str(_LIB))

from alert_condition_state import observe, store_path  # noqa: E402

#: OPERATIONS.md:71-75 — "6-hour heartbeat (`min_realert_minutes` = 360) while
#: still unhealthy/degraded". The health agent's throttle, applied to the
#: monitors that never had one.
MIN_REALERT_MINUTES = 360

#: alert_events.alert_type carries a CHECK constraint. These are the two members
#: of it that fit a condition monitor; anything else is rejected by the database
#: and the row is silently lost, which is the failure mode this module exists to
#: end.
TYPE_SYSTEM_HEALTH = "system_health"
TYPE_DATA_INTEGRITY = "data_integrity"


def _db_enabled() -> bool:
    """alert_events rows are production evidence.

    Same barrier shape as TRADEAI_AUDIT_LEDGER_DB: on by default, and turned off
    by tests/conftest.py so a unit test cannot mint rows in the live database.
    """
    return os.environ.get("TRADEAI_ALERT_EVENT_DB", "1").strip() != "0"


def _writer():
    """alert_event_writer, without putting scripts/ on sys.path.

    research_lane_health.py runs under a G2 rule that forbids scripts/ on the
    path (it creates a second identity for every `lib.X` module). Loading the
    writer from its file keeps that rule intact.
    """
    try:
        import alert_event_writer as w  # already importable for most callers

        return w
    except ImportError:
        pass
    path = _SCRIPTS / "alert_event_writer.py"
    spec = importlib.util.spec_from_file_location("_alert_event_writer_via_transition", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@dataclass
class Transition:
    """One observation of one condition, and what the operator should be told."""

    key: str
    state: str
    alertable: bool
    action: str
    notify: bool
    uid: str
    previous: Optional[str]
    suppress_count: int
    notify_count: int
    path: Optional[Path] = None
    _snapshot: Optional[str] = None
    _settled: bool = False

    # ── what the monitor prints when it stays quiet ──────────────────────────

    @property
    def recovered(self) -> bool:
        return self.action == "recovered"

    @property
    def escalated(self) -> bool:
        """The finding set changed while still bad — new information."""
        return self.action == "reversed"

    def quiet_reason(self, min_realert_minutes: int = MIN_REALERT_MINUTES) -> str:
        """Why nothing was sent — and when something will be.

        The old message ("suppressed — unchanged since the last run") never said
        the silence had an end. This one does.
        """
        if self.action == "ongoing" and self.alertable:
            return (
                f"suppressed — unchanged since the last run "
                f"(run {self.suppress_count}); a heartbeat follows at "
                f"{min_realert_minutes} minutes if it is still unhealthy."
            )
        if not self.alertable:
            return "healthy — nothing to report, and nothing was open."
        return f"suppressed — {self.action}."

    # ── settling the observation ────────────────────────────────────────────

    def rollback(self) -> None:
        """Put the store back. The send failed; the finding must not be lost."""
        if self._settled:
            return
        self._settled = True
        p = store_path(self.path)
        try:
            if self._snapshot is None:
                if p.exists():
                    p.unlink()
            else:
                p.write_text(self._snapshot, encoding="utf-8")
        except OSError:
            pass

    def commit(
        self,
        *,
        body: str = "",
        alert_type: str = TYPE_SYSTEM_HEALTH,
        source_script: str = "",
        severity: Optional[str] = None,
        telegram_message_id: Optional[str] = None,
        symbol: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Keep the observation and record it where it can be acknowledged.

        Never raises: a database that is down must not cost the operator the
        alert that was already delivered.
        """
        self._settled = True
        out: dict[str, Any] = {"alert_event_id": None, "resolved_rows": 0, "error": None}
        if not self.notify:
            return out

        if not _db_enabled():
            out["error"] = "db_disabled"
            return out

        if severity is None:
            severity = "info" if self.recovered else "warning"
        parsed = {
            "condition_key": self.key,
            "condition_state": self.state,
            "transition": self.action,
            "previous_state": self.previous,
            "notify_count": self.notify_count,
            "suppressed_since_last_notify": self.suppress_count,
        }
        if payload:
            parsed.update(payload)

        try:
            w = _writer()
            out["alert_event_id"] = w.save_alert_event(
                alert_type=alert_type,
                raw_text=body or self.state,
                symbol=symbol,
                severity=severity,
                source_script=source_script,
                parsed_payload=parsed,
                telegram_message_id=telegram_message_id,
            )
            if self.recovered:
                # The condition cleared. Everything it opened is resolved — this
                # is the transition that 7,830 rows never got.
                out["resolved_rows"] = w.resolve_alert_events(
                    condition_key=self.key,
                    source_script=source_script,
                    resolved_by=f"auto:{source_script or 'alert_transition'}",
                )
        except Exception as exc:  # noqa: BLE001 - recording must never re-break delivery
            out["error"] = f"{type(exc).__name__}: {exc}"
        return out


def evaluate(
    key: str,
    state: str,
    *,
    alertable: bool = True,
    path: Optional[Path] = None,
    min_realert_minutes: int = MIN_REALERT_MINUTES,
    extra: Optional[dict[str, Any]] = None,
) -> Transition:
    """Ask the shared state machine what this observation is.

    `state` must encode the whole finding set, not merely "bad": that is what
    makes an escalation distinguishable from a repeat. `fingerprint_state()`
    builds one.
    """
    p = store_path(path)
    try:
        snapshot = p.read_text(encoding="utf-8") if p.exists() else None
    except OSError:
        snapshot = None

    obs = observe(
        key,
        state,
        alertable=alertable,
        path=path,
        extra=extra,
        min_realert_minutes=min_realert_minutes,
    )
    return Transition(
        key=key,
        state=state,
        alertable=bool(alertable),
        action=obs["action"],
        notify=bool(obs["notify"]),
        uid=obs["uid"],
        previous=obs.get("previous"),
        suppress_count=int(obs.get("suppress_count", 0)),
        notify_count=int(obs.get("notify_count", 0)),
        path=path,
        _snapshot=snapshot,
    )


def fingerprint_state(fingerprint: dict[str, Any]) -> str:
    """A stable state string for a finding set.

    Sorted, so dictionary order cannot fake a change; JSON, so a count moving
    from 8 to 900 IS a change and re-alerts. Empty means healthy.
    """
    if not fingerprint:
        return "CLEAR"
    return json.dumps({str(k): fingerprint[k] for k in sorted(fingerprint, key=str)},
                      sort_keys=True, default=str)


def previous_fingerprint(state: Optional[str]) -> dict[str, Any]:
    """The finding set behind a previous state string.

    The monitors say "NEW since the last run" and "Recovered:" by diffing
    against what they saw last time; this gives them that back out of the state
    machine, so no monitor needs its own parallel state file to keep saying it.
    """
    if not state or state == "CLEAR":
        return {}
    try:
        out = json.loads(state)
    except (TypeError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}

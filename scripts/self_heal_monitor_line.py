#!/usr/bin/env python3
"""One hourly self-heal status block for the hourly operator email.

Read-only: no network, no model, no writes, no schedule. It reads the live incident store
(data/coordination/incidents/{index,supervisor_last,watchers_last,supervisor_calls}.json),
the fixer state (data/runtime/self_heal_fixer_state.json) and the reviewed runbook config
(config/incident_runbook_actions.json) and prints four lines the lead pastes as-is:

    SELF-HEAL · 17:07 UTC
    detected 5 (last hour) · dispatched 0 · fixed 4 (last hour) · still blocked 27 · unresolved 10
    supervisor 2026-11-03T17:02:00Z: considered 5, actions 0, dispatched 0, skipped 5 (5 on daily model-call cap); model calls today 40/40
    watchers 2026-11-03T17:05:00Z: 10/10 without a gap; findings lane_health 16, health_tick 3, ...
    verdict: NOT LIVE — DETECT alive · DECIDE starved by the daily model-call cap · FIX not scheduled (5 requests queued)

Definitions (stable; do not "improve" silently):
  detected      incidents with opened_at inside the last 60 minutes
  dispatched    supervisor dispatches in its last cycle (the fixer is unscheduled)
  fixed         status=fixed records whose closed_at / fixed_at / resolved_at is inside the last
                60 minutes; a won't-fix closure (status closed) is not a repair
  model calls today  supervisor_calls.json count when its date is today (UTC); a counter left from
                another day is 0, matching incident_supervisor._calls_today
  blocked       records with status blocked; unresolved = the index summary's unresolved count
Verdict rules:
  DETECT alive       watcher receipt fresh (0 <= age <= 15 min) and every watcher enabled with no
                     gap; a switched-off watcher is reported as DETECT disabled (it is not evidence
                     of health, however fresh the receipt), ahead of stale/gapped
  DECIDE working     supervisor receipt fresh (0 <= age <= 30 min; the timer runs every 10 min),
                     no skip in the last cycle is a failed triage (model_error/unparseable), and
                     not every skip is "daily model-call cap"; else stale/failing/starved
  FIX not scheduled  fix_requested jobs waiting in the fixer state (no schedule exists; 24.5 still gates the PR)
  unknown            a store that could not be read or does not have its documented shape renders as
                     "unknown (reason)", never as 0/default; the verdict is then NOT LIVE, because a
                     measurement that was not made must never be presented as one that was
  LIVE / NOT LIVE    the literal verdict: LIVE only when every stage is positively verified and every
                     input was read; NOT LIVE otherwise (dully, the hourly email can grep one token)

The state root is ``$TRADEAI_STATE_ROOT`` when set (the incident timers set it), default unchanged.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_STATE = Path.home() / "trade-ai-releases" / "persistent-state"
CONFIG = Path(__file__).resolve().parents[1] / "config" / "incident_runbook_actions.json"
CAP_SKIP = "daily model-call cap"
# A cycle that skipped incidents because the triage itself failed is not a working cycle.
# scripts/lib/incident_supervisor.py records these as skipped[*].why alongside the cap.
FAIL_SKIPS = frozenset({"model_error", "unparseable"})
WATCHER_FRESH_MIN = 15.0
# The supervisor timer is *:2/10 (config/systemd/incidents/tradeai-incident-supervisor.timer),
# so three missed cycles is stale. A long fixer dispatch can legitimately outlive one tick; the
# direction of that error is NOT LIVE, never a false LIVE.
SUPERVISOR_FRESH_MIN = 30.0

SOURCE_FILES = {
    "index": "index.json",
    "supervisor": "supervisor_last.json",
    "watchers": "watchers_last.json",
    "calls": "supervisor_calls.json",
    "policy": "incident_runbook_actions.json",
    "fixer": "self_heal_fixer_state.json",
}


def _ts(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _read(path: Path) -> tuple[dict | None, str | None]:
    """(document, reason-it-could-not-be-read). Never flattens a failure into ``{}``."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{path.name} unreadable: {type(exc).__name__}"
    try:
        doc = json.loads(text)
    except ValueError:
        return None, f"{path.name} unreadable: invalid JSON"
    if not isinstance(doc, dict):
        return None, f"{path.name} unreadable: not a JSON object"
    return doc, None


def _unread_reason(name, doc, required, unread):
    """Why ``doc`` is not a usable document, or None. A missing key is not an empty measurement."""
    if name in unread:
        return unread[name]
    fname = SOURCE_FILES[name]
    if not isinstance(doc, dict):
        return f"{fname} unreadable"
    for key in required:
        if key not in doc:
            return f"{fname} unreadable: missing {key!r}"
    return None


def _age_minutes(stamp, now):
    at = _ts(stamp)
    return None if at is None else (now - at).total_seconds() / 60.0


def _int_or_none(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or DEFAULT_STATE)


def build_block(
    *,
    index: dict,
    supervisor: dict,
    watchers: dict,
    calls: dict,
    policy: dict,
    fixer: dict,
    now: datetime,
    unread: dict[str, str] | None = None,
) -> list[str]:
    """The four pasted lines. Pure: every input is a parsed document, no I/O.

    ``unread`` optionally carries the reader's reason per source; a source whose document is
    missing or malformed without a reason is still rendered unknown, never as a zero.
    """
    unread = unread or {}
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    index_reason = _unread_reason("index", index, ("incidents",), unread)
    if index_reason is None and not isinstance(index.get("incidents"), list):
        index_reason = "index.json unreadable: 'incidents' is not a list"
    supervisor_reason = _unread_reason("supervisor", supervisor, ("as_of",), unread)
    watchers_reason = _unread_reason("watchers", watchers, ("watchers", "as_of"), unread)
    if watchers_reason is None and not isinstance(watchers.get("watchers"), dict):
        watchers_reason = "watchers_last.json unreadable: 'watchers' is not an object"
    calls_reason = _unread_reason("calls", calls, ("count",), unread)
    policy_reason = _unread_reason("policy", policy, ("policy",), unread)
    if policy_reason is None and not isinstance(policy.get("policy"), dict):
        policy_reason = "incident_runbook_actions.json unreadable: 'policy' is not an object"
    fixer_reason = _unread_reason("fixer", fixer, ("jobs",), unread)
    if fixer_reason is None and not isinstance(fixer.get("jobs"), dict):
        fixer_reason = "self_heal_fixer_state.json unreadable: 'jobs' is not an object"

    # ── counts ────────────────────────────────────────────────────────────────────────────────
    if supervisor_reason:
        dispatch_text = "unknown"
    else:
        dispatch_text = str(len(supervisor.get("dispatched") or []))

    if index_reason:
        counts_line = (
            f"detected unknown · dispatched {dispatch_text} · fixed unknown · "
            f"still blocked unknown · unresolved unknown ({index_reason})"
        )
    else:
        records = index.get("incidents") or []
        hour = now - timedelta(hours=1)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        detected = [r for r in records if (_ts(r.get("opened_at")) or epoch) > hour]
        # Only the ledger's fixed status is a repair: a won't-fix closure (status "closed",
        # resolution "wont_fix") also stamps closed_at and must not read as a fix.
        fixed = [
            r
            for r in records
            if r.get("status") == "fixed"
            and any((_ts(r.get(k)) or epoch) > hour for k in ("closed_at", "fixed_at", "resolved_at"))
        ]
        summary = index.get("summary")
        summary = summary if isinstance(summary, dict) else {}
        counts = summary.get("counts")
        counts = counts if isinstance(counts, dict) else {}
        blocked = counts.get("blocked", sum(1 for r in records if r.get("status") == "blocked"))
        unresolved = summary.get("unresolved", sum(1 for r in records if r.get("status") == "open"))
        counts_line = (
            f"detected {len(detected)} (last hour) · dispatched {dispatch_text} · "
            f"fixed {len(fixed)} (last hour) · still blocked {blocked} · unresolved {unresolved}"
        )

    # ── DETECT ───────────────────────────────────────────────────────────────────────────────
    detect_ok = False
    findings_text = "unknown"
    watcher_at_text = "?"
    if watchers_reason:
        detect_part = f"DETECT unknown ({watchers_reason})"
        watchers_line = f"watchers unknown ({watchers_reason})"
    else:
        watcher_rows = watchers.get("watchers") or {}
        watcher_at_text = watchers.get("as_of", "?")
        # incident_watchers.run records a switched-off watcher as {"enabled": False} (no findings,
        # no gap); a watcher that did run carries no "enabled" key at all. A disabled lane never
        # ran, so it is neither "without a gap" nor evidence of health, however fresh the receipt.
        disabled = [name for name, row in watcher_rows.items() if isinstance(row, dict) and row.get("enabled") is False]
        gaps = [
            name
            for name, row in watcher_rows.items()
            if name not in disabled and isinstance(row, dict) and row.get("gap")
        ]
        findings = {
            name: row.get("findings", 0)
            for name, row in watcher_rows.items()
            if isinstance(row, dict) and row.get("findings")
        }
        findings_text = ", ".join(f"{k} {v}" for k, v in sorted(findings.items(), key=lambda kv: -kv[1])) or "none"
        running = len(watcher_rows) - len(gaps) - len(disabled)
        disabled_text = f", {len(disabled)} disabled" if disabled else ""
        watchers_line = (
            f"watchers {watcher_at_text}: {running}/{len(watcher_rows)} "
            f"without a gap{disabled_text}; findings {findings_text}"
        )
        age = _age_minutes(watchers.get("as_of"), now)
        if age is None:
            detect_part = "DETECT unknown (watchers_last.json unreadable: 'as_of' is not a timestamp)"
        elif disabled:
            detect_part = f"DETECT disabled ({len(disabled)} of {len(watcher_rows)} watchers switched off)"
        elif age < 0:
            detect_part = f"DETECT future-dated (watcher receipt {abs(age):.0f} min ahead — clock skew)"
        elif age > WATCHER_FRESH_MIN:
            detect_part = f"DETECT stale (watcher receipt {age:.0f} min old)"
        elif not watcher_rows:
            detect_part = "DETECT unknown (watchers_last.json has no watchers)"
        elif gaps:
            detect_part = f"DETECT gapped ({len(gaps)} watcher(s) with a gap)"
        else:
            detect_ok = True
            detect_part = "DETECT alive"

    # ── DECIDE ───────────────────────────────────────────────────────────────────────────────
    decide_ok = False
    skipped = [] if supervisor_reason else (supervisor.get("skipped") or [])
    cap_skips = sum(1 for s in skipped if isinstance(s, dict) and s.get("why") == CAP_SKIP)
    failed_skips = sum(1 for s in skipped if isinstance(s, dict) and s.get("why") in FAIL_SKIPS)
    # cx-openai D52 refresh at 749c8a216 (the ONE remaining item): a runbook action that exited non-zero is a FAILED
    # repair, and the supervisor still writes its cycle receipt. DECIDE looked only at skips and at the FIX queue, so a
    # failed repair with an empty queue could publish LIVE. A non-zero action rc is evidence the self-healing did not do
    # its job, and it outranks the freshness checks for the same reason a stale receipt does.
    failed_actions = [
        a for a in (supervisor.get("actions") or [])
        if isinstance(a, dict) and _int_or_none(a.get("rc")) not in (None, 0)
    ]
    # cx-openai D52 KEEP_BLOCK at 3e4091ca1 (the ONE remaining item): the supervisor also records the rc of each
    # DISPATCH it handed to an agent (``dispatched[*].rc``), and DECIDE never read it. A fresh receipt with a failed
    # dispatch, no skips, no actions and an empty fixer queue published "LIVE / FIX no queue" -- a failed repair
    # reading as a healthy lane. An explicit non-zero rc is a failed dispatch; a missing rc is unknown, not zero.
    failed_dispatches = [
        d for d in (supervisor.get("dispatched") or [])
        if isinstance(d, dict) and _int_or_none(d.get("rc")) not in (None, 0)
    ]
    if supervisor_reason:
        decide_part = f"DECIDE unknown ({supervisor_reason})"
        supervisor_line = None
    else:
        age = _age_minutes(supervisor.get("as_of"), now)
        if age is None:
            decide_part = "DECIDE unknown (supervisor_last.json unreadable: 'as_of' is not a timestamp)"
        elif age < 0:
            decide_part = f"DECIDE future-dated (supervisor receipt {abs(age):.0f} min ahead — clock skew)"
        elif age > SUPERVISOR_FRESH_MIN:
            decide_part = f"DECIDE stale (supervisor receipt {age:.0f} min old)"
        elif failed_actions:
            decide_part = (f"DECIDE failing ({len(failed_actions)} of {len(supervisor.get('actions') or [])} "
                           f"action(s) exited non-zero)")
        elif failed_dispatches:
            decide_part = (f"DECIDE failing ({len(failed_dispatches)} of "
                           f"{len(supervisor.get('dispatched') or [])} dispatch(es) exited non-zero)")
        elif failed_skips:
            decide_part = f"DECIDE failing ({failed_skips} of {len(skipped)} skipped on a failed triage)"
        elif skipped and cap_skips == len(skipped):
            decide_part = f"DECIDE starved by the {CAP_SKIP}"
        else:
            decide_ok = True
            decide_part = "DECIDE working"
        supervisor_line = (
            f"supervisor {supervisor.get('as_of', '?')}: "
            f"considered {len(supervisor.get('considered') or [])}, "
            f"actions {len(supervisor.get('actions') or [])}, "
            f"dispatched {len(supervisor.get('dispatched') or [])}, "
            f"skipped {len(skipped)} ({cap_skips} on {CAP_SKIP})"
        )

    # ── model-call cap (display; an unread config is never replaced by the literal 40) ──────
    calls_text = "unknown"
    day_cap_text = "unknown"
    if calls_reason is None:
        count = _int_or_none(calls.get("count"))
        if count is None:
            calls_reason = "supervisor_calls.json unreadable: 'count' is not an integer"
        elif calls.get("date") != now.astimezone(timezone.utc).date().isoformat():
            # Same rollover as incident_supervisor._calls_today: a counter from another UTC day
            # is not today's usage, whatever it says.
            calls_text = "0"
        else:
            calls_text = str(count)
    if policy_reason is None:
        cap = _int_or_none((policy.get("policy") or {}).get("max_model_calls_per_day"))
        if cap is None:
            policy_reason = "incident_runbook_actions.json unreadable: missing policy.max_model_calls_per_day"
        else:
            day_cap_text = str(cap)

    # ── FIX ─────────────────────────────────────────────────────────────────────────────────
    fix_ok = False
    if fixer_reason:
        fix_part = f"FIX unknown ({fixer_reason})"
    else:
        queued = sum(
            1
            for job in (fixer.get("jobs") or {}).values()
            if isinstance(job, dict) and job.get("state") == "fix_requested"
        )
        fix_ok = queued == 0
        fix_part = "FIX no queue" if queued == 0 else f"FIX not scheduled ({queued} requests queued)"

    if supervisor_line is None:
        tail_reasons = [r for r in (calls_reason, policy_reason) if r]
        tail = f" ({'; '.join(tail_reasons)})" if tail_reasons else ""
        supervisor_line = (
            f"supervisor unknown ({supervisor_reason}); model calls today {calls_text}/{day_cap_text}{tail}"
        )
    else:
        tail_reasons = [r for r in (calls_reason, policy_reason) if r]
        tail = f" ({'; '.join(tail_reasons)})" if tail_reasons else ""
        supervisor_line += f"; model calls today {calls_text}/{day_cap_text}{tail}"

    # ── verdict ─────────────────────────────────────────────────────────────────────────────
    # The index, the call counter and the runbook config are not stage predicates, but a store
    # that was not read is still an unknown measurement: it appears as a DATA component and
    # keeps the verdict off LIVE.
    data_reasons = [r for r in (index_reason, calls_reason, policy_reason) if r]
    parts = [detect_part, decide_part, fix_part]
    if data_reasons:
        parts.append(f"DATA unknown ({'; '.join(data_reasons)})")
    alive = detect_ok and decide_ok and fix_ok and not data_reasons
    verdict = ("LIVE" if alive else "NOT LIVE") + " — " + " · ".join(parts)

    return [
        f"SELF-HEAL · {now:%H:%M} UTC",
        counts_line,
        supervisor_line,
        watchers_line,
        f"verdict: {verdict}",
    ]


def main(argv=None) -> int:
    now = datetime.now(timezone.utc)
    root = _state_root()
    incidents = root / "data" / "coordination" / "incidents"
    runtime = root / "data" / "runtime"
    sources = {
        "index": _read(incidents / "index.json"),
        "supervisor": _read(incidents / "supervisor_last.json"),
        "watchers": _read(incidents / "watchers_last.json"),
        "calls": _read(incidents / "supervisor_calls.json"),
        "policy": _read(CONFIG),
        "fixer": _read(runtime / "self_heal_fixer_state.json"),
    }
    documents = {name: doc for name, (doc, _reason) in sources.items()}
    unread = {name: reason for name, (_doc, reason) in sources.items() if reason}
    block = build_block(**documents, now=now, unread=unread)
    print("\n".join(block))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

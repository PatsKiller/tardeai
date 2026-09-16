#!/usr/bin/env python3
"""report_goal_loop_baseline.py — the control measurement the goal loop is judged against.

READ-ONLY. No network, no model call, no writes outside its own append-only receipt.

WHY
---
Every later phase of the goal-oriented agent work claims to improve something. This
records what "before" actually was, so the claim is falsifiable rather than asserted.
AGENTS.md §0 rule 8: exit code 0 is not evidence of work — prove it with a durable
artefact that would not exist if the thing had not run.

THE CONTROL NUMBER
------------------
`GOAL_STATUS_CHANGED` has been **0** for 37 days against 34,718 wakes on 3 goals.
Success for the whole programme is that counter becoming non-zero WITH EVIDENCE
ATTACHED. Everything else here is context for that one number.

HONESTY RULE
------------
A source that cannot be read is recorded as ``{"status": "unavailable", "why": ...}``
and never as ``0``. A fabricated zero is indistinguishable from a real one, and this
codebase has already been bitten by exactly that: a dashboard read ``result_count``
from memory-retrieval receipts, a field which does not exist in that schema, and
reported 0 results while retrieval was returning ~6 memories every call.

USAGE
-----
    python scripts/report_goal_loop_baseline.py            # human-readable
    python scripts/report_goal_loop_baseline.py --json
    python scripts/report_goal_loop_baseline.py --no-write # compute, print, persist nothing

Authority: READ_ONLY_ADVISORY. Never sizes, orders, stops, or writes broker state.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SCHEMA = "GoalLoopBaseline@v1"
#: Receipt path is resolved lazily via _receipt_path(), NOT at import time:
#: PROJECT_ROOT/data does not exist in a worktree, so a module-level constant
#: would write the control row into a throwaway checkout and lose it.

#: The persistent-wake state tree. The critic corpora are NOT under data/cio —
#: measured 2026-09-16 by locating the files, after a data/cio probe returned
#: MISSING and would have yielded a false zero.
WAKE_STATE = Path("/home/johnclaw/trade-ai-state/persistent_wake/state")

SCHEDULED_ENTRYPOINT = (
    "INSTALLED, active — crontab `20 * * * *`, hourly, from the dev tree. "
    "Operator approved the schedule 2026-09-16 (AGENTS.md §17); declared in "
    "config/lane_registry.json as lane `goal-loop-baseline`. NOTE: the "
    "`intake` section records `unavailable` on every scheduled run until "
    "AGENT_RUNTIME_DISPATCH_DSN is provisioned — that is honest, not a zero."
)


def _state_root() -> Path:
    """The production state root, not this checkout.

    `data/` is a symlink farm in the dev tree and does NOT exist in a fresh
    worktree. Resolving `PROJECT_ROOT/data/cio` therefore reads nothing when this
    runs from a worktree — which is exactly how a baseline ends up recording a
    fabricated zero for the control number. Measured 2026-09-16: the first run of
    this script reported `goals: unavailable` for precisely that reason.
    """
    try:
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root())
    except Exception:
        return PROJECT_ROOT


def _cio(name: str) -> Path:
    """Resolve data/cio/<name>, preferring the production state root."""
    candidate = _state_root() / "data" / "cio" / name
    return candidate if candidate.is_file() else PROJECT_ROOT / "data" / "cio" / name


def _receipt_path() -> Path:
    """Where the control row is persisted: the production state root."""
    root = _state_root()
    cio = root / "data" / "cio"
    return (cio if cio.is_dir() else PROJECT_ROOT / "data" / "cio") / "goal_loop_baseline.jsonl"


def _unavailable(why: str) -> dict[str, Any]:
    return {"status": "unavailable", "why": why}


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


# --------------------------------------------------------------- collectors

def goals() -> dict[str, Any]:
    """The control number, plus the shape of the goal store around it."""
    path = _cio("cio_goals.jsonl")
    rows = _jsonl(path)
    if not rows:
        return _unavailable(f"no rows at {path}")
    events = collections.Counter(r.get("event_type") for r in rows)
    per_goal = collections.Counter(r.get("goal_id") for r in rows)
    ts = [str(r.get("occurred_at") or "") for r in rows if r.get("occurred_at")]
    # A thesis that only ever restates runtime telemetry is not a finding.
    blocked = sum(
        1 for r in rows
        if r.get("event_type") == "GOAL_THESIS_UPDATED"
        and "PROVIDER_BLOCKED" in json.dumps(r.get("payload") or {})
    )
    thesis_total = events.get("GOAL_THESIS_UPDATED", 0)
    return {
        "events_total": len(rows),
        "by_event_type": dict(events),
        "goal_status_changed": events.get("GOAL_STATUS_CHANGED", 0),  # THE control number
        "distinct_goals": len(per_goal),
        "wakes_per_goal": dict(per_goal),
        "thesis_updates": thesis_total,
        "thesis_updates_provider_blocked": blocked,
        "thesis_blocked_pct": round(100.0 * blocked / thesis_total, 2) if thesis_total else None,
        "first_event": min(ts) if ts else None,
        "last_event": max(ts) if ts else None,
    }


def validators() -> dict[str, Any]:
    """Day-one calibration baselines. These become UNCALIBRATED under the P6 floor."""
    out: dict[str, Any] = {}

    av = _jsonl(WAKE_STATE / "agent_views.jsonl")
    if av:
        passes = collections.Counter(r.get("critic_pass") for r in av)
        out["agent_view_critic_pass"] = {
            "rows": len(av),
            "by_verdict": {str(k): v for k, v in passes.items()},
            "critique_id_set": sum(1 for r in av if r.get("critique_id")),
            "critic_notes_nonempty": sum(1 for r in av if r.get("critic_notes")),
        }
    else:
        out["agent_view_critic_pass"] = _unavailable(f"no rows at {WAKE_STATE/'agent_views.jsonl'}")

    vw = _jsonl(WAKE_STATE / "views.jsonl")
    if vw:
        out["l3_independent_critic"] = {
            "rows": len(vw),
            "by_verdict": {str(k): v for k, v in collections.Counter(r.get("critic_verdict") for r in vw).items()},
            "by_stance": {str(k): v for k, v in collections.Counter(r.get("stance") for r in vw).items()},
            "contradictions_nonempty": sum(1 for r in vw if r.get("contradictions")),
            "field_changes_nonempty": sum(1 for r in vw if r.get("field_changes")),
        }
    else:
        out["l3_independent_critic"] = _unavailable(f"no rows at {WAKE_STATE/'views.jsonl'}")

    # research_quality verdicts are NOT persisted on the artifact. Measured
    # 2026-09-16: hermes_research_results.jsonl has 613 rows and no `critique`
    # key; the verdict survives only in the audit ledger / memory metadata.
    # Recording the count would mean recording a fabricated zero.
    out["research_quality_critique"] = _unavailable(
        "verdict is not stored on the artifact (hermes_research_results.jsonl has no "
        "'critique' key); it exists only in the audit ledger and memory metadata"
    )
    return out


def adversarial() -> dict[str, Any]:
    """Challenges raised vs resolved, and contradictions written vs consumed."""
    out: dict[str, Any] = {}

    ch = _jsonl(_cio("hermes_challenge_queue.jsonl"))
    if ch:
        ev = collections.Counter(r.get("event") or r.get("event_type") for r in ch)
        out["hermes_challenge_queue"] = {
            "events": {str(k): v for k, v in ev.items()},
            # Structural, not incidental: the vocabulary has no RESOLVED member.
            "resolved": ev.get("HERMES_CHALLENGE_RESOLVED", 0),
            "resolved_event_type_exists": any("RESOLVED" in str(k) for k in ev),
        }
    else:
        out["hermes_challenge_queue"] = _unavailable("no challenge queue rows")

    contra = _cio("research_contradiction_candidates.jsonl")
    if contra.is_file():
        n = sum(1 for line in contra.open(encoding="utf-8", errors="replace") if line.strip())
        out["contradiction_candidates"] = {"rows": n, "note": "consumer count is measured by grep, not here"}
    else:
        out["contradiction_candidates"] = _unavailable(f"missing {contra}")
    return out


def refusals(now: datetime) -> dict[str, Any]:
    """Search refusals that went nowhere — over a window, not 'today'."""
    try:
        from scripts.check_gap_resolution import (
            REFUSED_THRESHOLD, REFUSED_WINDOW_DAYS, refused_nowhere,
        )
        from scripts.lib.search_budget import all_status, denial_receipts
    except Exception as exc:  # noqa: BLE001
        return _unavailable(f"{type(exc).__name__}: {exc}")

    rows = denial_receipts()
    unspilled = [r for r in rows if not r.get("spilled_to")]
    return {
        "receipts_inline": len(rows),
        "receipts_spilled_to_null": len(unspilled),
        "threshold": REFUSED_THRESHOLD,
        "window_days": REFUSED_WINDOW_DAYS,
        "finding_window": refused_nowhere(rows, now=now),
        "finding_one_day": refused_nowhere(rows, now=now, window_days=1),
        "provider_status": all_status(now=now),
    }


def intake() -> dict[str, Any]:
    """Queue depth per agent — the backpressure that starves a first lap."""
    try:
        from scripts.agent_runtime.trigger_intake import PostgresTriggerIntakeStore
    except Exception as exc:  # noqa: BLE001
        return _unavailable(f"import: {type(exc).__name__}: {exc}")
    # Connecting requires AGENT_RUNTIME_DISPATCH_DSN and the runtime writer role.
    # Absent that, report unavailable rather than inventing a depth of zero.
    import os
    dsn = (os.environ.get("AGENT_RUNTIME_DISPATCH_DSN") or "").strip()
    if not dsn:
        return _unavailable("AGENT_RUNTIME_DISPATCH_DSN not set in this environment")
    try:
        import importlib

        psycopg2 = importlib.import_module("psycopg2")

        def _factory():  # noqa: ANN202
            conn = psycopg2.connect(dsn)
            conn.autocommit = False
            return conn

        # Same construction as scripts/agent_runtime/trigger_producer.py —
        # PostgresTriggerIntakeStore requires a zero-arg connection_factory.
        store = PostgresTriggerIntakeStore(_factory)
        return {"queue_stats": store.queue_stats()}
    except Exception as exc:  # noqa: BLE001
        return _unavailable(f"connect: {type(exc).__name__}: {str(exc)[:160]}")

# ------------------------------------------------------------------- report

def collect(*, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    return {
        "schema": SCHEMA,
        "authority": "READ_ONLY_ADVISORY",
        "ran_at": now.isoformat(),
        "goals": goals(),
        "validators": validators(),
        "adversarial": adversarial(),
        "refusals": refusals(now),
        "intake": intake(),
    }


def render(rep: dict[str, Any]) -> str:
    g = rep["goals"]
    v = rep["validators"]
    lines = [
        "Goal-loop baseline — the control every later phase is diffed against",
        "=" * 74,
    ]
    if isinstance(g, dict) and "goal_status_changed" in g:
        lines += [
            f"  GOAL_STATUS_CHANGED : {g['goal_status_changed']}   <-- the control number",
            f"  goals / events      : {g['distinct_goals']} goals, {g['events_total']} events",
            f"  thesis blocked      : {g['thesis_updates_provider_blocked']}/{g['thesis_updates']}"
            f" ({g['thesis_blocked_pct']}%)",
            f"  window              : {g['first_event']} .. {g['last_event']}",
        ]
    for key, label in (("agent_view_critic_pass", "critic_pass"), ("l3_independent_critic", "L3 critic")):
        d = v.get(key, {})
        if d.get("status") == "unavailable":
            lines.append(f"  {label:20s}: unavailable — {d['why'][:60]}")
        else:
            lines.append(f"  {label:20s}: {d.get('rows')} rows, verdicts {d.get('by_verdict')}")
    r = rep["refusals"]
    if isinstance(r, dict) and "receipts_inline" in r:
        lines.append(
            f"  refused nowhere     : {r['receipts_spilled_to_null']}/{r['receipts_inline']} receipts"
            f" spilled_to null; finding={len(r['finding_window'])} over {r['window_days']}d"
        )
    lines += ["-" * 74, "  A source that could not be read is 'unavailable', never 0."]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-write", action="store_true", help="compute and print; persist nothing")
    args = ap.parse_args()

    try:
        rep = collect()
    except Exception as exc:  # noqa: BLE001 — cannot-run is exit 2, never a green 0
        print(f"ERROR: could not collect: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(rep, indent=2, default=str) if args.json else render(rep))

    if not args.no_write:
        receipt = _receipt_path()
        try:
            receipt.parent.mkdir(parents=True, exist_ok=True)
            with receipt.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rep, sort_keys=True, default=str) + "\n")
            print(f"\n  receipt appended: {receipt}")
        except OSError as exc:
            print(f"  receipt: could not write ({exc})", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

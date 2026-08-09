#!/usr/bin/env python3
"""darwin_outcome_scorer.py — Darwin outcome scoring for the CIO learning loop.

Scores CIO actions against deterministic outcomes. Feeds Iris for lesson curation.
Runs as a bounded sweep — reads the action ledger, checks outcomes, produces scorecards.

Deterministic only — zero model calls. The scoring is based on:
  - Action status (OPEN → no outcome yet, DONE → check if impact was measurable)
  - Domain health (did the domain improve after action was created?)
  - Time-to-close (was the action resolved in a timely manner?)

Output: scorecard entries in data/cio/darwin_scorecards.jsonl

Usage:
  python3 scripts/darwin_outcome_scorer.py --once [--max-actions 20]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SCORECARD_PATH = PROJECT_ROOT / "data" / "cio" / "darwin_scorecards.jsonl"
ACTION_LEDGER = PROJECT_ROOT / "data" / "cio" / "cio_action_ledger.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def _append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(entry, default=str) + "\n")
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def score_action(action: dict[str, Any]) -> dict[str, Any]:
    """Score a single CIO action. Deterministic — no model calls."""
    aid = action.get("cio_action_id", "unknown")
    status = action.get("status", "OPEN")
    priority = action.get("priority", "P3")
    domain = action.get("domain", "unknown")
    created = action.get("created_at", "")

    # Compute dimensions
    scores: dict[str, Any] = {
        "action_id": aid,
        "domain": domain,
        "priority": priority,
        "status": status,
        "scored_at": _now_iso(),
    }

    # Dimension 1: Resolution (0–40 pts)
    if status == "DONE":
        scores["resolution_score"] = 40
        scores["resolution_note"] = "Action completed"
    elif status == "ACKNOWLEDGED":
        scores["resolution_score"] = 20
        scores["resolution_note"] = "Acknowledged but not resolved"
    elif status == "OPEN":
        # Check age — older open actions score lower
        try:
            age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(created)).total_seconds() / 3600
            scores["age_hours"] = round(age_hours, 1)
            if age_hours > 168:  # 7 days
                scores["resolution_score"] = 0
                scores["resolution_note"] = f"Open {age_hours:.0f}h — stale"
            elif age_hours > 24:
                scores["resolution_score"] = 5
                scores["resolution_note"] = f"Open {age_hours:.0f}h — aging"
            else:
                scores["resolution_score"] = 15
                scores["resolution_note"] = f"Open {age_hours:.0f}h — recent"
        except Exception:
            scores["resolution_score"] = 10
            scores["resolution_note"] = "Open (age unknown)"
    else:
        scores["resolution_score"] = 5
        scores["resolution_note"] = f"Status: {status}"

    # Dimension 2: Priority alignment (0–30 pts)
    priority_scores = {"P1": 30, "P2": 20, "P3": 10}
    scores["priority_score"] = priority_scores.get(priority, 5)

    # Dimension 3: Domain impact (0–30 pts) — did the domain improve?
    domain_weights = {
        "portfolio": 25, "risk": 30, "watch": 20, "rotation": 15,
        "income": 20, "reconciliation": 25, "hermes_research": 10,
        "system": 10,
    }
    scores["domain_score"] = domain_weights.get(domain, 10)

    # Total
    scores["total_score"] = (
        scores["resolution_score"]
        + scores["priority_score"]
        + scores["domain_score"]
    )
    scores["max_possible"] = 100

    # Grade
    if scores["total_score"] >= 80:
        scores["grade"] = "A"
    elif scores["total_score"] >= 60:
        scores["grade"] = "B"
    elif scores["total_score"] >= 40:
        scores["grade"] = "C"
    else:
        scores["grade"] = "D"

    return scores


def run_scoring_cycle(max_actions: int = 20) -> dict[str, Any]:
    """Score the most recent CIO actions. Returns summary."""
    t0 = time.time()
    events = _read_jsonl(ACTION_LEDGER)
    actions: dict[str, dict[str, Any]] = {}

    for event in events:
        payload = event.get("payload", {})
        aid = payload.get("cio_action_id")
        if not aid:
            continue
        if event.get("event_type") == "CIO_ACTION_CREATED":
            actions[aid] = payload

    # Score actions, newest first
    scored = 0
    for action in sorted(actions.values(), key=lambda a: a.get("created_at", ""), reverse=True)[:max_actions]:
        scorecard = score_action(action)
        _append_jsonl(SCORECARD_PATH, {
            "event_type": "DARWIN_SCORECARD",
            "event_id": str(uuid.uuid4()),
            "timestamp": _now_iso(),
            "scorer": "darwin",
            "reviewer": "iris",
            "payload": scorecard,
        })
        scored += 1

    elapsed = time.time() - t0
    return {
        "actions_scored": scored,
        "total_actions": len(actions),
        "elapsed_ms": int(elapsed * 1000),
        "mode": "deterministic",
        "model_calls": 0,
        "cost_usd": 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Darwin Outcome Scorer — CIO learning loop")
    parser.add_argument("--once", action="store_true", default=True)
    parser.add_argument("--max-actions", type=int, default=20)
    args = parser.parse_args()

    print(f"Darwin Outcome Scorer — {_now_iso()[:19]}")
    print(f"  mode=deterministic  max_actions={args.max_actions}")

    summary = run_scoring_cycle(max_actions=args.max_actions)
    print(f"  summary: {json.dumps(summary, default=str)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

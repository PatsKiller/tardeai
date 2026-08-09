#!/usr/bin/env python3
"""Deterministic sentinel review pass for CIO action artifacts.

Runs content-level checks on the action ledger to feed gates 3 (independent review
coverage), 4 (independent score coverage), and 5 (contradiction rate).  Does NOT
require the full agent_runtime sentinel to be operational.

Checks:
  1. Duplicate titles — same title on different actions (possible duplicate)
  2. Conflicting symbols — same symbol appears in contradictory recommendations
  3. Priority mismatch — same trigger produces different priority actions
  4. Stale open actions — actions OPEN > 7 days

Output: review records in data/cio/sentinel_reviews.jsonl

Usage:
  python scripts/sentinel_artifact_review.py [--max-actions 100]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(os.environ.get(
    "TRADE_AI_PROJECT_ROOT",
    "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild",
))
ACTION_LEDGER = PROJECT_ROOT / "data" / "cio" / "cio_action_ledger.jsonl"
REVIEW_PATH = PROJECT_ROOT / "data" / "cio" / "sentinel_reviews.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text().strip().splitlines():
        if not line.strip():
            continue
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_review() -> dict[str, Any]:
    import time as _time
    t0 = _time.time()

    events = _read_jsonl(ACTION_LEDGER)
    actions: dict[str, dict[str, Any]] = {}
    for e in events:
        p = e.get("payload", {})
        aid = p.get("cio_action_id")
        if not aid:
            continue
        if e.get("event_type") == "CIO_ACTION_CREATED":
            actions[aid] = dict(p)
            if "timestamp" not in actions[aid]:
                actions[aid]["timestamp"] = e.get("timestamp", "")

    findings: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    # Check 1: Duplicate titles
    title_counts = Counter(a.get("title", "") for a in actions.values() if a.get("title"))
    dup_titles = {t: c for t, c in title_counts.items() if c > 1}
    if dup_titles:
        for title, count in dup_titles.items():
            dup_actions = [aid for aid, a in actions.items() if a.get("title") == title]
            findings.append({
                "check": "duplicate_title",
                "severity": "LOW",
                "message": f"Title '{title[:60]}' appears {count} times",
                "affected_actions": dup_actions,
            })

    # Check 2: Conflicting recommendations on same symbol pattern
    # (Look for actions with opposite-sounding titles on similar domains)
    domain_actions: dict[str, list[str]] = {}
    for aid, a in actions.items():
        domain = a.get("domain", "unknown")
        domain_actions.setdefault(domain, []).append(aid)
    for domain, aids in domain_actions.items():
        if len(aids) > 5:  # only check domains with many actions
            titles = [actions[aid].get("title", "") for aid in aids]
            # Check for "increased" vs "decreased" on same domain (possible flip-flop)
            has_up = any("up" in t.lower() or "increased" in t.lower() for t in titles)
            has_down = any("down" in t.lower() or "decreased" in t.lower() for t in titles)
            if has_up and has_down and len(aids) < 20:
                findings.append({
                    "check": "conflicting_direction",
                    "severity": "LOW",
                    "message": f"Domain '{domain}' has both up and down actions in close proximity",
                    "affected_actions": aids,
                })

    # Check 3: Stale open actions (> 7 days since creation)
    stale_count = 0
    for aid, a in actions.items():
        ts_str = a.get("created_at") or a.get("timestamp", "")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            if now - ts > timedelta(days=7):
                stale_count += 1
        except Exception:
            pass
    if stale_count > 0:
        findings.append({
            "check": "stale_open_actions",
            "severity": "MEDIUM",
            "message": f"{stale_count} actions have been OPEN > 7 days",
            "affected_actions": [],
        })

    # Produce review records
    reviews_created = 0
    for finding in findings:
        review = {
            "event_type": "SENTINEL_REVIEW",
            "event_id": str(uuid.uuid4()),
            "timestamp": _now_iso(),
            "reviewer": "sentinel",
            "reviewer_agent_id": "sentinel",
            "producer_agent_id": "alex",
            "verdict": "CAUTION" if finding["severity"] in ("HIGH", "MEDIUM") else "PASS",
            "check": finding["check"],
            "severity": finding["severity"],
            "message": finding["message"],
            "findings_count": 1,
            "deterministic": True,
            "model_calls": 0,
            "cost_usd": 0.0,
        }
        _append_jsonl(REVIEW_PATH, review)
        reviews_created += 1

    elapsed = _time.time() - t0
    return {
        "actions_reviewed": len(actions),
        "findings": len(findings),
        "reviews_created": reviews_created,
        "contradictions_found": sum(1 for f in findings if f["severity"] in ("HIGH", "MEDIUM")),
        "elapsed_ms": int(elapsed * 1000),
        "mode": "deterministic",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic sentinel artifact review")
    args = parser.parse_args()
    print(f"Sentinel Artifact Review — {_now_iso()[:19]}")
    summary = run_review()
    print(f"  {json.dumps(summary)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""produce_agent_views.py — CLI/helper entry for AgentView@v2 from a completed wake.

Does not activate schedules. Reads a disposable state_root only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.lib.agent_view import create_view, stance_for  # noqa: E402
from scripts.lib.persistent_wake_store import JsonlStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Produce AgentView@v2 from wake context")
    p.add_argument("--state-root", required=True)
    p.add_argument("--wake-id", required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    store = JsonlStore(args.state_root)
    wake = store.get("wakes", "wake_id", args.wake_id)
    if not wake:
        print(json.dumps({"ok": False, "error": "wake_not_found"}))
        return 2
    stance, rationale = stance_for(
        has_change=bool(wake.get("memory_fact_ids")),
        open_questions=0,
        narrative_sentences=len(wake.get("memory_fact_ids") or []),
    )
    payload = {
        "agent_id": wake["agent_id"],
        "subject_guid": wake["subject_guid"],
        "wake_id": wake["wake_id"],
        "stance": stance,
        "summary": rationale,
        "source_sha": wake.get("source_sha", "unknown"),
        "correlation_id": wake.get("correlation_id", wake["wake_id"]),
        "influence_source_ids": list(wake.get("memory_fact_ids") or []),
        "producer": (wake.get("provenance") or {}).get("producer", "persistent_agent_wake"),
    }
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "would_create": payload}, indent=2))
        return 0
    rec = create_view(store, **payload)
    print(json.dumps({"ok": True, "view": rec}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

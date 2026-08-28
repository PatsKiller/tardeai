#!/usr/bin/env python3
"""Build lesson candidates from recorded outcomes.

    python scripts/build_lesson_candidates.py            # dry run
    python scripts/build_lesson_candidates.py --json
    python scripts/build_lesson_candidates.py --apply

The lesson lane holds 1,617 lessons and 1,467 applications and **none of them
references an outcome** — they come from the advisory knowledge base, so the
system has been learning from something other than its own recorded results.
This is the missing link between `OutcomeObservation@v1` and
`LessonCandidate@v2`.

Candidates only. Nothing here ratifies a lesson or influences behaviour;
`memory_behavior_influence` stays 0.

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

SCHEDULED_ENTRYPOINT = (
    'cron: 40 6 * * * -- daily 06:40, --apply (wired 2026-08-27, Phase 2)'
)

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cio_institutional_learning import OBSERVATION_PATH, _append, _jsonl  # noqa: E402
from scripts.lib.outcome_to_lesson import build_candidates  # noqa: E402

LESSON_CANDIDATE_PATH = "data/cio/lesson_candidates.jsonl"


def _state_root() -> Path:
    from scripts.lib.canonical_store_registry import production_state_root
    return Path(production_state_root())


def run(apply: bool = False) -> dict[str, Any]:
    root = _state_root()
    observations = _jsonl(root / OBSERVATION_PATH)
    # The whole corpus is scanned, so counterexample search is genuinely done.
    candidates = build_candidates(observations, searched_counterexamples=True)
    case_n_before = len(candidates)
    try:
        from scripts.lib.agent_durable_memory import get_durable_provider
        from scripts.lib.outcome_to_lesson import candidates_from_case_summaries
        mems = list((get_durable_provider(root)._store or {}).values())
        case_cands = candidates_from_case_summaries(mems)
        existing_keys = {
            (c.get("scope"), c.get("plan_id"), c.get("hermes_result_id"))
            for c in candidates
        }
        for c in case_cands:
            key = (c.get("scope"), c.get("plan_id"), c.get("hermes_result_id"))
            if key in existing_keys:
                continue
            candidates.append(c)
            existing_keys.add(key)
        case_added = len(candidates) - case_n_before
    except Exception:
        case_added = 0

    path = root / LESSON_CANDIDATE_PATH
    existing = {str(r.get("lesson_id")) for r in _jsonl(path)}
    written = 0
    if apply:
        for candidate in candidates:
            if str(candidate.get("lesson_id")) in existing:
                continue
            _append(path, candidate)
            written += 1

    return {
        "schema": "LessonCandidateBuild@v1",
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
        "memory_behavior_influence": 0,
        "applied": bool(apply),
        "observations_read": len(observations),
        "candidates": len(candidates),
        "case_summary_support_added": case_added,
        "written": written,
        "path": str(path),
        "detail": [
            {
                "lesson_id": c.get("lesson_id"),
                "scope": c.get("scope"),
                "task_class": c.get("task_class"),
                "status": c.get("status"),
                "independent_samples": c.get("independent_samples"),
                "total_observations": c.get("total_observations"),
                "statement": c.get("statement"),
            }
            for c in candidates
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build lesson candidates from outcomes")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = run(apply=args.apply)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        for key in ("observations_read", "candidates", "case_summary_support_added", "written", "applied"):
            print(f"{key:20} {result[key]}")
        for d in result["detail"]:
            print(f"\n  {d['scope']} / {d['task_class']}  [{d['status']}]")
            print(f"    independent samples {d['independent_samples']} "
                  f"of {d['total_observations']} observations")
            print(f"    {d['statement']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

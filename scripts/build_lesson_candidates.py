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

Dry run (n8n refactor wave 3, 2026-10-10): ``--dry-run`` WINS over ``--apply``; no ``--apply`` is still a
dry run. Both read the observation corpus, the durable memory store and the existing candidate file, and
call ``run(apply=False)``, in which ``_append`` is not reachable; the dry run also prints a ``DRY-RUN``
report and writes no receipt.

A REAL (``--apply``) run writes LaneRunReceipt@v1 ``<state_root>/data/runtime/build-lesson-candidates_last.json``
(``ok_at`` only on success). Exit codes: 0 = ran (zero new candidates is a finding, still 0); 1 = the run
failed (an exception, e.g. the append failed, or the observation store
``data/cio/outcome_observations.jsonl`` is missing under the resolved state root -- a mis-resolved root
would otherwise build nothing and look healthy); 2 = usage error.

Log volume: the per-candidate text block is capped at ``--detail-limit`` (default 25; ``-1`` = all).
The uncapped listing grew the cron log to ~6 MB; ``--json`` output is unchanged.
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
from scripts.lib.outcome_to_lesson import (  # noqa: E402
    build_candidates,
    needs_outcome_provenance_amendment,
    provenance_amendment_row,
)

LESSON_CANDIDATE_PATH = "data/cio/lesson_candidates.jsonl"
LANE_ID = "build-lesson-candidates"
DEFAULT_DETAIL_LIMIT = 25


def _receipt_lib():
    from scripts.lib import lane_last_receipt as lr
    return lr


def _state_root() -> Path:
    from scripts.lib.canonical_store_registry import production_state_root
    return Path(production_state_root())


def run(apply: bool = False) -> dict[str, Any]:
    root = _state_root()
    observation_store_present = (root / OBSERVATION_PATH).is_file()
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
    # Last-wins fold so a prior amendment is visible to this run.
    existing_rows: dict[str, dict[str, Any]] = {}
    for row in _jsonl(path):
        lid = str(row.get("lesson_id") or "")
        if lid:
            existing_rows[lid] = row

    written = 0
    amended = 0
    new_candidates = 0  # lesson_ids not yet in the file (what --apply appends)
    would_amend: list[dict[str, Any]] = []
    for candidate in candidates:
        lid = str(candidate.get("lesson_id") or "")
        if not lid:
            continue
        prev = existing_rows.get(lid)
        if prev is None:
            new_candidates += 1
            if apply:
                _append(path, candidate)
                existing_rows[lid] = candidate
                written += 1
            continue
        if needs_outcome_provenance_amendment(prev, candidate):
            amendment = provenance_amendment_row(candidate)
            would_amend.append({
                "lesson_id": lid,
                "scope": candidate.get("scope"),
                "task_class": candidate.get("task_class"),
                "lesson_provenance": amendment.get("lesson_provenance"),
            })
            if apply:
                _append(path, amendment)
                existing_rows[lid] = amendment
                amended += 1

    return {
        "schema": "LessonCandidateBuild@v1",
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
        "memory_behavior_influence": 0,
        "applied": bool(apply),
        "observation_store_present": observation_store_present,
        "observations_read": len(observations),
        "candidates": len(candidates),
        "case_summary_support_added": case_added,
        "new_candidates": new_candidates,
        "written": written,
        "amended": amended if apply else len(would_amend),
        "would_amend": would_amend,
        "path": str(path),
        "detail": [
            {
                "lesson_id": c.get("lesson_id"),
                "scope": c.get("scope"),
                "task_class": c.get("task_class"),
                "status": c.get("status"),
                "lesson_provenance": c.get("lesson_provenance"),
                "independent_samples": c.get("independent_samples"),
                "total_observations": c.get("total_observations"),
                "statement": c.get("statement"),
            }
            for c in candidates
        ],
    }


def _print_text(result: dict[str, Any], detail_limit: int) -> None:
    for key in (
        "observations_read", "candidates", "case_summary_support_added",
        "written", "amended", "applied",
    ):
        print(f"{key:20} {result[key]}")
    for a in result.get("would_amend") or []:
        print(f"  would-amend {a.get('scope')} / {a.get('task_class')}  "
              f"lid={a.get('lesson_id')} → {a.get('lesson_provenance')}")
    details = result["detail"] if detail_limit < 0 else result["detail"][:detail_limit]
    for d in details:
        print(f"\n  {d['scope']} / {d['task_class']}  [{d['status']}]")
        print(f"    independent samples {d['independent_samples']} "
              f"of {d['total_observations']} observations")
        print(f"    provenance={d.get('lesson_provenance')}")
        print(f"    {d['statement']}")
    hidden = len(result["detail"]) - len(details)
    if hidden > 0:
        print(f"\n  (+{hidden} more candidates not listed; --detail-limit -1 lists all)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build lesson candidates from outcomes")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--dry-run", action="store_true", help="never write; wins over --apply")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--detail-limit", type=int, default=DEFAULT_DETAIL_LIMIT,
                    help="candidates listed in text output (default 25; -1 = all)")
    args = ap.parse_args(argv)

    if args.dry_run or not args.apply:
        result = run(apply=False)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True, default=str))
        else:
            _print_text(result, args.detail_limit)
        if args.dry_run:
            _receipt_lib().dry_run_report(
                LANE_ID,
                {"observation_store_present": result["observation_store_present"],
                 "observations_read": result["observations_read"], "candidates": result["candidates"],
                 "would_append_new": result["new_candidates"], "would_amend": result["amended"]},
                would_write=[f"{result['path']} (append) x would_append_new + would_amend"],
            )
        return 0 if result["observation_store_present"] else 1

    lr = _receipt_lib()
    from datetime import datetime, timezone
    started = datetime.now(timezone.utc).isoformat()
    try:
        result = run(apply=True)
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="build_lesson_candidates.py", error=f"{type(exc).__name__}: {exc}")
        raise
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        _print_text(result, args.detail_limit)
    rc = 0 if result["observation_store_present"] else 1
    lr.write_lane_receipt(LANE_ID, ok=rc == 0, exit_code=rc, started_at=started,
                          script="build_lesson_candidates.py",
                          summary={"observation_store_present": result["observation_store_present"],
                                   "observations_read": result["observations_read"],
                                   "candidates": result["candidates"], "written": result["written"],
                                   "amended": result["amended"]})
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

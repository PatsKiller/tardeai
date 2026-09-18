#!/usr/bin/env python3
"""Ratchet: every module that can MINT goal work must be declared.

Measured 2026-09-17/18. `agent_runtime_live_providers.job_source` built goal
`JobRequest`s in-process and never enqueued them, so they reached neither the
intake ON CONFLICT dedup nor `produce_once`'s `gate_candidate`. The module calls
`gate_candidate`/`try_consume_lap`/`goal_budget`/`record_spend` zero times, so
every lap it minted was unbudgeted by construction. It ran at a flat 36 laps an
hour for days: `lap` reached 85, three distinct dedup keys across 184 rows,
184/184 carrying `model_error` with an empty finding, 0/184 closing a need.

Nothing noticed, because nothing was watching for a NEW minter.

This guard cannot decide whether a given minter is correctly budgeted -- that is
a judgement, and `agent_runtime_live_providers` legitimately appends laps while
NOT importing the budget, because the budget binds at the producer where the lap
is AUTHORISED rather than inside the runtime, which runs as the agent. What it
can do is make the SET of minters closed: the inventory is declared, and a
module that starts minting without being added fails the build.

Ratchet only: the baseline may shrink, never silently grow. Regenerate the
declared inventory deliberately with --update-baseline.

AUTHORITY: READ_ONLY_ADVISORY. Static analysis, repo-only inputs, no network,
no database, no subprocess.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIR = ROOT / "scripts"
BASELINE = ROOT / "config" / "goal_work_minter_baseline.json"

SCHEMA = "GoalWorkMinterAudit@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: Functions whose call MINTS a lap or the work item that becomes one.
MINTING_CALLS = frozenset({
    "append_lap",            # writes the lap ledger directly
    "enqueue_goal_lap",      # enqueues one generation of a goal
    "goal_trigger_candidate",  # builds the candidate an enqueue admits
})

#: A JobRequest carrying one of these job types IS goal work, however built.
GOAL_JOB_TYPES = frozenset({"goal_shadow_review"})


def _call_name(node: ast.AST) -> str | None:
    """The bare function name of a call, whether plain or attribute access."""
    if not isinstance(node, ast.Call):
        return None
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return None


def minting_reasons(src: str) -> list[str]:
    """Why this source mints goal work, or an empty list."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return []
    found: set[str] = set()
    for node in ast.walk(tree):
        name = _call_name(node)
        if name in MINTING_CALLS:
            found.add(f"calls {name}()")
        # A JobRequest naming a goal job type mints goal work even if it never
        # touches a helper -- which is exactly how the retired in-process minter
        # was built.
        if name == "JobRequest":
            for kw in getattr(node, "keywords", []):
                if (kw.arg == "job_type" and isinstance(kw.value, ast.Constant)
                        and kw.value.value in GOAL_JOB_TYPES):
                    found.add(f'builds JobRequest(job_type="{kw.value.value}")')
    return sorted(found)


def scan() -> dict[str, list[str]]:
    """Every module under scripts/ that mints goal work, and why."""
    out: dict[str, list[str]] = {}
    for path in sorted(SCAN_DIR.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel == Path(__file__).resolve().relative_to(ROOT).as_posix():
            continue  # the guard names the patterns it hunts
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        reasons = minting_reasons(src)
        if reasons:
            out[rel] = reasons
    return out


def _load_baseline() -> dict | None:
    if not BASELINE.is_file():
        return None
    try:
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--update-baseline", action="store_true",
                    help="record the current inventory as declared debt")
    a = ap.parse_args()

    found = scan()

    if a.update_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps({
            "_note": ("Modules that may MINT goal work. Ratchet only - may shrink, "
                      "never grow silently. A new entry means a new path can create "
                      "a goal lap; confirm it is budgeted before declaring it."),
            "schema": SCHEMA,
            "files": {k: v for k, v in sorted(found.items())},
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[goal-work-minters] baseline updated: {len(found)} modules")
        return 0

    base = _load_baseline()
    if base is None:
        print(f"[goal-work-minters] FAIL: no readable baseline at {BASELINE}. "
              f"Run --update-baseline once to record the current inventory.",
              file=sys.stderr)
        return 1

    declared = set(base.get("files") or {})
    current = set(found)
    new = sorted(current - declared)
    resolved = sorted(declared - current)

    result = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "declared": len(declared),
        "current": len(current),
        "new": {m: found[m] for m in new},
        "resolved_since_baseline": resolved,
    }

    if a.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if new:
            print(f"[goal-work-minters] {len(new)} violation(s): a module mints "
                  f"goal work and is not declared")
            for m in new:
                print(f"    x {m}  ({', '.join(found[m])})")
        else:
            print(f"[goal-work-minters] pass: zero undeclared minters "
                  f"({len(current)} declared)")
        for m in resolved:
            print(f"    v no longer mints: {m}")

    if new:
        print("\nFAIL: a module can now create goal work without being declared.\n"
              "Confirm the lap it mints is BUDGETED (gate_candidate binds at the\n"
              "producer, before the row exists), then record it:\n"
              "    python3 scripts/check_goal_work_minters.py --update-baseline",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

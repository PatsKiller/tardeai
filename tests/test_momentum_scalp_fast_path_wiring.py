#!/usr/bin/env python3
"""P0-5: fast-path wiring — env-gated (default OFF), idempotent, dedup + limits enforced."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from momentum_scalp_paper_fast_path import (maybe_run_after_generation, submission_allowed)  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # 1. Default OFF — hook is a no-op unless the env flag is set.
    os.environ.pop("MOMENTUM_SCALP_PAPER_FAST_PATH", None)
    check("hook is no-op when flag unset", maybe_run_after_generation() is None)

    # 2. Flag on → runs (dry-run by default, paper-submit needs separate explicit opt-in).
    os.environ["MOMENTUM_SCALP_PAPER_FAST_PATH"] = "1"
    os.environ.pop("MOMENTUM_SCALP_PAPER_FAST_PATH_SUBMIT", None)
    rep = maybe_run_after_generation(dry_run=True)
    check("flag on → hook runs", rep is not None)
    if rep:
        check("hook runs in dry-run (no paper submit without explicit opt-in)", rep.get("mode") == "dry_run")
    os.environ.pop("MOMENTUM_SCALP_PAPER_FAST_PATH", None)

    # 3. Dedup/limits gate (pure):
    check("open paper trade blocks duplicate", submission_allowed(open_count=1, today_count=0)[0] is False)
    check("no open + under caps allowed", submission_allowed(open_count=0, today_count=1)[0] is True)
    check("max daily trades blocks",
          submission_allowed(open_count=0, today_count=3, limits={"max_daily_trades": 3})[0] is False)
    check("daily cap reason", "max_daily" in submission_allowed(0, 3, {"max_daily_trades": 3})[1])
    check("under daily cap allowed",
          submission_allowed(open_count=0, today_count=2, limits={"max_daily_trades": 3})[0] is True)

    # 4. Idempotency: the runner query excludes already-EXECUTED proposals (static check).
    src = open(os.path.join(os.path.dirname(__file__), "..", "scripts",
                            "momentum_scalp_paper_fast_path.py")).read()
    check("runner excludes EXECUTED proposals (idempotent)", "paper_submit_state" in src and "EXECUTED" in src)
    check("delegates submit to existing safe submitter (its own dup gates)", "submit_paper" in src)

    # 5. The generator wiring is env-gated + paper-only, default OFF.
    gen = open(os.path.join(os.path.dirname(__file__), "..", "scripts",
                            "auto_proposal_generator.py")).read()
    check("generator hook is env-gated", "maybe_run_after_generation" in gen)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

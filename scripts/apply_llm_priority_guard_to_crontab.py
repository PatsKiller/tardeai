#!/usr/bin/env python3
"""apply_llm_priority_guard_to_crontab.py — tiered-prioritization applier (auditable, reversible).

For every TIER-3 LLM cron job that can fire inside the 06:00-12:00 ET market window, inject the
llm_priority_guard so it DEFERS during that window (freeing the local GPU for T1 scalp/proposal work).
Also closes the Monday proposal-worker gap (`*/5 0-5 * * 2-6` → `1-6`). T1/T2/INFRA jobs are never
touched; the deep-overnight LLM window (22:00-03:00) is untouched. Does NOT change any gate, broker
path, or 2FA. Idempotent — already-guarded lines are skipped.

    python3 scripts/apply_llm_priority_guard_to_crontab.py            # DRY-RUN: show the diff
    python3 scripts/apply_llm_priority_guard_to_crontab.py --apply    # install (backs up first)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from job_schedule_audit import classify, _resource_class, _expand_hours  # noqa: E402

GUARD = "bash $PROJ/scripts/llm_priority_guard.sh &&"
MARKET_HOURS = set(range(6, 12))


def _should_guard(cmd: str, hour_field: str) -> bool:
    tier, llm_now, _ = classify(cmd)
    if tier != "T3":
        return False
    if _resource_class(cmd, llm_now) != "llm":
        return False
    if GUARD in cmd or "llm_priority_guard.sh" in cmd:
        return False                      # already guarded (idempotent)
    if "run_deep_overnight_llm_window" in cmd:
        return False                      # already window-gated to 22:00-03:00
    hours = set(_expand_hours(hour_field))
    # Guard ONLY when the job fires in the market window AND ALSO outside it — so guarding merely
    # trims its in-window ticks and never fully eliminates a job. A job that fires ONLY inside
    # 06:00-12:00 (e.g. a single `0 8` pre-open run) must be RESCHEDULED, not guarded — it is reported
    # as a reschedule candidate instead.
    return bool(hours & MARKET_HOURS) and bool(hours - MARKET_HOURS)


def transform(crontab_text: str) -> tuple[str, list]:
    out, changes = [], []
    for line in crontab_text.splitlines():
        if not line.strip() or line.strip().startswith("#") or re.match(r"^[A-Z_]+=", line):
            out.append(line); continue
        m = re.match(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)$", line)
        if not m:
            out.append(line); continue
        minute, hour, dom, mon, dow, cmd = m.groups()

        # Fix the Monday proposal-worker gap: */5 0-5 * * 2-6 → 1-6 (add Monday overnight coverage).
        if "process_watchlist_agent_jobs.py" in cmd and hour == "0-5" and dow == "2-6":
            new = f"{minute} {hour} {dom} {mon} 1-6 {cmd}"
            out.append(new); changes.append(("worker-gap-fix", line, new)); continue

        # Report T3 LLM jobs that fire ONLY inside the window (need rescheduling, not guarding).
        _tier, _now, _ = classify(cmd)
        if (_tier == "T3" and _resource_class(cmd, _now) == "llm"
                and "llm_priority_guard.sh" not in cmd and "run_deep_overnight" not in cmd):
            _h = set(_expand_hours(hour))
            if (_h & MARKET_HOURS) and not (_h - MARKET_HOURS):
                changes.append(("RESCHEDULE_CANDIDATE", line, ""))

        # Inject the guard for T3 LLM market-window jobs, right after `cd <proj> && `.
        if _should_guard(cmd, hour):
            m2 = re.match(r"^(cd \S+ &&\s+)(.*)$", cmd)
            if m2:
                new_cmd = f"{m2.group(1)}{GUARD} {m2.group(2)}"
                new = f"{minute} {hour} {dom} {mon} {dow} {new_cmd}"
                out.append(new); changes.append(("guard", line, new)); continue
            else:
                changes.append(("SKIPPED_no_cd_anchor", line, ""))  # report, don't mangle
        out.append(line)
    return "\n".join(out) + "\n", changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="install the transformed crontab (backs up first)")
    args = ap.parse_args()

    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    new, changes = transform(current)

    guarded = [c for c in changes if c[0] == "guard"]
    gapfix = [c for c in changes if c[0] == "worker-gap-fix"]
    skipped = [c for c in changes if c[0].startswith("SKIPPED")]
    print(f"T3 LLM jobs to guard (defer 06:00-12:00 ET): {len(guarded)}")
    for _, old, _new in guarded:
        nm = re.search(r"scripts/[\w\-]+\.(py|sh)|run_[\w]+\.sh|linux_launchers/\S+", old)
        print(f"  + guard: {nm.group(0) if nm else old[:60]}")
    print(f"worker-gap fixes: {len(gapfix)}")
    for _, _o, _n in gapfix:
        print("  + Monday overnight proposal worker (0-5 2-6 → 1-6)")
    if skipped:
        print(f"SKIPPED (no `cd` anchor — review manually): {len(skipped)}")
        for _, old, _ in skipped:
            print(f"  ! {old[:80]}")
    resched = [c for c in changes if c[0] == "RESCHEDULE_CANDIDATE"]
    if resched:
        print(f"RESCHEDULE CANDIDATES (T3 LLM firing ONLY in 06-12 — move to a quiet window, NOT guarded): {len(resched)}")
        for _, old, _ in resched:
            nm = re.search(r"scripts/[\w\-]+\.(py|sh)|run_[\w]+\.sh|linux_launchers/\S+", old)
            print(f"  ~ {(nm.group(0) if nm else old[:50])}  [{old.split()[1]}:00]")

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to install (a timestamped backup is written first).")
        return 0
    if not changes:
        print("No changes needed."); return 0

    backup = Path.home() / f".crontab_backup_llm_guard_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup.write_text(current)
    subprocess.run(["crontab", "-"], input=new, text=True, check=True)
    print(f"\nApplied. Backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

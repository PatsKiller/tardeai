#!/usr/bin/env python3
"""Reclaim agent worktrees that are merged and clean. Never the ones holding work.

WHY THIS EXISTS
---------------
Operator, 2026-09-21: "set up a mechanism that's automatic for the retention,
deletion of all of that Claude data or any other agent data."

WHAT THE DATA SAYS (measured 2026-09-21, 111 worktrees under .claude/worktrees)
------------------------------------------------------------------------------
  total                                18 GB, ~229 MB each
  registered with git                  111 of 111
  clean AND merged  -> reclaimable      95  (~15 GB)
  commits ahead of main -> KEEP         16
  of those, uncommitted changes          5
  older than 30 days                     0

Two findings shape this script, and both contradict the obvious design:

1. AGE IS THE WRONG AXIS. Nothing is older than 30 days, so an age rule reclaims
   nothing. The same mistake sits in db_retention.py:162, where content_embeddings
   has a 180-day cap on a 90-day-old table. What matters is whether the work
   still exists anywhere else.

2. THESE ARE REGISTERED GIT WORKTREES, not scratch directories. `rm -rf` leaves
   111 stale registrations behind. new-worktree.sh:50 documents the correct
   removal -- `git worktree remove` -- and this uses it.

And the reason the KEEP rule is not negotiable: five worktrees dated 2026-07-28
hold real unmerged work (ahead=25 "Active Trader motion: tests + findings",
ahead=12 "live motion UI"). The standing memory note records that at least five
commits exist ONLY inside worktrees. An age-based or blanket reaper destroys
them.

THE RULE
--------
A worktree is reclaimable when ALL of:
  * `git rev-list --count origin/main..HEAD` == 0   (nothing unmerged)
  * `git status --porcelain` is empty               (nothing uncommitted)
  * it is older than --min-age-days                 (default 3; a live agent's
                                                     tree is not garbage)
Anything else is kept and reported. When in doubt, keep.

    python scripts/agent_worktree_retention.py                 # dry run
    python scripts/agent_worktree_retention.py --apply
    python scripts/agent_worktree_retention.py --min-age-days 7 --apply

AUTHORITY: OPERATOR_APPROVED 2026-09-21. Removal is `git worktree remove`, never
`rm -rf`. Refuses to touch a worktree with unmerged commits under any flag.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

def _primary_repo_root() -> Path:
    """The PRIMARY checkout, not whatever tree this file happens to sit in.

    Found the hard way: the first dry run reported "worktrees found: 0" because
    ROOT resolved to the disk-guard worktree, whose .claude/worktrees does not
    exist. The 111 agent worktrees live under the primary tree. Installed as a
    timer, that version would have found nothing, reported success, and reclaimed
    nothing -- forever.

    `git rev-parse --git-common-dir` is the correct question: in a linked
    worktree it points at the PRIMARY tree's .git, unlike --git-dir.
    """
    here = Path(__file__).resolve().parents[1]
    try:
        out = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                             cwd=str(here), capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            common = Path(out.stdout.strip())
            if not common.is_absolute():
                common = (here / common).resolve()
            return common.parent
    except Exception:  # noqa: BLE001
        pass
    return here


ROOT = _primary_repo_root()
sys.path.insert(0, str(ROOT / "scripts"))

#: Directories holding agent-created worktrees. Add new agent tools here rather
#: than writing a second script.
AGENT_WORKTREE_ROOTS = [
    ROOT / ".claude" / "worktrees",
]

#: A worktree younger than this may belong to a session that is still running.
DEFAULT_MIN_AGE_DAYS = 3


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    """Return (rc, output). Output is stdout on success, STDERR on failure.

    The first --apply run reported six bare "FAILED <name>:" lines with no
    reason, because this returned stdout only and `git worktree remove` writes
    its refusal to stderr. A failure you cannot read is not a report.
    """
    try:
        p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                           text=True, timeout=60)
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        return p.returncode, (out if p.returncode == 0 else (err or out))
    except Exception as exc:  # noqa: BLE001
        return 1, f"{type(exc).__name__}: {exc}"


def _dir_mb(p: Path) -> int:
    try:
        out = subprocess.run(["du", "-sm", str(p)], capture_output=True,
                             text=True, timeout=120)
        return int((out.stdout or "0").split()[0])
    except Exception:  # noqa: BLE001
        return 0


def classify(wt: Path, min_age_days: int) -> dict:
    """Decide one worktree's fate. Every 'keep' carries its reason."""
    info: dict = {"path": str(wt), "name": wt.name}
    rc, ahead = _git(["rev-list", "--count", "origin/main..HEAD"], wt)
    if rc != 0:
        return {**info, "action": "keep", "reason": f"git_unreadable:{ahead[:60]}"}
    info["ahead"] = int(ahead or 0)

    rc, status = _git(["status", "--porcelain"], wt)
    info["dirty"] = len([ln for ln in status.splitlines() if ln.strip()]) if rc == 0 else -1

    try:
        age_days = (time.time() - wt.stat().st_mtime) / 86400.0
    except OSError:
        age_days = 0.0
    info["age_days"] = round(age_days, 1)

    # A locked worktree belongs to a RUNNING agent. Measured 2026-09-21: six
    # were locked by "claude agent ... (pid 43373)" -- this very session. git
    # refused them correctly; the script should never have tried. Removing a
    # live agent's tree with `remove -f -f` would delete work in progress.
    rc, locked = _git(["worktree", "list", "--porcelain"], ROOT)
    if rc == 0:
        block, hit = [], False
        for line in locked.splitlines() + [""]:
            if line.startswith("worktree "):
                if hit and any(b.startswith("locked") for b in block):
                    info["action"] = "keep"
                    info["reason"] = "locked:live_agent_session"
                    return info
                block, hit = [], str(wt) in line
            block.append(line)
        if hit and any(b.startswith("locked") for b in block):
            info["action"] = "keep"
            info["reason"] = "locked:live_agent_session"
            return info

    if info["ahead"] > 0:
        rc, last = _git(["log", "-1", "--format=%ad %s", "--date=short"], wt)
        info["last_commit"] = last[:70] if rc == 0 else ""
        info["action"] = "keep"
        info["reason"] = f"unmerged:{info['ahead']}_commits_ahead_of_main"
        return info
    if info["dirty"] != 0:
        info["action"] = "keep"
        info["reason"] = f"uncommitted:{info['dirty']}_files"
        return info
    if age_days < min_age_days:
        info["action"] = "keep"
        info["reason"] = f"too_recent:{info['age_days']}d_under_{min_age_days}d"
        return info
    info["action"] = "reclaim"
    info["reason"] = "merged_and_clean"
    return info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="execute; without it the script only reports")
    ap.add_argument("--min-age-days", type=int, default=DEFAULT_MIN_AGE_DAYS)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    plans: list[dict] = []
    for root in AGENT_WORKTREE_ROOTS:
        if not root.is_dir():
            continue
        for wt in sorted(p for p in root.iterdir() if p.is_dir()):
            plans.append(classify(wt, a.min_age_days))

    reclaim = [p for p in plans if p["action"] == "reclaim"]
    keep = [p for p in plans if p["action"] == "keep"]
    unmerged = [p for p in keep if p.get("reason", "").startswith("unmerged")]

    print(f"Agent worktree retention — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    print("-" * 68)
    print(f"  worktrees found      : {len(plans)}")
    print(f"  reclaimable          : {len(reclaim)}  (merged AND clean AND >={a.min_age_days}d)")
    print(f"  kept                 : {len(keep)}")
    print(f"    of which UNMERGED  : {len(unmerged)}   <- never removed, under any flag")

    if unmerged:
        print("\n  KEEPING (work exists only here):")
        for p in unmerged[:20]:
            print(f"    {p['name']:<38} ahead={p['ahead']:<4} {p.get('last_commit','')}")

    if not a.apply:
        size = sum(_dir_mb(Path(p["path"])) for p in reclaim)
        print(f"\n  would reclaim: ~{size/1024:.1f} GB")
        print("\nDRY RUN — nothing removed. Re-run with --apply to execute.")
        if a.json:
            print(json.dumps({"plans": plans}, indent=2))
        return 0

    removed = failed = mb = 0
    for p in reclaim:
        before = _dir_mb(Path(p["path"]))
        rc, out = _git(["worktree", "remove", p["path"]], ROOT)
        if rc == 0:
            removed += 1
            mb += before
        else:
            # --force only for a tree git considers modified by untracked build
            # artifacts; never for one with commits, which classify() excluded.
            rc2, out2 = _git(["worktree", "remove", "--force", p["path"]], ROOT)
            if rc2 == 0:
                removed += 1
                mb += before
            else:
                failed += 1
                print(f"    FAILED {p['name']}: {out2[:100]}")
    _git(["worktree", "prune"], ROOT)

    print(f"\n  removed   : {removed}")
    print(f"  reclaimed : ~{mb/1024:.1f} GB")
    print(f"  failed    : {failed}")
    print(f"  kept      : {len(keep)} ({len(unmerged)} holding unmerged work)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

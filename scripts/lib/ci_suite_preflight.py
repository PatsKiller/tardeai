"""Does this head need the full CI suite? (DSN-20261031-ci-load-reduction §5, D50 item 7.)

A push that only merges ``origin/main`` into a branch carries no new **branch** content: the branch's own
diff against ``origin/main`` is the same at the merge commit as it was at the merge's first parent. Running
the twelve-job sharded suite on it costs about 110 runner-minutes to re-learn what the first parent's run
already said — on 2026-10-31, 54% of all runs were exactly those catch-up pushes, and 269 of 444 full-suite
PR runs were cancelled by a newer push anyway.

The rule implemented here is deliberately narrow:

* a **non-merge** head always needs the suite — it may have changed anything;
* a **merge whose branch-side diff is identical to its first parent's** needs nothing: the merge brought
  only the other side (main) in;
* a merge that ALSO changed the branch's own files — a hand-resolved conflict, a fix folded into the merge
  commit — needs the suite, because that content has never been tested;
* anything unreadable, shallow or ambiguous needs the suite. The failure direction is always "run": a
  skipped suite that should have run is a green on untested code, and that is the one outcome this module
  must never produce.

The rule assumes what the design assumes: the first parent was itself pushed and therefore had its own run
(or its run is the one this head supersedes). It is not a claim that main is untested — push-to-main runs
the same suite and is never skipped here.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

MAIN = "origin/main"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)  # noqa: S603, S607 -- fixed git argv list, no shell; git is resolved from the runner PATH


def _out(repo: Path, *args: str) -> str | None:
    r = _git(repo, *args)
    return r.stdout.strip() if r.returncode == 0 else None


def parents(repo: Path, head: str) -> list[str] | None:
    """The head's parents, or None when the object cannot be read (a shallow clone, an unknown sha)."""
    raw = _out(repo, "rev-list", "--parents", "-n", "1", head)
    if not raw:
        return None
    parts = raw.split()
    return parts[1:] if parts else None


def branch_diff(repo: Path, commit: str, main: str = MAIN) -> str | None:
    """The commit's own changes against ``main``, as a stable diff — or None when it cannot be computed."""
    base = _out(repo, "merge-base", main, commit)
    if not base:
        return None
    r = _git(repo, "diff", "--no-color", "--no-ext-diff", base, commit)
    return r.stdout if r.returncode == 0 else None


def decide(repo: Path, head: str = "HEAD", main: str = MAIN) -> dict:
    """{needed: bool, reason: str} for one head. Fails OPEN (needed=True) whenever it cannot tell."""
    ps = parents(repo, head)
    if ps is None:
        return {"needed": True, "reason": "the head could not be read; running the suite is the safe direction"}
    if len(ps) < 2:
        return {"needed": True, "reason": "the head is not a merge, so it may have changed any file"}
    head_diff = branch_diff(repo, head, main)
    base_diff = branch_diff(repo, ps[0], main)
    if head_diff is None or base_diff is None:
        return {"needed": True, "reason": f"{main} or a parent could not be read; running the suite is the safe direction"}
    if head_diff == base_diff:
        return {"needed": False,
                "reason": "merge-of-main-only: the branch's diff against main is identical to its first parent's, "
                          "so the merge brought only main in"}
    return {"needed": True, "reason": "the merge also changed the branch's own files (a hand resolution or a fix folded in)"}


def main(argv: list[str] | None = None) -> int:
    """CLI for the workflow: writes suite_needed/reason, prints the decision, exits 0 either way."""
    import argparse
    from pathlib import Path as _Path

    ap = argparse.ArgumentParser(description="Decide whether a head needs the full CI suite")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--main", default=MAIN)
    ap.add_argument("--github-output", default=None)
    a = ap.parse_args(argv)
    out = decide(_Path(a.repo), a.head, a.main)
    print(f"preflight: suite_needed={'true' if out['needed'] else 'false'} — {out['reason']}")
    if a.github_output:
        with open(a.github_output, "a", encoding="utf-8") as fh:
            fh.write(f"suite_needed={'true' if out['needed'] else 'false'}\n")
            fh.write(f"reason={out['reason']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

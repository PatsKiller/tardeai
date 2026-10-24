"""Operator-controlled proposal/ratification. Previews by default. Never pushes or merges."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

from package21 import HERE, ADAPTERS, apply_proposed, check_base, check_package, load_module, run

DEFAULT_REPO = Path.home() / "trade-ai-v12-rebuild/trade-ai-v12-rebuild"
DEFAULT_WT = Path.home() / "wt-agents-21-0-0-wp16-apply"
BRANCH = "ops/agents-21-0-0-wp16-20261023"
SESSION = "operator-wp16-20261023"


def capture(argv, **kwargs):
    return subprocess.check_output([str(x) for x in argv], text=True, **kwargs).strip()


def print_commit(root, paths, ratified=False):
    print("Review the changes, then commit/publish as the operator:")
    print("cd " + shlex.quote(str(root)))
    print("git diff --check && git diff --stat")
    print("git add -- " + " ".join(shlex.quote(x) for x in paths))
    message = "WP-16 AGENTS 21.0.0 " + (
        "ACTIVE: operator token ratification" if ratified else "PROPOSED: advisory sizing package"
    )
    print(
        "AGENT_CLAIM_SESSION="
        + SESSION
        + " git commit -m "
        + shlex.quote(message)
        + " -m "
        + shlex.quote("Design-Task: DSN-20261023-handoff-v3-P4-T16")
    )
    print("TRADEAI_REMOTE_PUSH_AUTHORIZED=1 git push -u origin " + shlex.quote(BRANCH))
    if not ratified:
        print(
            "gh pr create --base main --head "
            + shlex.quote(BRANCH)
            + " --title "
            + shlex.quote("WP-16 AGENTS 21.0.0 PROPOSED advisory sizing (operator-applied)")
            + " --body-file "
            + shlex.quote(str(HERE / "operator-pr-body.md"))
        )
    print("Never merge before real operator ratification and four required checks pass. The coordinator owns release.")


def apply(args):
    check_package()
    remote = capture(["git", "-C", args.repo, "ls-remote", "--exit-code", "--heads", "origin", "main"]).split()[0]
    local = capture(["git", "-C", args.repo, "rev-parse", "origin/main"])
    if remote != local:
        raise SystemExit("REFUSE: origin/main is stale; operator must git fetch origin and rerun preview")
    check_base(args.repo, "origin/main")
    base = (HERE / "BASE_SHA").read_text().strip()
    run(["git", "-C", args.repo, "merge-base", "--is-ancestor", base, "origin/main"])
    manifest = json.loads((HERE / "BASE_MANIFEST.json").read_text())
    paths = ["AGENTS.md"] + [
        x for x in manifest["files"] if x.startswith(("tests/", "config/")) or x == "scripts/lib/cio_advisory_sizing.py"
    ]
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "preview",
                "base": base,
                "worktree": str(args.worktree),
                "branch": BRANCH,
                "files": paths,
            },
            indent=2,
        )
    )
    if not args.apply:
        print("PREVIEW ONLY: exact policy and touched-file digests match; no worktree, claim or policy change made.")
        return
    if args.worktree.exists():
        raise SystemExit(
            "REFUSE: operator worktree already exists; inspect/reuse it manually, never delete automatically"
        )
    run(["git", "-C", args.repo, "worktree", "add", "-b", BRANCH, args.worktree, "origin/main"])
    run(
        [
            "python3",
            "scripts/agent_claim.py",
            "--vendor",
            "operator",
            "--session",
            SESSION,
            "--agent",
            "operator",
            "claim",
            "--task",
            "WP-16 operator proposal apply",
            "--branch",
            BRANCH,
            "--paths",
            *paths,
            *ADAPTERS,
            "--goal",
            "Operator applies the exact pinned WP-16 PROPOSED policy package",
            "--plan",
            "Review exact base and proposed policy",
            "Run policy suite and publish operator PR",
        ],
        cwd=args.worktree,
    )
    apply_proposed(args.worktree)
    run(["bash", HERE / "checks21.sh", args.worktree])
    print_commit(args.worktree, paths)


def ratify(args):
    check_package()
    root = args.worktree
    if capture(["git", "-C", root, "branch", "--show-current"]) != BRANCH:
        raise SystemExit("REFUSE: wrong operator branch")
    sha = capture(["git", "-C", root, "rev-parse", "HEAD"])
    if capture(["git", "-C", root, "status", "--porcelain"]):
        raise SystemExit("REFUSE: ratification requires a clean, committed proposal")
    pr = json.loads(
        capture(
            [
                "gh",
                "pr",
                "view",
                BRANCH,
                "--repo",
                "PatsKiller/tardeai",
                "--json",
                "number,headRefOid,headRefName,state",
            ]
        )
    )
    if pr["state"] != "OPEN" or pr["headRefOid"] != sha or pr["headRefName"] != BRANCH:
        raise SystemExit("REFUSE: PR/HEAD/branch mismatch")
    token = f"APPROVE_AGENTS_POLICY_21_0_0 {pr['number']} {sha}"
    print("Exact operator token for this PR/head: " + token)
    if not args.apply:
        print("gh pr comment " + str(pr["number"]) + " --repo PatsKiller/tardeai --body " + shlex.quote(token))
        print("PREVIEW ONLY: no token was posted and no policy or adapter changed.")
        return
    comments = json.loads(
        capture(["gh", "api", f"repos/PatsKiller/tardeai/issues/{pr['number']}/comments", "--paginate", "--slurp"])
    )
    flat = [c for page in comments for c in page]
    hits = [
        c for c in flat if c.get("user", {}).get("login") == "PatsKiller" and (c.get("body") or "").strip() == token
    ]
    if not hits:
        raise SystemExit("REFUSE: no exact operator-owned approval comment for this PR/head")
    comment = hits[-1]
    date = capture(["date", "-d", comment["created_at"], "+%F"], env={**os.environ, "TZ": "America/New_York"})
    load_module("build_ratify21").ratify(root, pr["number"], sha, str(comment["id"]), comment["created_at"], date)
    run(["bash", HERE / "checks21.sh", root])
    print_commit(root, ["AGENTS.md", *ADAPTERS], ratified=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["apply", "ratify"])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--worktree", type=Path, default=DEFAULT_WT)
    a = parser.parse_args()
    apply(a) if a.command == "apply" else ratify(a)

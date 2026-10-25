#!/usr/bin/env python3
"""OPERATOR entry point. Preview is read-only; apply/ratify need a TTY and exact phrase."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from common import HERE, apply_proposed, metadata, output, ratify_text, run, verify_base, verify_digests

REPO = Path(os.environ.get("REPO", str(Path.home() / "trade-ai-v12-rebuild/trade-ai-v12-rebuild")))
WT = Path(os.environ.get("WT", str(Path.home() / "wt-agents-20-2-operator-20261023")))
BRANCH = "ops/agents-20-2-20261023"


def confirm(phrase):
    if not sys.stdin.isatty():
        raise ValueError("operator TTY required; do not pipe a confirmation")
    if input(f"Type {phrase}: ") != phrase:
        raise ValueError("confirmation did not match")


def checks(tree):
    env = dict(os.environ, TRADE_AI_CI="1", TMPDIR=str(Path.home() / ".cache/rtc"))
    env["PY"] = os.environ.get("PY", str(REPO / ".venv/bin/python"))
    run("bash", str(HERE / "checks202.sh"), cwd=tree, env=env)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("apply", "ratify"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--pr")
    ap.add_argument("--sha")
    a = ap.parse_args()
    verify_digests()
    if a.action == "apply":
        ref = verify_base(REPO)
        print(f"PREVIEW: origin/main {ref}; exact policy/support digests match; patch SHA256SUMS verified")
        print(
            f"Would create {WT} on {BRANCH}; apply only {len(metadata()['files'])} declared paths; run checks, commit and publish PROPOSED PR"
        )
        print("Runtime flags remain unchanged; approve_item stays false; no service, credential or endpoint calls")
        if not a.apply:
            return 0
        if (
            WT.exists()
            or subprocess.run(["git", "show-ref", "--verify", "--quiet", "refs/heads/" + BRANCH], cwd=REPO).returncode
            == 0
        ):
            raise ValueError("operator worktree/branch already exists; inspect rather than replacing it")
        confirm("APPLY-AGENTS-20-2-PROPOSED")
        run("git", "worktree", "add", "-b", BRANCH, str(WT), ref, cwd=REPO)
        apply_proposed(WT)
        checks(WT)
        run("git", "add", "--", *metadata()["files"], cwd=WT)
        run(
            "git",
            "commit",
            "-m",
            "AGENTS 20.2.0 PROPOSED: operator Work pipeline acts and evidence obligations",
            "-m",
            "Design-Task: DSN-20261023-handoff-v3-P4-T15",
            cwd=WT,
        )
        env = dict(os.environ, TRADEAI_REMOTE_PUSH_AUTHORIZED="1")
        run("git", "push", "-u", "origin", BRANCH, cwd=WT, env=env)
        run(
            "gh",
            "pr",
            "create",
            "--base",
            "main",
            "--head",
            BRANCH,
            "--title",
            "WP-15 AGENTS 20.2.0 PROPOSED operator package",
            "--body-file",
            str(HERE / "operator-pr-body.md"),
            cwd=WT,
        )
        print(output("gh", "pr", "view", BRANCH, "--json", "number,headRefOid,url", cwd=WT))
        return 0
    if not a.pr or not a.sha:
        raise ValueError("ratify requires --pr and --sha from the proposed PR")
    if (
        output("git", "branch", "--show-current", cwd=WT) != BRANCH
        or output("git", "rev-parse", "HEAD", cwd=WT) != a.sha
    ):
        raise ValueError("operator branch/head mismatch")
    if output("git", "status", "--porcelain", cwd=WT):
        raise ValueError("operator worktree is not clean")
    pr = json.loads(output("gh", "pr", "view", a.pr, "--json", "headRefOid,headRefName,state", cwd=WT))
    if pr != {"headRefOid": a.sha, "headRefName": BRANCH, "state": "OPEN"}:
        raise ValueError("PR branch/head/state mismatch")
    comments = output("gh", "api", f"repos/PatsKiller/tardeai/issues/{a.pr}/comments", "--paginate", "--slurp", cwd=WT)
    token = f"APPROVE_AGENTS_POLICY_20_2_0 {a.pr} {a.sha}"
    hits = [
        c
        for page in json.loads(comments)
        for c in page
        if c["user"]["login"] == "PatsKiller" and (c.get("body") or "").strip() == token
    ]
    if not hits:
        raise ValueError("no exact approval token comment by PatsKiller")
    hit = hits[-1]
    original = (WT / "AGENTS.md").read_text()
    updated = ratify_text(original, pr=a.pr, sha=a.sha, comment_id=str(hit["id"]), comment_at=hit["created_at"])
    print(
        f"PREVIEW: exact operator comment {hit['id']} at {hit['created_at']}; only AGENTS.md header/banner/history ratifying edit; runtime flags unchanged"
    )
    if not a.apply:
        return 0
    confirm(f"RATIFY-AGENTS-20-2-{a.pr}-{a.sha}")
    (WT / "AGENTS.md").write_text(updated)
    checks(WT)
    if output("git", "status", "--porcelain", cwd=WT) != "M AGENTS.md":
        raise ValueError("unexpected ratification working-tree change")
    run("git", "add", "AGENTS.md", cwd=WT)
    run(
        "git",
        "commit",
        "-m",
        f"AGENTS 20.2.0 ACTIVE: operator token on PR #{a.pr}",
        "-m",
        "Design-Task: DSN-20261023-handoff-v3-P4-T15",
        cwd=WT,
    )
    run("git", "push", "origin", BRANCH, cwd=WT, env=dict(os.environ, TRADEAI_REMOTE_PUSH_AUTHORIZED="1"))
    print("Operator: merge only after exact-head required checks pass. Feature flags require a later reviewed PR.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, AssertionError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"REFUSED: {exc}")

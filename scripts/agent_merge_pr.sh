#!/usr/bin/env bash
# Merge a PR via GitHub API — no local checkout of main (worktree-safe).
#
# Usage: scripts/agent_merge_pr.sh <pr-number-or-url>
#
# Refuses (exit 3) during a Release Train merge freeze unless the PR is exempt
# (scripts/release_train_freeze.py check-pr).
#
# Avoids ``gh pr merge --delete-branch``, which tries to checkout main locally
# and fails when main is checked out in another worktree.
set -euo pipefail
PR="${1:?usage: agent_merge_pr.sh <pr-number-or-url>}"
REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
STATE="$(gh pr view "$PR" --json state -q .state)"
if [[ "$STATE" != "OPEN" ]]; then
  echo "PR $PR already $STATE — nothing to merge."
  exit 0
fi
# Release Train v2 merge freeze (AGENTS.md §25.3; docs/ops/RELEASE_TRAIN_MERGE_FREEZE.md): from 30 min before a
# scheduled window until its train is terminal, only the train merges to main. Exit 3 = frozen; any other failure
# of the check also refuses (fail closed: an agent merge is never urgent).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set +e
python3 "$ROOT/scripts/release_train_freeze.py" check-pr "$PR" --repo "$REPO"
FREEZE_RC=$?
set -e
if [[ "$FREEZE_RC" -ne 0 ]]; then
  if [[ "$FREEZE_RC" -ne 3 ]]; then
    echo "merge-freeze check failed (rc=$FREEZE_RC); refusing to merge PR $PR" >&2
  fi
  exit 3
fi
gh pr merge "$PR" --merge --repo "$REPO"
BRANCH="$(gh pr view "$PR" --json headRefName -q .headRefName)"
gh api -X DELETE "repos/${REPO}/git/refs/heads/${BRANCH}" >/dev/null 2>&1 \
  || echo "Remote branch delete skipped (may already be gone): $BRANCH"
echo "Merged $PR ($REPO); remote branch $BRANCH removed if present."

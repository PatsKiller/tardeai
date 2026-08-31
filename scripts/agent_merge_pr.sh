#!/usr/bin/env bash
# Merge a PR via GitHub API — no local checkout of main (worktree-safe).
#
# Usage: scripts/agent_merge_pr.sh <pr-number-or-url>
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
gh pr merge "$PR" --merge --repo "$REPO"
BRANCH="$(gh pr view "$PR" --json headRefName -q .headRefName)"
gh api -X DELETE "repos/${REPO}/git/refs/heads/${BRANCH}" >/dev/null 2>&1 \
  || echo "Remote branch delete skipped (may already be gone): $BRANCH"
echo "Merged $PR ($REPO); remote branch $BRANCH removed if present."

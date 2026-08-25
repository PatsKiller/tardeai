#!/usr/bin/env bash
# Install the tracked AI work-policy hooks for this clone/worktree.
# Does not push. Does not deploy. Does not weaken secrets or hygiene checks.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

chmod +x "$ROOT/.githooks/pre-commit" "$ROOT/.githooks/pre-push"
chmod +x "$ROOT/scripts/install_ai_work_policy.sh" "$ROOT/scripts/ai_local_acceptance.sh"

# Worktree-scoped when possible so a shared .git with many worktrees is not
# globally switched until this checkout actually contains .githooks.
git_dir="$(git rev-parse --absolute-git-dir)"
common="$(cd "$(git rev-parse --git-common-dir)" && pwd)"
if [[ "$git_dir" != "$common" ]]; then
  git config extensions.worktreeConfig true
  git config --worktree core.hooksPath .githooks
  echo "core.hooksPath=.githooks (worktree-local)"
else
  git config core.hooksPath .githooks
  echo "core.hooksPath=.githooks (clone-local)"
fi

echo
echo "AI work policy hooks installed."
echo "  canonical policy: $ROOT/AI_WORK_POLICY.md"
echo "  pre-commit: secrets + scripts/githooks/pre-commit if present"
echo "  pre-push:   TRADEAI_REMOTE_PUSH_AUTHORIZED=1 then secrets --tree"
echo
echo "Remote push remains separately authorized."
echo "Test the gate:  git push   (must block without the env flag)"

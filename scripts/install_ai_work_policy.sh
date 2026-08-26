#!/usr/bin/env bash
# Install the tracked AI work-policy hooks for this clone/worktree.
# Idempotent. Does not push, deploy, or write global git config.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if [[ ! -f "$ROOT/AI_WORK_POLICY.md" ]]; then
  echo "ERROR: policy file not found: $ROOT/AI_WORK_POLICY.md" >&2
  exit 1
fi

chmod +x "$ROOT/.githooks/pre-commit" "$ROOT/.githooks/pre-push"
chmod +x "$ROOT/scripts/install_ai_work_policy.sh" \
  "$ROOT/scripts/ai_local_acceptance.sh" \
  "$ROOT/scripts/ai_work_status.sh" 2>/dev/null || true

before_global="$(git config --global --get core.hooksPath || true)"

git_dir="$(git rev-parse --absolute-git-dir)"
common="$(cd "$(git rev-parse --git-common-dir)" && pwd)"
if [[ "$git_dir" != "$common" ]]; then
  git config extensions.worktreeConfig true
  git config --worktree core.hooksPath .githooks
  scope="worktree-local"
else
  git config core.hooksPath .githooks
  scope="clone-local"
fi

after_global="$(git config --global --get core.hooksPath || true)"
if [[ "$before_global" != "$after_global" ]]; then
  echo "ERROR: installer mutated global git config" >&2
  exit 1
fi

branch="$(git rev-parse --abbrev-ref HEAD)"
hook_ok=false
[[ -x "$ROOT/.githooks/pre-push" ]] && hook_ok=true

echo "policy file found: $ROOT/AI_WORK_POLICY.md"
echo "hook path configured: .githooks ($scope)"
echo "pre-push executable: $hook_ok"
echo "current branch: $branch"
echo "remote push default=BLOCKED"
echo "budget file: $git_dir/tradeai-push-budget.json (git-dir, not committed)"
echo
echo "Remote push remains separately authorized:"
echo "  TRADEAI_REMOTE_PUSH_AUTHORIZED=1 git push ..."

#!/usr/bin/env bash
# install-git-hygiene.sh — install the git-hygiene guard: hooks into the shared git dir + the `git`
# wrapper into ~/.bashrc. Idempotent. Run once from PROJECT_ROOT.
#   ALLOW_MAINTREE_GIT=1 bash scripts/install-git-hygiene.sh
set -euo pipefail
PROJECT_ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJECT_ROOT"

# Hooks live in the COMMON git dir → they apply to the primary tree AND every linked worktree; the guard
# itself no-ops in linked worktrees (only fires in the primary live tree), so this is safe.
HOOKS_DIR="$(git rev-parse --git-common-dir)/hooks"
mkdir -p "$HOOKS_DIR"
for h in pre-commit pre-rebase post-checkout; do
  src="$PROJECT_ROOT/scripts/githooks/$h"
  dst="$HOOKS_DIR/$h"
  # Preserve a pre-existing NON-hygiene hook (e.g. the secret scanner) under a stable name so our hook
  # can CHAIN to it. Only do this once — never clobber an already-saved chained hook on reinstall.
  if [ -e "$dst" ] && ! grep -q "git_hygiene_guard" "$dst" 2>/dev/null; then
    if [ ! -e "$dst.chained" ]; then
      cp "$dst" "$dst.chained"; chmod +x "$dst.chained"
      echo "preserved existing $h → $dst.chained (our hook will chain to it)"
    fi
  fi
  install -m 0755 "$src" "$dst"
  echo "installed hook: $dst"
done

# `git` wrapper for interactive shells (blocks branch switch/reset — no native pre-checkout hook)
MARK="# >>> tradeai git-hygiene >>>"
BRC="$HOME/.bashrc"
if ! grep -qF "$MARK" "$BRC" 2>/dev/null; then
  {
    echo ""
    echo "$MARK"
    echo "source $PROJECT_ROOT/scripts/git-hygiene.sh"
    echo "# <<< tradeai git-hygiene <<<"
  } >> "$BRC"
  echo "added git-hygiene source line to $BRC (applies to NEW shells)"
else
  echo "git-hygiene already sourced in $BRC"
fi

echo
echo "✅ installed. New shells get the git wrapper; hooks are active now."
echo "   Test:  (cd $PROJECT_ROOT && git switch -c throwaway)   # should be blocked while server is live"
echo "   Uninstall: remove the block in $BRC and the *-hygiene hooks in $HOOKS_DIR"

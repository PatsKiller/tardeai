#!/usr/bin/env bash
# git_hygiene_guard.sh — shared logic for the git-hygiene guard (2026-07-01).
#
# WHY: the primary working tree (PROJECT_ROOT) is what portfolio_server.py HOT-RELOADS code from.
# Multiple interactive claude/codex sessions share this one tree — a `git checkout`/`reset` here swaps
# files under the LIVE dashboard and under other sessions (a commit lands on whoever's branch is checked
# out). See docs/GIT_HYGIENE.md. This guard keeps the live primary tree pinned to its current branch and
# pushes all branch work into isolated worktrees.
#
# Sourced by scripts/git-hygiene.sh (the `git` wrapper) and executed by the git hooks in scripts/githooks/.
# All functions are read-only checks; they never mutate anything. Override for legit server-tree ops
# (deploy pulls, the installer) with: ALLOW_MAINTREE_GIT=1

GIT_HYGIENE_PROJECT_ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
GIT_HYGIENE_PROTECTED_BRANCHES="main master"

# True when the CURRENT dir is the primary (non-linked) working tree at PROJECT_ROOT — NOT a linked worktree.
_gh_is_primary_tree() {
  local top gd gcd
  top=$(git rev-parse --show-toplevel 2>/dev/null) || return 1
  [ "$top" = "$GIT_HYGIENE_PROJECT_ROOT" ] || return 1
  # linked worktrees have --git-dir != --git-common-dir; the primary tree has them equal
  gd=$(git rev-parse --absolute-git-dir 2>/dev/null)
  gcd=$(cd "$(git rev-parse --git-common-dir 2>/dev/null)" 2>/dev/null && pwd)
  [ "$gd" = "$gcd" ]
}

# True when the trade-ai dashboard server is live (it hot-reloads from the primary tree).
_gh_server_live() {
  systemctl is-active --quiet tradeai-portfolio-server 2>/dev/null && return 0
  pgrep -f "scripts/portfolio_server.py" >/dev/null 2>&1
}

# The guard fires only in the primary tree + live server + no override.
_gh_guard_active() {
  [ -n "$ALLOW_MAINTREE_GIT" ] && return 1
  _gh_is_primary_tree || return 1
  _gh_server_live || return 1
  return 0
}

_gh_block_msg() {
  local action="$1"
  cat >&2 <<EOF
⛔ git-hygiene: refusing to $action in the PRIMARY working tree while the trade-ai server is LIVE.
   The server hot-reloads code from here, and other claude/codex sessions share this tree —
   branch switches / rebases here swap files under the live dashboard and clobber other sessions.

   → Do branch work in an isolated worktree:   scripts/new-worktree.sh <name>
   → Server-tree deploy only (bypass guard):    ALLOW_MAINTREE_GIT=1 git ...
EOF
}

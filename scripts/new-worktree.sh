#!/usr/bin/env bash
# new-worktree.sh — spin up an isolated git worktree for branch work, so the LIVE primary tree
# (which the server hot-reloads from) is never disturbed. See docs/GIT_HYGIENE.md.
#
#   scripts/new-worktree.sh <short-name> [base]
#     <short-name>  →  branch `wt/<short-name>` and dir /home/johnclaw/tradeai-wt-<short-name>
#     [base]        →  base ref (default origin/main)
set -euo pipefail

PROJECT_ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
name="${1:-}"
base="${2:-origin/main}"
if [ -z "$name" ]; then echo "usage: scripts/new-worktree.sh <short-name> [base]" >&2; exit 2; fi
# sanitize: git branch names can't contain many chars; keep it simple
safe=$(printf '%s' "$name" | tr -c 'A-Za-z0-9._-' '-')
wt="/home/johnclaw/tradeai-wt-${safe}"
branch="wt/${safe}"

cd "$PROJECT_ROOT"
ALLOW_MAINTREE_GIT=1 git fetch origin main -q || true
if [ -e "$wt" ]; then echo "worktree path already exists: $wt" >&2; exit 1; fi

ALLOW_MAINTREE_GIT=1 git worktree add -b "$branch" "$wt" "$base"

# SOP Stage 5: never copy/symlink .env by default. Opt-in only:
#   TRADEAI_WORKTREE_LINK_ENV=1 scripts/new-worktree.sh ...
if [ "${TRADEAI_WORKTREE_LINK_ENV:-0}" = "1" ]; then
  ln -sf "$PROJECT_ROOT/.env" "$wt/.env" 2>/dev/null || true
  env_note="symlinked (.env) via TRADEAI_WORKTREE_LINK_ENV=1"
else
  env_note="NOT linked (default). Use PROJECT_ROOT/.venv; set TRADEAI_WORKTREE_LINK_ENV=1 only if required"
fi

# Refuse force-remove guidance when dirty — print safe cleanup only.
cat <<EOF

✅ worktree ready
   dir:    $wt
   branch: $branch (off $base)
   .env:   $env_note
   python: $PROJECT_ROOT/.venv/bin/python

Next (explicit paths only — never use add-all / add-dot):
   cd $wt
   git add path/to/file1 path/to/file2
   git commit -m "..."
   # Remote push requires operator authorization (AI_WORK_POLICY).

Cleanup (refuses dirty trees — do not --force while dirty):
   git -C "$PROJECT_ROOT" worktree remove "$wt"
EOF

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
# gitignored files the worktree needs for running python/DB scripts
ln -sf "$PROJECT_ROOT/.env" "$wt/.env" 2>/dev/null || true

cat <<EOF

✅ worktree ready
   dir:    $wt
   branch: $branch (off $base)
   .env:   symlinked from PROJECT_ROOT (DB/creds work; .venv: use $PROJECT_ROOT/.venv/bin/python)

Next:
   cd $wt
   # ...edit, then commit here (never in PROJECT_ROOT):
   git add -A && git commit -m "..." && git push -u origin $branch
   gh pr create --base main --head $branch

When merged/done:
   git -C "$PROJECT_ROOT" worktree remove "$wt" --force
EOF

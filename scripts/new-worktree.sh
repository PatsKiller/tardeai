#!/usr/bin/env bash
# new-worktree.sh — spin up an isolated git worktree for branch work, so the LIVE primary tree
# (which the server hot-reloads from) is never disturbed. See docs/GIT_HYGIENE.md.
#
#   scripts/new-worktree.sh [--dry-run] <short-name> [base]
#     <short-name>  →  branch `wt/<short-name>`
#                      and a tree at ${TRADEAI_WORKTREE_ROOT:-/data/worktrees}/tradeai-wt-<short-name>
#                      with a compatibility symlink ~/tradeai-wt-<short-name> to it
#     [base]        →  base ref (default origin/main)
#     --dry-run     →  verify the volume and print the resolved paths; create nothing
#
# LQ-20261113-3151: trees live on the verified /data volume, never on the 468 GB root filesystem.
# The old path keeps working through the symlink, so every documented `cd ~/tradeai-wt-…`
# still resolves. The mount guard runs FIRST and refuses to create anything when /data is not the
# verified volume: a tree created on root is exactly the silent failure this script exists to avoid.
# It is never a fallback — there is no "create it on root anyway" path.
set -euo pipefail

PROJECT_ROOT="${TRADEAI_PROJECT_ROOT:-${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
LEGACY_HOME="${TRADEAI_WORKTREE_LEGACY_HOME:-${HOME}}"
VOLUME_ROOT="${TRADEAI_VOLUME_ROOT:-/data}"
WT_ROOT="${TRADEAI_WORKTREE_ROOT:-${VOLUME_ROOT}/worktrees}"
GUARD="${PROJECT_ROOT}/scripts/lib/tradeai_volume.py"
dry_run=0
if [ "${1:-}" = "--dry-run" ] || [ "${1:-}" = "-n" ]; then dry_run=1; shift; fi
name="${1:-}"
base="${2:-origin/main}"
if [ -z "$name" ]; then echo "usage: scripts/new-worktree.sh [--dry-run] <short-name> [base]" >&2; exit 2; fi
# sanitize: git branch names can't contain many chars; keep it simple
safe=$(printf '%s' "$name" | tr -c 'A-Za-z0-9._-' '-')
wt="${WT_ROOT}/tradeai-wt-${safe}"
link="${LEGACY_HOME}/tradeai-wt-${safe}"
branch="wt/${safe}"

# ---- mount guard (LQ-3151). Non-zero here = a clear refusal, never a tree on root.
if [ ! -f "$GUARD" ]; then echo "new-worktree: mount guard missing: $GUARD" >&2; exit 78; fi
if ! python3 "$GUARD" check --root "$VOLUME_ROOT" --path "$WT_ROOT" --quiet; then
  echo "new-worktree: refusing to create $wt — the verified ${VOLUME_ROOT} volume is not mounted." >&2
  exit 78
fi

cd "$PROJECT_ROOT"
if [ "$dry_run" = "1" ]; then
  echo "dry run: nothing created."
  echo "   tree:   $wt"
  echo "   branch: $branch (off $base)"
  echo "   link:   $link -> $wt"
  exit 0
fi

ALLOW_MAINTREE_GIT=1 git fetch origin main -q || true
if [ -e "$wt" ] || [ -L "$wt" ]; then echo "worktree path already exists: $wt" >&2; exit 1; fi
if [ -e "$link" ] || [ -L "$link" ]; then echo "path already exists: $link" >&2; exit 1; fi

mkdir -p "$WT_ROOT"
ALLOW_MAINTREE_GIT=1 git worktree add -b "$branch" "$wt" "$base"
ln -s "$wt" "$link"

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
   dir:    $wt          (on ${VOLUME_ROOT}, the verified volume)
   link:   $link -> $wt (the legacy path keeps working)
   branch: $branch (off $base)
   .env:   $env_note
   python: $PROJECT_ROOT/.venv/bin/python

Next (explicit paths only — never use add-all / add-dot):
   cd $link
   git add path/to/file1 path/to/file2
   git commit -m "..."
   # Remote push requires operator authorization (AI_WORK_POLICY).

Cleanup (refuses dirty trees — do not --force while dirty):
   git -C "$PROJECT_ROOT" worktree remove "$wt"
   # the $link symlink is left in place; remove it only after the tree is gone
EOF

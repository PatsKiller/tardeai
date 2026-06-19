#!/bin/bash
# commit_hermes_daily.sh — auto-commit the day's Hermes auto-generated daily reports (operator 2026-06-19).
# Scope is STRICTLY docs/hermes/ (backlog_health, embedding_promotion_reviews, librarian_loop_dryruns,
# observations). IRON-guarded; the pre-commit secret hook is the safety net; only commits/pushes when
# there is something to commit. One-way: local → origin/main, then mirror docs to Drive.
set -uo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
PY="$PROJ/.venv/bin/python"
cd "$PROJ" || { echo "[hermes-daily] cd failed"; exit 1; }

# IRON RULE — never operate on a wiped holdings file
if ! "$PY" -c "import json,sys;d=json.load(open('data/portfolios/state/holdings.json'));sys.exit(0 if d['portfolio_totals']['total_value']>1000000 else 1)"; then
  echo "[hermes-daily] IRON RULE failed (holdings <= \$1M or unreadable) — aborting"; exit 1
fi

# Stage ONLY hermes docs (includes adds/mods/deletes under that path)
git add docs/hermes/ 2>/dev/null

# Nothing to commit → clean exit
if git diff --cached --quiet -- docs/hermes/; then
  echo "[hermes-daily] no hermes changes today — nothing to commit"; exit 0
fi

# Refuse if anything outside docs/hermes/ somehow got staged (belt-and-suspenders)
OUTSIDE=$(git diff --cached --name-only | grep -v '^docs/hermes/' || true)
if [ -n "$OUTSIDE" ]; then
  echo "[hermes-daily] unexpected staged paths outside docs/hermes/ — aborting:"; echo "$OUTSIDE"
  git reset -q; exit 1
fi

N=$(git diff --cached --name-only | wc -l | tr -d ' ')
DATE=$(date '+%Y-%m-%d')
# The pre-commit secret hook runs here; a finding aborts the commit (non-zero) and we stop.
if git commit -q -m "hermes: auto-commit daily reports ($DATE, $N files)

Automated daily capture of docs/hermes/ self-learning artifacts (backlog_health / embedding_promotion_
reviews / librarian_loop_dryruns / observations). scripts/commit_hermes_daily.sh.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"; then
  echo "[hermes-daily] committed $N files"
  git push origin main 2>&1 | tail -2
  bash scripts/sync-docs-to-drive.sh >/dev/null 2>&1 && echo "[hermes-daily] drive synced"
else
  echo "[hermes-daily] commit blocked (secret hook or error) — left staged for review"
fi

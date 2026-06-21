#!/usr/bin/env bash
# Scheduled backup of generated docs to the `generated-docs-backup` branch.
#
# The generated docs (reports/briefs/status snapshots) are gitignored + untracked
# on main so they don't clutter dev diffs. This job snapshots their current
# on-disk state into a SEPARATE branch using git plumbing (commit-tree) — it never
# touches main's working tree, index, or HEAD, so it's safe to run anytime.
#
# Cron (daily, flock-guarded):
#   50 23 * * * cd $PROJ && bash linux_launchers/backup_generated_docs.sh >> logs/docs_backup.log 2>&1
set -uo pipefail

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ"
BR="generated-docs-backup"
TS="$(date '+%F %T')"

# single-instance
exec 9>/tmp/tradeai_docs_backup.lock
flock -n 9 || { echo "$TS skipped (locked)"; exit 0; }

# exact generated-doc paths (mirror the .gitignore "Generated/snapshot docs" block)
PATHS=(
  docs/governance/*latest*
  docs/maturity_hardening/*latest*
  docs/hermes/backlog_health
  docs/hermes/embedding_promotion_reviews
  docs/hermes/observations
  docs/hermes/librarian_loop_dryruns
  docs/openclaw_aegis_morning_brief_*.md
  docs/project/STATE_OF_REPO_LATEST.md
  docs/project/SYSTEM_FACTS_LATEST.md
)

# Build a tree from the current on-disk generated docs in an isolated temp index
# (-f overrides .gitignore). Globs that match nothing expand to themselves and are
# skipped via --ignore-unmatch / 2>/dev/null.
TMPIDX="$(mktemp)"; rm -f "$TMPIDX"
GIT_INDEX_FILE="$TMPIDX" git add -f --ignore-errors -- "${PATHS[@]}" 2>/dev/null || true
TREE="$(GIT_INDEX_FILE="$TMPIDX" git write-tree 2>/dev/null || true)"
rm -f "$TMPIDX"
if [ -z "${TREE:-}" ]; then echo "$TS nothing to back up"; exit 0; fi

PARENT="$(git rev-parse -q --verify "refs/heads/$BR" || true)"
if [ -n "$PARENT" ] && [ "$(git rev-parse "$PARENT^{tree}")" = "$TREE" ]; then
  echo "$TS no generated-doc changes"; exit 0
fi

MSG="docs: generated-docs backup $TS"
COMMIT="$(printf '%s\n' "$MSG" | git commit-tree "$TREE" ${PARENT:+-p "$PARENT"})"
git update-ref "refs/heads/$BR" "$COMMIT"

if git push -q origin "$BR" 2>/dev/null; then
  echo "$TS backed up $(git rev-parse --short "$COMMIT") -> origin/$BR"
else
  echo "$TS commit $(git rev-parse --short "$COMMIT") made locally; push FAILED (will retry next run)"
fi

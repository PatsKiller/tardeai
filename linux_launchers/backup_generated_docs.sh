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
#
# LOCAL ONLY by default (2026-10-10): the commit lands on the local `generated-docs-backup` branch and
# nothing is pushed. Operator-only push: `TRADEAI_REMOTE_PUSH_AUTHORIZED=1 bash
# linux_launchers/backup_generated_docs.sh --push` (both are required; cron passes neither).
set -uo pipefail

ALLOW_PUSH=0
for _arg in "$@"; do
  case "$_arg" in
    --push) ALLOW_PUSH=1 ;;
    *) echo "unknown argument: $_arg" >&2; exit 64 ;;
  esac
done

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ"
BR="generated-docs-backup"
TS="$(date '+%F %T')"
HOST="$(hostname -s 2>/dev/null || echo host)"

# Telegram failure ping (direct Bot API; token/chat from .env, first chat id only).
# No-op if not configured or disabled. Mirrors the repo's existing curl idiom.
tg_alert() {
  local msg="$1" enabled token chat
  enabled="$(grep -E '^ENABLE_TELEGRAM=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'\''[:space:]')"
  [ "${enabled:-true}" = "false" ] && return 0
  token="$(grep -E '^TELEGRAM_BOT_TOKEN=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'\''[:space:]')"
  chat="$(grep -E '^TELEGRAM_CHAT_ID=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'\''[:space:]')"
  chat="${chat%%,*}"
  [ -n "$token" ] && [ -n "$chat" ] || { echo "$TS [tg] not configured — alert skipped"; return 0; }
  curl -s --max-time 15 -X POST "https://api.telegram.org/bot${token}/sendMessage" \
    -d "chat_id=${chat}" -d "text=${msg}" >/dev/null 2>&1 \
    && echo "$TS [tg] failure alert sent" || echo "$TS [tg] alert curl failed"
}

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
COMMIT="$(printf '%s\n' "$MSG" | git commit-tree "$TREE" ${PARENT:+-p "$PARENT"} 2>/dev/null || true)"
if [ -z "${COMMIT:-}" ]; then
  echo "$TS commit-tree FAILED"
  tg_alert "🔴 docs-backup ($HOST): commit-tree failed — generated docs NOT backed up. Check logs/docs_backup.log."
  exit 1
fi
git update-ref "refs/heads/$BR" "$COMMIT"

SHORT="$(git rev-parse --short "$COMMIT")"
# Local-only by default (AGENTS.md §0 rule 4, AI_WORK_POLICY.md; 2026-10-10, cron L541): a checkpoint is
# a commit, not a push. The branch ref above IS the backup. A push to origin happens only when an
# operator runs this by hand with --push AND TRADEAI_REMOTE_PUSH_AUTHORIZED=1 in the environment.
if [ "${ALLOW_PUSH:-0}" != "1" ] || [ "${TRADEAI_REMOTE_PUSH_AUTHORIZED:-}" != "1" ]; then
  echo "$TS backed up $SHORT -> refs/heads/$BR (local only; push not authorized)"
  exit 0
fi
if git push -q origin "$BR" 2>/dev/null; then
  echo "$TS backed up $SHORT -> origin/$BR (operator-authorized push)"
else
  echo "$TS commit $SHORT made locally; authorized push FAILED"
  exit 1
fi

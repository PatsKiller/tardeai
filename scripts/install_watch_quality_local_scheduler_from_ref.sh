#!/usr/bin/env bash
set -euo pipefail

readonly ACK_REQUIRED="INSTALL_AND_RUN_BOUNDED_LOCAL_QUANT"
readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"
readonly SOURCE_REF="${WATCH_QUALITY_SOURCE_REF:-}"
readonly LIMIT="${WATCH_QUALITY_LOCAL_LIMIT:-20}"
readonly SCHEDULE_ROOT=/home/johnclaw/tradeai-scheduled
readonly LOG_DIR="$HOST_REPO/logs"
readonly BACKUP="$HOME/.crontab_backup_watch_quality_$(date -u +%Y%m%d_%H%M%S)"
readonly LOCK=/tmp/watch_quality_local_scheduler.lock

if [[ "${WATCH_QUALITY_SCHEDULE_ACK:-}" != "$ACK_REQUIRED" ]]; then
  echo "BLOCKED_GATE6: WATCH_QUALITY_SCHEDULE_ACK must equal $ACK_REQUIRED" >&2
  exit 2
fi
if [[ -z "$SOURCE_REF" || ! "$SOURCE_REF" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BLOCKED_GATE6: WATCH_QUALITY_SOURCE_REF must be an exact 40-character commit SHA" >&2
  exit 2
fi
if [[ ! "$LIMIT" =~ ^[0-9]+$ ]] || (( LIMIT < 1 || LIMIT > 40 )); then
  echo "BLOCKED_GATE6: WATCH_QUALITY_LOCAL_LIMIT must be 1..40" >&2
  exit 2
fi

git -C "$HOST_REPO" cat-file -e "$SOURCE_REF^{commit}"
readonly RESOLVED_COMMIT="$(git -C "$HOST_REPO" rev-parse "$SOURCE_REF^{commit}")"
if [[ "$RESOLVED_COMMIT" != "$SOURCE_REF" ]]; then
  echo "BLOCKED_GATE6: resolved commit differs from exact source ref" >&2
  exit 2
fi

mkdir -p "$SCHEDULE_ROOT" "$LOG_DIR"
chmod 700 "$SCHEDULE_ROOT"
readonly PINNED_RUNNER="$SCHEDULE_ROOT/watch-quality-local-${RESOLVED_COMMIT:0:12}.sh"
readonly MARKER="# tradeai-watch-quality-local-v1-${RESOLVED_COMMIT:0:12}"
readonly CRON_LINE="17 7 * * * flock -n $LOCK $PINNED_RUNNER >> $LOG_DIR/watch_quality_local_scheduler.log 2>&1 $MARKER"

cat > "$PINNED_RUNNER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
REPO="$HOST_REPO"
SHA="$RESOLVED_COMMIT"
RUNNER=\$(mktemp /tmp/watch-quality-local-pinned.XXXXXX.sh)
cleanup() { rm -f "\$RUNNER"; }
trap cleanup EXIT
git -C "\$REPO" cat-file -e "\$SHA^{commit}"
git -C "\$REPO" show "\$SHA:scripts/run_watch_quality_local_scheduler_from_ref.sh" > "\$RUNNER"
chmod 700 "\$RUNNER"
REPO="\$REPO" \
WATCH_QUALITY_SOURCE_REF="\$SHA" \
WATCH_QUALITY_SCHEDULER_MODE=RUN \
WATCH_QUALITY_LOCAL_LIMIT="$LIMIT" \
bash "\$RUNNER"
EOF
chmod 700 "$PINNED_RUNNER"

# Mandatory dry-run from the exact source before modifying the schedule.
DRY_RUNNER="$(mktemp /tmp/watch-quality-local-dryrun.XXXXXX.sh)"
cleanup() { rm -f "$DRY_RUNNER"; }
trap cleanup EXIT
git -C "$HOST_REPO" show \
  "$RESOLVED_COMMIT:scripts/run_watch_quality_local_scheduler_from_ref.sh" \
  > "$DRY_RUNNER"
chmod 700 "$DRY_RUNNER"
REPO="$HOST_REPO" \
WATCH_QUALITY_SOURCE_REF="$RESOLVED_COMMIT" \
WATCH_QUALITY_SCHEDULER_MODE=DRY_RUN \
WATCH_QUALITY_LOCAL_LIMIT="$LIMIT" \
bash "$DRY_RUNNER"

crontab -l > "$BACKUP" 2>/dev/null || :
chmod 600 "$BACKUP"
CURRENT="$(mktemp /tmp/watch-quality-crontab.XXXXXX)"
crontab -l > "$CURRENT" 2>/dev/null || :
if ! grep -Fq "$MARKER" "$CURRENT"; then
  printf '%s\n' "$CRON_LINE" >> "$CURRENT"
  crontab "$CURRENT"
fi
rm -f "$CURRENT"

# Enqueue one immediate bounded LOCAL_QUANT pass after installation.
flock -n "$LOCK" "$PINNED_RUNNER"

printf 'scheduler_source_commit|%s\n' "$RESOLVED_COMMIT"
printf 'scheduler_contract|watch-quality-local-scheduler-v1\n'
printf 'schedule|17 7 * * *\n'
printf 'local_limit|%s\n' "$LIMIT"
printf 'oauth_lane|WITHHELD\n'
printf 'paid_lane|WITHHELD\n'
printf 'crontab_backup|%s\n' "$BACKUP"
printf 'pinned_runner|%s\n' "$PINNED_RUNNER"
printf 'immediate_local_pass|ENQUEUED_OR_NOTHING_DUE\n'
printf 'final_status|PASS_GATE6_LOCAL_SCHEDULER_ACTIVATION\n'

#!/bin/bash
# cron_wrapper.sh — Universal cron failure notifier with Telegram alerts.
#
# Wraps any pipeline script. On failure: logs error, sends Telegram alert
# with script name + error + reply-to-retry command.
#
# Usage in crontab:
#   0 7 * * 1-5 /path/to/cron_wrapper.sh sentiment_processor ".venv/bin/python3 scripts/sentiment_processor.py"
#
# Args:
#   $1 = pipeline name (for alerts)
#   $2+ = command to run

set -o pipefail

if [[ "${1:-}" == "--wrapper-preflight" ]]; then
    # Explicit no-op protocol, BEFORE .env or any business command is read.
    PREFLIGHT_ROOT="${2:-}"
    [[ -n "$PREFLIGHT_ROOT" && -d "$PREFLIGHT_ROOT/scripts" ]] || exit 64
    PREFLIGHT_ROOT="$(cd "$PREFLIGHT_ROOT" && pwd -P)" || exit 64
    PREFLIGHT_LOGS="$(cd "$PREFLIGHT_ROOT/logs" && pwd -P)" || exit 64
    PREFLIGHT_RUN="$$-$(date +%s%N)"
    PREFLIGHT_HELPER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/lib/wrapper_events.py"
    for event in started completed; do
      python3 "$PREFLIGHT_HELPER" \
        --journal "$PREFLIGHT_LOGS/safe_flock_events.jsonl" --job-id cron_wrapper_preflight \
        --wrapper cron_wrapper --run-id "$PREFLIGHT_RUN" --mode preflight --event "$event" --exit-code 0 || exit 65
    done
    printf 'cron_wrapper preflight: release layout writable; no environment or producer loaded\n'
    exit 0
fi

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJ" || exit 1

# Load env
if [ -f "$PROJ/.env" ]; then
    export $(grep -v '^#' "$PROJ/.env" | grep '=' | xargs)
fi

PIPELINE_NAME="$1"
shift
COMMAND="$*"
WRAPPER_RUN_ID="$$-$(date +%s%N)"
WRAPPER_MODE=business
case " $COMMAND " in *--dry-run*|*--dry_run*|*--plan*) WRAPPER_MODE=dry_run ;; esac
wrapper_event() {
    python3 "$PROJ/scripts/lib/wrapper_events.py" --journal "$PROJ/logs/safe_flock_events.jsonl" \
      --job-id "$PIPELINE_NAME" --wrapper cron_wrapper --run-id "$WRAPPER_RUN_ID" --mode "$WRAPPER_MODE" \
      --event "$1" --exit-code "$2" 2>/dev/null \
      || printf 'cron_wrapper: telemetry unavailable (original command outcome preserved)\n' >&2
}
wrapper_event started 0
LOG_FILE="$PROJ/logs/${PIPELINE_NAME}.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Run the command, capture output and exit code
OUTPUT=$($COMMAND 2>&1)
EXIT_CODE=$?
wrapper_event completed "$EXIT_CODE"

# Always append to log
echo "[$TIMESTAMP] Exit: $EXIT_CODE" >> "$LOG_FILE"
echo "$OUTPUT" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

if [ $EXIT_CODE -ne 0 ]; then
    # Extract last 5 lines of error for the alert
    ERROR_TAIL=$(echo "$OUTPUT" | tail -5)

    # Send Telegram alert
    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        MSG=$(cat <<EOF
PIPELINE FAILURE: ${PIPELINE_NAME}
Exit code: ${EXIT_CODE}
Time: ${TIMESTAMP}

${ERROR_TAIL}

Reply to retry:
  run ${PIPELINE_NAME}
  status — system health
EOF
)
        # Body goes over stdin, never interpolated into Python source. ERROR_TAIL is
        # program output and can contain triple quotes, backslashes, backticks or
        # ${...} — inside a heredoc those escaped the string literal and executed.
        # Absolute paths + the project venv so the cron working directory is irrelevant.
        printf '%s' "$MSG" | "$PROJ/.venv/bin/python" \
            "$PROJ/scripts/send_operator_alert.py" \
            --source-producer cron_wrapper --quiet >/dev/null 2>&1 || true
    fi

    exit $EXIT_CODE
fi

# Print output for any downstream capture
echo "$OUTPUT"

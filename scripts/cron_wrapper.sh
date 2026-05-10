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

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJ" || exit 1

# Load env
if [ -f "$PROJ/.env" ]; then
    export $(grep -v '^#' "$PROJ/.env" | grep '=' | xargs)
fi

PIPELINE_NAME="$1"
shift
COMMAND="$*"
LOG_FILE="$PROJ/logs/${PIPELINE_NAME}.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Run the command, capture output and exit code
OUTPUT=$($COMMAND 2>&1)
EXIT_CODE=$?

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
        # Send to all chat IDs (comma-separated)
        IFS=',' read -ra CHAT_IDS <<< "$TELEGRAM_CHAT_ID"
        for CID in "${CHAT_IDS[@]}"; do
            CID=$(echo "$CID" | xargs)  # trim whitespace
            curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
                -d "chat_id=${CID}" \
                -d "text=${MSG}" \
                --max-time 10 > /dev/null 2>&1
        done
    fi

    exit $EXIT_CODE
fi

# Print output for any downstream capture
echo "$OUTPUT"

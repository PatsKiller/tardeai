#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
SCRIPTS="$ROOT/scripts"
OUTDIR="$ROOT/docs/atm_lifecycle_v1_2026_05_26/source_exports"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
GIT_COMMIT=$(cd "$ROOT" && git log --oneline -1 2>/dev/null | cut -d' ' -f1 || echo "UNKNOWN")
GIT_BRANCH=$(cd "$ROOT" && git branch --show-current 2>/dev/null || echo "unknown")

PATTERNS=(
  "*screener*" "*finviz*" "*news*" "*research*" "*social*" "*score*"
  "*critic*" "*orchestrator*" "*signal*" "*proposal*" "*atm*" "*risk*"
  "*capital*" "*allocation*" "*account*" "*alpaca*" "*broker*" "*paper*"
  "*execution*" "*quality*" "*slippage*" "*tca*" "*stop*" "*trailing*"
  "*time*" "*exit*" "*close*" "*backtest*" "*learn*" "*outcome*"
  "*journal*" "*raci*" "*agent*" "*alert*" "*telegram*" "*watchdog*"
  "*health*" "*monitor*" "*gate*" "*regime*" "*classify*" "*incubator*"
)

COUNT=0
TOTAL_SIZE=0

export_file() {
  local filepath="$1"
  local relpath="${filepath#$ROOT/}"
  local basename=$(basename "$filepath")
  local ext="${basename##*.}"
  local sha256=$(sha256sum "$filepath" | cut -d' ' -f1)
  local filesize=$(stat -c%s "$filepath")
  local safename=$(echo "$relpath" | tr '/' '_')
  local outfile="$OUTDIR/${safename%.${ext}}.md"

  cat > "$outfile" <<HEREDOC
# Source Export: ${relpath}

| Field | Value |
|-------|-------|
| **Original Path** | \`${relpath}\` |
| **Git Branch** | \`${GIT_BRANCH}\` |
| **Git Commit** | \`${GIT_COMMIT}\` |
| **Export Timestamp** | \`${TIMESTAMP}\` |
| **SHA256** | \`${sha256}\` |
| **File Size** | ${filesize} bytes |

## Full Source

\`\`\`${ext}
$(cat "$filepath")
\`\`\`
HEREDOC

  TOTAL_SIZE=$((TOTAL_SIZE + filesize))
  COUNT=$((COUNT + 1))
  echo "  Exported: ${relpath} (${filesize} bytes)"
}

echo "=== ATM Lifecycle Source Export ==="
echo "Timestamp: $TIMESTAMP"
echo "Git Commit: $GIT_COMMIT"
echo "Git Branch: $GIT_BRANCH"
echo ""

# Collect matching files (deduplicated)
declare -A SEEN

for pat in "${PATTERNS[@]}"; do
  for f in "$SCRIPTS"/${pat}.py "$SCRIPTS"/${pat}.sh; do
    if [[ -f "$f" ]]; then
      real=$(realpath "$f")
      if [[ -z "${SEEN[$real]:-}" ]]; then
        SEEN["$real"]=1
        export_file "$f"
      fi
    fi
  done
done

# Also export api_v2.py
API_FILE="$SCRIPTS/api_v2.py"
if [[ -f "$API_FILE" ]]; then
  export_file "$API_FILE"
else
  echo "WARNING: $API_FILE not found"
fi

echo ""
echo "=== Export Complete ==="
echo "Total files exported: $COUNT"
echo "Total source size: $TOTAL_SIZE bytes ($(echo "scale=2; $TOTAL_SIZE/1048576" | bc) MB)"

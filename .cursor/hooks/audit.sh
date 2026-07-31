#!/usr/bin/env bash
set -uo pipefail
LOG="${CURSOR_PROJECT_DIR:-.}/logs/cursor-agent-audit.jsonl"
mkdir -p "$(dirname "$LOG")" 2>/dev/null
jq -nc --argjson ev "$(cat)" --arg ts "$(date -Is)" '{ts:$ts} + $ev' >> "$LOG" 2>/dev/null
exit 0

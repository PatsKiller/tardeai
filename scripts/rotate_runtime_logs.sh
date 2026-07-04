#!/usr/bin/env bash
# rotate_runtime_logs.sh — size-based copytruncate rotation for logs/*.log
#
# Long-running processes hold these files open via '>>' (O_APPEND), so
# copytruncate is safe: archive the tail, truncate in place, writer keeps going.
# (2026-07-04: telegram_callback_poller.log had reached 1.4GB with no rotation.)
#
# Usage: rotate_runtime_logs.sh [--limit-mb N] [--keep N]
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
LIMIT_MB="${ROTATE_LIMIT_MB:-100}"
KEEP="${ROTATE_KEEP:-2}"          # rotated archives to keep per log
TAIL_MB="${ROTATE_TAIL_MB:-25}"   # how much recent history to preserve in the archive

while [ $# -gt 0 ]; do
  case "$1" in
    --limit-mb) LIMIT_MB="$2"; shift 2 ;;
    --keep) KEEP="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

rotated=0
for f in "$LOG_DIR"/*.log; do
  [ -f "$f" ] || continue
  size_mb=$(( $(stat -c%s "$f") / 1048576 ))
  [ "$size_mb" -lt "$LIMIT_MB" ] && continue
  ts="$(date +%Y%m%d-%H%M%S)"
  archive="${f%.log}.${ts}.log.gz"
  # Preserve only the recent tail — the head of a multi-GB log is dead weight.
  tail -c "$((TAIL_MB * 1048576))" "$f" | gzip > "$archive"
  truncate -s 0 "$f"
  echo "$(date '+%F %T') rotated $(basename "$f") (${size_mb}MB -> tail ${TAIL_MB}MB archived)"
  rotated=$((rotated + 1))
  # Prune old archives for this log beyond KEEP
  ls -t "${f%.log}".*.log.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
done
echo "$(date '+%F %T') rotate_runtime_logs: $rotated file(s) rotated (limit ${LIMIT_MB}MB)"

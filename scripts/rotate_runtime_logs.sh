#!/usr/bin/env bash
# rotate_runtime_logs.sh — size-based copytruncate rotation for logs/*.log
#
# Long-running processes hold these files open via '>>' (O_APPEND), so
# copytruncate is safe: archive the tail, truncate in place, writer keeps going.
# (2026-07-04: telegram_callback_poller.log had reached 1.4GB with no rotation.)
#
# 2026-10-21 (operator D8.1, registry-owned retention; AGENTS.md §0 rule 6): nothing is discarded.
#   * the HEAD of a log (everything before the recent tail) is gzipped to
#     <state>/archive/logs/<name>.<stamp>.gz, re-read and checked (byte count + sha256 of the
#     decompressed stream equal the head that was read), and a RetentionArchiveTripwire@v1 line is
#     appended to <state>/archive/logs/TRIPWIRE.jsonl BEFORE the log is truncated. A failed check
#     leaves the log untouched (not truncated) and the run exits non-zero.
#   * the recent tail keeps going to <log>.<stamp>.log.gz beside the log, as before; tail archives
#     beyond --keep are MOVED into <state>/archive/logs/ (with a tripwire line), no longer removed.
#   <state> is $TRADEAI_STATE_ROOT, else ~/trade-ai-releases/persistent-state (lib/retention_archive.state_root).
#
# Usage: rotate_runtime_logs.sh [--limit-mb N] [--keep N]
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROTATE_LOG_DIR:-$PROJECT_ROOT/logs}"
LIMIT_MB="${ROTATE_LIMIT_MB:-100}"
KEEP="${ROTATE_KEEP:-2}"          # rotated tail archives to keep beside each log
TAIL_MB="${ROTATE_TAIL_MB:-25}"   # how much recent history stays beside the log
STATE_ROOT="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"
ARCH_DIR="$STATE_ROOT/archive/logs"
TRIPWIRE="$ARCH_DIR/TRIPWIRE.jsonl"

while [ $# -gt 0 ]; do
  case "$1" in
    --limit-mb) LIMIT_MB="$2"; shift 2 ;;
    --keep) KEEP="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

tripwire_line() {  # archive_path kind bytes sha256
  printf '{"schema": "RetentionArchiveTripwire@v1", "kind": "%s", "writer": "rotate_runtime_logs", "table": null, "label": "logs", "archive": "%s", "manifest": null, "rows": null, "bytes": %s, "sha256": "%s", "archived_at": "%s", "fires_on": "any live reference to archive/logs (scripts/lib/retention_tripwire.py, read nightly by report_db_hygiene.py -> incident fan-in)"}\n' \
    "$2" "$1" "$3" "$4" "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)" >> "$TRIPWIRE"
  sync "$TRIPWIRE" 2>/dev/null || true
}

rotated=0
failed=0
for f in "$LOG_DIR"/*.log; do
  [ -f "$f" ] || continue
  size_b=$(stat -c%s "$f")
  size_mb=$(( size_b / 1048576 ))
  [ "$size_mb" -lt "$LIMIT_MB" ] && continue
  ts="$(date +%Y%m%d-%H%M%S)"
  name="$(basename "${f%.log}")"
  tail_b=$(( TAIL_MB * 1048576 ))
  head_b=$(( size_b > tail_b ? size_b - tail_b : 0 ))
  if [ "$head_b" -gt 0 ]; then
    mkdir -p "$ARCH_DIR"
    head_arch="$ARCH_DIR/${name}.${ts}.gz"
    want_sha=$(head -c "$head_b" "$f" | sha256sum | cut -d' ' -f1)
    head -c "$head_b" "$f" | gzip > "$head_arch.part"
    sync "$head_arch.part" 2>/dev/null || true
    got_b=$(gzip -dc "$head_arch.part" | wc -c)
    got_sha=$(gzip -dc "$head_arch.part" | sha256sum | cut -d' ' -f1)
    if [ "$got_b" != "$head_b" ] || [ "$got_sha" != "$want_sha" ]; then
      echo "$(date '+%F %T') ARCHIVE_VERIFY_FAILED $(basename "$f"): head ${head_b}B sha ${want_sha} != archive ${got_b}B sha ${got_sha}; NOT truncated (partial kept at $head_arch.part)" >&2
      failed=$((failed + 1))
      continue
    fi
    mv "$head_arch.part" "$head_arch"
    tripwire_line "$head_arch" "log_head" "$head_b" "$want_sha"
  fi
  archive="${f%.log}.${ts}.log.gz"
  # The recent tail (from the end of the archived head to EOF) stays beside the log.
  tail -c +"$(( head_b + 1 ))" "$f" | gzip > "$archive"
  truncate -s 0 "$f"
  echo "$(date '+%F %T') rotated $(basename "$f") (${size_mb}MB: head ${head_b}B archived -> ${ARCH_DIR}, tail kept beside the log)"
  rotated=$((rotated + 1))
  # Tail archives beyond KEEP move into the archive (never removed).
  while IFS= read -r old; do
    [ -n "$old" ] || continue
    mkdir -p "$ARCH_DIR"
    dest="$ARCH_DIR/$(basename "$old")"
    old_b=$(stat -c%s "$old")
    old_sha=$(sha256sum "$old" | cut -d' ' -f1)
    mv "$old" "$dest"
    tripwire_line "$dest" "log_tail" "$old_b" "$old_sha"
  done < <(ls -t "${f%.log}".*.log.gz 2>/dev/null | tail -n +$((KEEP + 1)))
done
echo "$(date '+%F %T') rotate_runtime_logs: $rotated file(s) rotated, $failed archive failure(s) (limit ${LIMIT_MB}MB)"
[ "$failed" -eq 0 ]

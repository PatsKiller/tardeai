#!/usr/bin/env bash
# Recycle telegram callback poller onto CURRENT release.
# Host-local helper. Prefer after promote. Does not stretch release-write:
# process signal/restart may still require a service/process-recycle grant.
set -euo pipefail
CUR="$(readlink -f "${HOME}/trade-ai-releases/portfolio-server/CURRENT")"
LAUNCH="${HOME}/.config/tradeai/bin/run_telegram_callback_poller_current.sh"
PIDFILE="/tmp/tradeai_telegram_poller.pid"
LOG="${CUR}/logs/telegram_poller_recycle.log"
mkdir -p "$(dirname "$LOG")"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

echo "$(ts) [recycle] CURRENT=${CUR}" >>"$LOG"

# Signal any poller whose cwd ≠ CURRENT (or deleted interpreter).
while read -r pid; do
  [[ -z "$pid" ]] && continue
  cwd="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || true)"
  exe="$(readlink "/proc/${pid}/exe" 2>/dev/null || true)"
  if [[ "$cwd" != "$CUR" || "$exe" == *"(deleted)"* ]]; then
    echo "$(ts) [recycle] signaling stale pid=${pid} cwd=${cwd:-?} exe=${exe:-?}" >>"$LOG"
    kill -TERM "$pid" 2>/dev/null || true
  else
    echo "$(ts) [recycle] already healthy pid=${pid}" >>"$LOG"
    exit 0
  fi
done < <(pgrep -f "run_telegram_callback_poller.py --daemon" || true)

# Wait briefly for exit so flock releases.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if ! pgrep -f "run_telegram_callback_poller.py --daemon" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

# Force-kill leftovers (still never unlink the flock inode).
while read -r pid; do
  [[ -z "$pid" ]] && continue
  echo "$(ts) [recycle] kill -9 leftover pid=${pid}" >>"$LOG"
  kill -9 "$pid" 2>/dev/null || true
done < <(pgrep -f "run_telegram_callback_poller.py --daemon" || true)

rm -f "$PIDFILE"
nohup bash "$LAUNCH" >>"$LOG" 2>&1 &
echo "$(ts) [recycle] launched launcher pid $!" >>"$LOG"
sleep 1
# Verify
ok=0
while read -r pid; do
  cwd="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || true)"
  if [[ "$cwd" == "$CUR" ]]; then
    echo "$(ts) [recycle] VERIFY_OK pid=${pid} cwd=$(basename "$cwd")" >>"$LOG"
    ok=1
  else
    echo "$(ts) [recycle] VERIFY_FAIL pid=${pid} cwd=${cwd:-?}" >>"$LOG"
  fi
done < <(pgrep -f "run_telegram_callback_poller.py --daemon" || true)
[[ "$ok" -eq 1 ]] || { echo "$(ts) [recycle] VERIFY_FAIL no CURRENT poller" >>"$LOG"; exit 1; }

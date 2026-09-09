#!/usr/bin/env bash
# Host-local watchdog: ensure poller cwd == CURRENT (not merely "a portfolio-server path").
# Lane A fix: stale 340aaf831-class processes must NOT count as healthy.
set -euo pipefail
CUR="$(readlink -f "${HOME}/trade-ai-releases/portfolio-server/CURRENT")"
LAUNCH="${HOME}/.config/tradeai/bin/run_telegram_callback_poller_current.sh"
RECYCLE="${HOME}/.config/tradeai/bin/recycle_telegram_poller.sh"
LOG="${CUR}/logs/telegram_poller_watchdog.log"
mkdir -p "$(dirname "$LOG")"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

healthy=0
stale=0
while read -r pid; do
  [[ -z "$pid" ]] && continue
  cwd="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || true)"
  exe="$(readlink "/proc/${pid}/exe" 2>/dev/null || true)"
  if [[ "$cwd" == "$CUR" && "$exe" != *"(deleted)"* ]]; then
    healthy=1
  else
    stale=1
    echo "$(ts) [watchdog] stale pid=${pid} cwd=${cwd:-?} exe=${exe:-?}" >>"$LOG"
  fi
done < <(pgrep -f "run_telegram_callback_poller.py --daemon" || true)

if [[ "$healthy" -eq 1 && "$stale" -eq 0 ]]; then
  exit 0
fi

echo "$(ts) [watchdog] recycle needed healthy=${healthy} stale=${stale}" >>"$LOG"
if [[ -x "$RECYCLE" ]]; then
  bash "$RECYCLE" >>"$LOG" 2>&1 || true
else
  # Fallback: TERM stale, clear pidfile, relaunch CURRENT.
  while read -r pid; do
    [[ -z "$pid" ]] && continue
    cwd="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || true)"
    if [[ "$cwd" != "$CUR" ]]; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done < <(pgrep -f "run_telegram_callback_poller.py --daemon" || true)
  sleep 1
  rm -f /tmp/tradeai_telegram_poller.pid
  nohup bash "$LAUNCH" >>"$LOG" 2>&1 &
  echo "$(ts) [watchdog] launched pid $!" >>"$LOG"
fi

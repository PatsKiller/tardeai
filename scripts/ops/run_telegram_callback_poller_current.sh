#!/usr/bin/env bash
# Host-local launcher: callback poller executes CURRENT release code, not a rebuild checkout.
# Not a git artifact. Survives CURRENT symlink changes only after this process is restarted.
# Lane A: if pidfile live but /proc/$PID/cwd ≠ CURRENT → signal exit so we can replace.
set -euo pipefail
CUR="$(readlink -f "${HOME}/trade-ai-releases/portfolio-server/CURRENT")"
PY="${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python"
LOCK="/tmp/tradeai_telegram_poller.lock"
PIDFILE="/tmp/tradeai_telegram_poller.pid"
LOG="${CUR}/logs/telegram_callback_poller.log"
SCRIPT="${CUR}/scripts/run_telegram_callback_poller.py"
mkdir -p "$(dirname "$LOG")"
[[ -x "$PY" ]] || { echo "missing venv python" >&2; exit 1; }
[[ -f "$SCRIPT" ]] || { echo "missing CURRENT poller script: $SCRIPT" >&2; exit 1; }

# Lane A wrapper harden: live pid with wrong cwd / deleted exe → ask it to exit.
if [[ -f "$PIDFILE" ]]; then
  OLD="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$OLD" ]] && kill -0 "$OLD" 2>/dev/null; then
    OLD_CWD="$(readlink -f "/proc/${OLD}/cwd" 2>/dev/null || true)"
    OLD_EXE="$(readlink "/proc/${OLD}/exe" 2>/dev/null || true)"
    if [[ "$OLD_CWD" != "$CUR" || "$OLD_EXE" == *"(deleted)"* ]]; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [launcher] stale pid=${OLD} cwd=${OLD_CWD:-?} exe=${OLD_EXE:-?} — TERM" >>"$LOG"
      kill -TERM "$OLD" 2>/dev/null || true
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        kill -0 "$OLD" 2>/dev/null || break
        sleep 0.3
      done
      kill -9 "$OLD" 2>/dev/null || true
      rm -f "$PIDFILE"
    fi
  elif [[ -n "$OLD" ]] && ! kill -0 "$OLD" 2>/dev/null; then
    rm -f "$PIDFILE"
  fi
fi

cd "$CUR"
# Secrets: host env files, then optional rebuild .env (tokens). Code path is CURRENT.
set -a
[[ -f "${HOME}/.config/tradeai/cio-telegram.env" ]] && . "${HOME}/.config/tradeai/cio-telegram.env"
[[ -f "${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env" ]] && . "${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env"
set +a
# m2-canary: Lane I inbound fails closed without sender allowlist
export COMMS_INBOUND_SENDER_ALLOWLIST="${COMMS_INBOUND_SENDER_ALLOWLIST:-8797974247,6993102664}"
export COMMS_GATEWAY_CANARY_CHATS="${COMMS_GATEWAY_CANARY_CHATS:-8797974247,6993102664}"
export PYTHONPATH="${CUR}:${CUR}/scripts${PYTHONPATH:+:$PYTHONPATH}"

# Never unlink the lock file. Unlink-while-held lets a second flock succeed
# on a newly created inode (Telegram getUpdates HTTP 409).
if [[ -f "$PIDFILE" ]]; then
  OLD="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$OLD" ]] && ! kill -0 "$OLD" 2>/dev/null; then
    rm -f "$PIDFILE"
  fi
fi

exec {fd}>"$LOCK" && flock -n "$fd" || exit 0
echo $$ >"$PIDFILE"
exec "$PY" -u "$SCRIPT" --daemon >>"$LOG" 2>&1

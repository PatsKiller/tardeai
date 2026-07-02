#!/usr/bin/env bash
# hermes_scalp_swarm_tmux.sh — tmux layout for Multi-Hermes Momentum Scalp swarm (MS-01)
# Usage: ./linux_launchers/hermes_scalp_swarm_tmux.sh [start|stop|status]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SESSION="hermes-scalp-swarm"
VENV="${ROOT}/.venv/bin/python3"

start_session() {
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Session $SESSION already running"
    return 0
  fi
  tmux new-session -d -s "$SESSION" -n orchestrator \
    "cd '$ROOT' && $VENV scripts/hermes_scalp_orchestrator.py --interval 60 2>&1 | tee -a logs/hermes_scalp_orchestrator.log"
  tmux new-window -t "$SESSION" -n live_monitor \
    "cd '$ROOT' && $VENV scripts/hermes_scalp_live_monitor.py --interval 30 2>&1 | tee -a logs/hermes_scalp_live_monitor.log"
  tmux new-window -t "$SESSION" -n signal_scout \
    "cd '$ROOT' && $VENV scripts/hermes_scalp_signal_scout.py --interval 45 2>&1 | tee -a logs/hermes_scalp_signal_scout.log"
  tmux new-window -t "$SESSION" -n entry_validation \
    "cd '$ROOT' && $VENV scripts/hermes_scalp_entry_validation.py --interval 60 2>&1 | tee -a logs/hermes_scalp_entry_validation.log"
  tmux new-window -t "$SESSION" -n health \
    "watch -n 15 'curl -s http://127.0.0.1:7777/api/v2/hermes/scalp-swarm/status | python3 -m json.tool | head -50'"
  echo "Started tmux session: $SESSION"
  echo "  attach: tmux attach -t $SESSION"
}

stop_session() {
  tmux kill-session -t "$SESSION" 2>/dev/null && echo "Stopped $SESSION" || echo "No session $SESSION"
}

case "${1:-start}" in
  start) start_session ;;
  stop)  stop_session ;;
  status) tmux list-sessions 2>/dev/null | grep -E "^$SESSION:" || echo "not running" ;;
  *) echo "Usage: $0 [start|stop|status]" ; exit 1 ;;
esac
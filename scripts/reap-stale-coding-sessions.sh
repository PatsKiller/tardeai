#!/usr/bin/env bash
# reap-stale-coding-sessions.sh — list (and optionally kill) stale interactive coding-agent processes
# (claude, codex) that linger for days holding a shell in the shared tree. Dry-run by default.
#
#   scripts/reap-stale-coding-sessions.sh                       # list; flag candidates older than 2d
#   scripts/reap-stale-coding-sessions.sh --older-than 5        # change the staleness threshold (days)
#   scripts/reap-stale-coding-sessions.sh --kill                # SIGTERM the flagged candidates
#   scripts/reap-stale-coding-sessions.sh --kill --older-than 7
#
# Safety: NEVER kills the current session's own process ancestry, and only targets `claude` / codex CLI
# processes (not the trade-ai server, python jobs, etc.). SIGTERM (not -9) so sessions exit cleanly.
set -uo pipefail

older_than=2
do_kill=0
while [ $# -gt 0 ]; do
  case "$1" in
    --older-than) older_than="${2:-2}"; shift 2 ;;
    --kill) do_kill=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# ancestry of THIS process — never reap ourselves
self_ancestry() {
  local pid=$$ guard=0
  while [ "$pid" -gt 1 ] && [ $guard -lt 40 ]; do
    echo "$pid"
    pid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    [ -z "$pid" ] && break
    guard=$((guard+1))
  done
}
mapfile -t ANCESTRY < <(self_ancestry)
is_ancestor() { local p="$1"; for a in "${ANCESTRY[@]}"; do [ "$a" = "$p" ] && return 0; done; return 1; }

# etime (elapsed) → days, from ps [[dd-]hh:]mm:ss
etime_days() {
  local e="$1" d=0
  case "$e" in *-*) d="${e%%-*}";; esac
  echo "$d"
}

printf '%-8s %-6s %-10s %-5s %s\n' PID PPID ELAPSED DAYS CMD
flagged=()
while read -r pid ppid etime cmd; do
  case "$cmd" in
    *"/claude"*|"claude"*|*"@openai/codex"*|*"/bin/codex"*) : ;;
    *) continue ;;
  esac
  days=$(etime_days "$etime")
  mark=""
  if [ "${days:-0}" -ge "$older_than" ] && ! is_ancestor "$pid"; then mark="  ← STALE (>${older_than}d)"; flagged+=("$pid"); fi
  is_ancestor "$pid" && mark="  ← this session (protected)"
  printf '%-8s %-6s %-10s %-5s %.60s%s\n' "$pid" "$ppid" "$etime" "$days" "$cmd" "$mark"
done < <(ps -eo pid=,ppid=,etime=,cmd= 2>/dev/null | grep -iE "claude|codex" | grep -v "reap-stale\|grep")

echo
if [ "${#flagged[@]}" -eq 0 ]; then echo "No stale candidates (>${older_than}d, excluding this session)."; exit 0; fi
echo "Stale candidates (>${older_than}d): ${flagged[*]}"
if [ "$do_kill" -eq 1 ]; then
  echo "Sending SIGTERM..."
  for p in "${flagged[@]}"; do kill "$p" 2>/dev/null && echo "  killed $p" || echo "  could not kill $p"; done
else
  echo "(dry-run) re-run with --kill to SIGTERM them."
fi

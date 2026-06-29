#!/usr/bin/env bash
# llm_priority_guard.sh — TIER priority gate for the shared local GPU/LLM.
#
# Returns 0 (PROCEED) when it is OK for a TIER-3 background/research LLM job to run, i.e. OUTSIDE the
# market-critical window. Returns 1 (DEFER) during 06:00-11:59 ET on trading days, so TIER-1 scalp /
# proposal / validation work gets the single local GPU during the early-momentum window.
#
# Usage in cron (T3 LLM jobs only):
#   ... && bash $PROJ/scripts/llm_priority_guard.sh && <the T3 LLM job>
# If the guard DEFERS, the job is skipped this tick (it will run on its next out-of-window tick).
#
# This does NOT touch any T1 job, gate, broker path, or 2FA. It only yields background LLM work to
# time-sensitive market work. Override with LLM_GUARD_FORCE=1 to run regardless (manual/debug).
set -euo pipefail

[ "${LLM_GUARD_FORCE:-0}" = "1" ] && exit 0

H=$(TZ=America/New_York date +%H)
DOW=$(TZ=America/New_York date +%u)   # 1=Mon .. 7=Sun
START="${LLM_GUARD_START_HOUR:-6}"
END="${LLM_GUARD_END_HOUR:-12}"       # exclusive

# 10#$H forces base-10 (leading-zero hours like 08 are not octal).
if [ "$DOW" -le 5 ] && [ "$((10#$H))" -ge "$START" ] && [ "$((10#$H))" -lt "$END" ]; then
  echo "$(date '+%F %T') [llm-priority-guard] DEFERRED — market-critical window ${START}:00-${END}:00 ET (T1 scalp/proposal priority on the local GPU)"
  exit 1
fi
exit 0

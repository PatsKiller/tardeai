#!/usr/bin/env bash
# Research Intelligence overnight / off-hours content update.
#
# Desk READ path (GET /api/v2/research-intelligence) stays live 24/7 from DB + cache.
# Heavy WRITE work (ingest, synthesize, LLM narrative, archive) runs only here —
# after close, overnight, and weekends — so market-hours CPU/GPU stays for trading.
#
# Cron (installed via install_research_intelligence_overnight_cron.sh):
#   30 20 * * 1-5  after-close batch
#   15  2 * * *    deep overnight
#   15  5 * * *    freshness + archive
#
# Usage:
#   bash scripts/run_research_intelligence_overnight.sh
#   bash scripts/run_research_intelligence_overnight.sh --phase archive
#   bash scripts/run_research_intelligence_overnight.sh --phase full
set -euo pipefail
cd "$(dirname "$0")/.."
PROJ="$(pwd)"
PY="${PROJ}/.venv/bin/python"
LOG_DIR="${PROJ}/logs"
mkdir -p "$LOG_DIR"
LOG="${LOG_DIR}/ri_overnight.log"
PHASE="full"
for a in "$@"; do
  case "$a" in
    --phase) shift; PHASE="${1:-full}" ;;
    --phase=*) PHASE="${a#--phase=}" ;;
  esac
done

ts() { date +%F\ %T; }
log() { echo "[ri_overnight] $(ts) $*" | tee -a "$LOG"; }

# Hard gate — never run mid-session even if cron is wrong
session=$($PY -c "
import sys; sys.path.insert(0,'scripts')
from market_session import current_market_session
print(current_market_session())
" 2>/dev/null || echo unknown)

case "$session" in
  regular|premarket)
    log "ABORT session=$session — RI content updates only outside RTH/premarket"
    exit 0
    ;;
esac

log "START phase=$PHASE session=$session"

run_step() {
  local name="$1"; shift
  log ">>> $name"
  if flock -n "/tmp/ri_overnight_${name}.lock" "$@"; then
    log "OK $name"
  else
    log "SKIP/FAIL $name (lock busy or exit non-zero)"
  fi
}

# 1) Soft-archive stale non-retirement Hermes rows (never deletes)
if [[ "$PHASE" == "full" || "$PHASE" == "archive" ]]; then
  run_step archive \
    $PY scripts/research_intelligence_refresh.py --archive >>"$LOG" 2>&1 || true
fi

# 2) Enqueue Hermes/shared topic_monitor → hermes_research_intelligence
if [[ "$PHASE" == "full" || "$PHASE" == "bridge" ]]; then
  run_step topic_bridge \
    $PY scripts/hermes_topic_monitor_bridge.py --apply --max-rows 60 >>"$LOG" 2>&1 || true
fi

# 3) LLM topic research synthesis (fills staged topic_research used by RI desk)
if [[ "$PHASE" == "full" || "$PHASE" == "synth" ]]; then
  if bash scripts/llm_priority_guard.sh; then
    run_step topic_synth \
      flock -n /tmp/topic_synth.lock \
      $PY scripts/topic_research_synthesizer.py --max 40 --apply >>"$LOG" 2>&1 || true
  else
    log "SKIP topic_synth — llm_priority_guard deferred"
  fi
fi

# 4) Optional reground of weak citations once crawler has material
if [[ "$PHASE" == "full" || "$PHASE" == "reground" ]]; then
  run_step reground \
    $PY scripts/topic_research_synthesizer.py --reground --max 25 --apply >>"$LOG" 2>&1 || true
fi

# 5) LLM narrative polish for desk cards (local → OAuth fallbacks)
if [[ "$PHASE" == "full" || "$PHASE" == "narrative" ]]; then
  run_step narrative \
    $PY scripts/research_intelligence_narrative_enrich.py --apply --limit 25 >>"$LOG" 2>&1 || true
fi

# 6) Topic crawl for never-searched / aging monitors (off-hours only)
if [[ "$PHASE" == "full" || "$PHASE" == "ingest" ]]; then
  run_step ingest \
    timeout 30m $PY scripts/topic_ingestion.py --use-llm-queries --max-topics 20 >>"$LOG" 2>&1 || true
fi

log "DONE phase=$PHASE"
exit 0

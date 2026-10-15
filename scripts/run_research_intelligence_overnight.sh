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
# Bounded work (lane repair 2026-10-15). The ingest step was SIGTERMed by `timeout 30m` (exit 124) every run:
# it rated every search result with one serial OAuth call (~11 s each, 331 calls on 2026-10-14) and had no
# per-run bound, so `--max-topics 20` needed hours. Now each LLM step carries a wall-clock budget below its
# outer timeout and a per-topic item cap; the step exits clean with a receipt and the next run resumes the
# stalest topics first. Values are environment-overridable (no hard-coded policy in the cron line):
#   RI_INGEST_TIMEOUT            outer kill backstop for the ingest step        (default 30m)
#   RI_INGEST_BUDGET_S           ingest wall-clock budget, < the timeout         (default 1500)
#   RI_INGEST_MAX_TOPICS         stalest topics considered per run               (default 20)
#   RI_INGEST_MAX_ITEMS_PER_TOPIC model-rated results per topic                  (default 12)
#   RI_NARRATIVE_LIMIT           narrative rows per run                          (default 25)
#   RI_NARRATIVE_BUDGET_S        narrative wall-clock budget                     (default 900)
#
# Lane receipt: run-research-intelligence-overnight_last.json (LaneRunReceipt@v1 + v2 output fields) sums
# produced_count / attempted_count / skipped_reasons from the ingest and narrative run receipts of THIS run.
#
# Usage:
#   bash scripts/run_research_intelligence_overnight.sh
#   bash scripts/run_research_intelligence_overnight.sh --phase archive
#   bash scripts/run_research_intelligence_overnight.sh --phase full
#   bash scripts/run_research_intelligence_overnight.sh --phase full --dry-run   # offline plan, no writes
set -euo pipefail
PHASE="full"
DRY_RUN=0
while (( $# )); do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --phase)
      if (( $# < 2 )); then echo "--phase requires a value" >&2; exit 2; fi
      PHASE="$2"; shift 2 ;;
    --phase=*) PHASE="${1#--phase=}"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$PHASE" in full|archive|bridge|synth|reground|narrative|ingest) ;; *) echo "unknown phase: $PHASE" >&2; exit 2 ;; esac

RI_INGEST_TIMEOUT="${RI_INGEST_TIMEOUT:-30m}"
RI_INGEST_BUDGET_S="${RI_INGEST_BUDGET_S:-1500}"
RI_INGEST_MAX_TOPICS="${RI_INGEST_MAX_TOPICS:-20}"
RI_INGEST_MAX_ITEMS_PER_TOPIC="${RI_INGEST_MAX_ITEMS_PER_TOPIC:-12}"
RI_NARRATIVE_LIMIT="${RI_NARRATIVE_LIMIT:-25}"
RI_NARRATIVE_BUDGET_S="${RI_NARRATIVE_BUDGET_S:-900}"

LANE="run-research-intelligence-overnight"
if [[ "$PHASE" == "archive" ]]; then LANE="run-research-intelligence-overnight-archive"; fi

in_phase() { [[ "$PHASE" == "full" || "$PHASE" == "$1" ]]; }

if (( DRY_RUN )); then
  # Offline plan: no gate, child, model, lock, log, DB or receipt (AGENTS.md §6). Prints the bounded plan only.
  steps=()
  in_phase archive && steps+=("archive")
  in_phase bridge && steps+=("topic_bridge(max-rows 60)")
  in_phase synth && steps+=("topic_synth(max 40; llm process topic_research_synthesizer)")
  in_phase reground && steps+=("reground(max 25; llm process topic_research_synthesizer)")
  in_phase narrative && steps+=("narrative(limit ${RI_NARRATIVE_LIMIT}, budget ${RI_NARRATIVE_BUDGET_S}s; llm process ri_narrative_enrich)")
  in_phase ingest && steps+=("ingest(max-topics ${RI_INGEST_MAX_TOPICS}, items/topic ${RI_INGEST_MAX_ITEMS_PER_TOPIC}, budget ${RI_INGEST_BUDGET_S}s inside timeout ${RI_INGEST_TIMEOUT}; llm process topic_ingestion)")
  echo "DRY-RUN ${LANE} phase=${PHASE}: would run ${#steps[@]} locked step(s) under the market/priority gates: ${steps[*]}; receipt ${LANE}_last.json sums produced_count from the ingest + narrative run receipts; no gate, child, model, lock, log, DB or writes now; inputs NOT_MEASURED"
  exit 0
fi
cd "$(dirname "$0")/.."
PROJ="$(pwd)"
. "$PROJ/scripts/lib/venv_python.sh"; PY="$(tradeai_venv_python "$PROJ")"  # release dirs ship no .venv
LOG_DIR="${PROJ}/logs"
mkdir -p "$LOG_DIR"
LOG="${LOG_DIR}/ri_overnight.log"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"

ts() { date +%F\ %T; }
# One copy per line: the cron line already appends this script's stdout to the same log, so `tee -a "$LOG"`
# wrote every line twice. Write the log; echo to the terminal only for an interactive run.
log() {
  local line="[ri_overnight] $(ts) $*"
  echo "$line" >> "$LOG"
  if [[ -t 1 ]]; then echo "$line"; fi
}

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

STATUS=0
OUTPUT_RECEIPTS=()
run_step() {
  local name="$1"; shift
  log ">>> $name"
  local rc=0
  flock -n -E 75 "/tmp/ri_overnight_${name}.lock" "$@" || rc=$?
  if (( rc == 0 )); then log "OK $name";
  elif (( rc == 75 )); then log "SKIP_LOCK $name"; if (( STATUS == 0 )); then STATUS=75; fi;
  else log "FAIL $name exit=$rc"; STATUS=1; fi
  "$PY" scripts/completion_compound_receipt.py --lane "$LANE" --step "$name" --exit "$rc" || true
}

# 1) Soft-archive stale non-retirement Hermes rows (never deletes)
if in_phase archive; then
  run_step archive \
    $PY scripts/research_intelligence_refresh.py --archive >>"$LOG" 2>&1
fi

# 2) Enqueue Hermes/shared topic_monitor → hermes_research_intelligence
if in_phase bridge; then
  run_step topic_bridge \
    $PY scripts/hermes_topic_monitor_bridge.py --apply --max-rows 60 >>"$LOG" 2>&1
fi

# 3) LLM topic research synthesis (fills staged topic_research used by RI desk)
if in_phase synth; then
  if bash scripts/llm_priority_guard.sh; then
    run_step topic_synth \
      flock -n /tmp/topic_synth.lock \
      $PY scripts/topic_research_synthesizer.py --max 40 --apply >>"$LOG" 2>&1
  else
    log "SKIP topic_synth — llm_priority_guard deferred"
  fi
fi

# 4) Optional reground of weak citations once crawler has material
if in_phase reground; then
  run_step reground \
    $PY scripts/topic_research_synthesizer.py --reground --max 25 --apply >>"$LOG" 2>&1
fi

# 5) LLM narrative polish for desk cards (governed OAuth grok → chatgpt; process ri_narrative_enrich)
if in_phase narrative; then
  run_step narrative \
    $PY scripts/research_intelligence_narrative_enrich.py --apply --limit "$RI_NARRATIVE_LIMIT" \
      --budget-s "$RI_NARRATIVE_BUDGET_S" >>"$LOG" 2>&1
  OUTPUT_RECEIPTS+=(--output-receipt "lane:ri-narrative-enrich")
fi

# 6) Topic crawl for never-searched / aging monitors (off-hours only). The budget ends the run cleanly before
#    the outer timeout; the timeout stays as the kill backstop.
if in_phase ingest; then
  run_step ingest \
    timeout "$RI_INGEST_TIMEOUT" $PY scripts/topic_ingestion.py --use-llm-queries \
      --max-topics "$RI_INGEST_MAX_TOPICS" --budget-s "$RI_INGEST_BUDGET_S" \
      --max-items-per-topic "$RI_INGEST_MAX_ITEMS_PER_TOPIC" >>"$LOG" 2>&1
  OUTPUT_RECEIPTS+=(--output-receipt "$PROJ/data/runtime/topic_ingestion_run_latest.json")
fi

log "DONE phase=$PHASE status=$STATUS"
"$PY" scripts/completion_compound_receipt.py --lane "$LANE" --exit "$STATUS" --since "$STARTED_AT" \
  "${OUTPUT_RECEIPTS[@]}" || true
exit "$STATUS"

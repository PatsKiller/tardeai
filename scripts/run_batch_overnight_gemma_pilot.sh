#!/usr/bin/env bash
# run_batch_overnight_gemma_pilot.sh — Phase 1D overnight gemma3-overnight pilot
#
# Runs multi_strategy_classifier.py with gemma3-overnight as the local model.
# Handles GPU lifecycle: evict qwen → load gemma → run pilot → restore qwen + nomic.
# Fails closed: if qwen restore fails, exits non-zero and alerts.
#
# Usage:
#   ./scripts/run_batch_overnight_gemma_pilot.sh              # default: --limit 1
#   ./scripts/run_batch_overnight_gemma_pilot.sh --limit 2    # 2 symbols
#   ./scripts/run_batch_overnight_gemma_pilot.sh --limit 5    # max allowed (Phase 1D)
#
# NOT scheduled via cron. Run manually or by operator only.
# ────────────────────────────────────────────────────────────────────────────

set -euo pipefail

PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/gemma_overnight_pilot.log"
OLLAMA_URL="http://localhost:11434"

# Pilot parameters
PILOT_MODEL="gemma3-overnight"
RESTORE_MODEL="qwen3:14b"
EMBED_MODEL="nomic-embed-text:latest"
PILOT_TIMEOUT="10m"
MAX_LIMIT=5

# Parse --limit N argument (default 1, max 5)
LIMIT_N=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --limit)
            LIMIT_N="${2:-1}"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

if ! [[ "$LIMIT_N" =~ ^[0-9]+$ ]] || [ "$LIMIT_N" -lt 1 ]; then
    echo "ERROR: --limit must be a positive integer, got '$LIMIT_N'" >&2
    exit 1
fi
if [ "$LIMIT_N" -gt "$MAX_LIMIT" ]; then
    echo "ERROR: --limit $LIMIT_N exceeds Phase 1D max of $MAX_LIMIT" >&2
    exit 1
fi
LIMIT="--limit $LIMIT_N"

# ── Logging ──────────────────────────────────────────────────────────────
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [pilot] $*" | tee -a "$LOG"; }

# ── GPU helpers ──────────────────────────────────────────────────────────
gpu_ps() {
    curl -s "$OLLAMA_URL/api/ps" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
for m in d.get('models',[]):
    v=round(m.get('size_vram',0)/1024/1024/1024,2)
    t=round(m.get('size',0)/1024/1024/1024,2)
    print(f'  {m[\"name\"]:30s}  total={t}GB  vram={v}GB')
" 2>/dev/null || echo "  (ollama unreachable)"
}

unload_model() {
    curl -s -X POST "$OLLAMA_URL/api/generate" \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"$1\",\"keep_alive\":0,\"prompt\":\"\"}" \
        --max-time 15 > /dev/null 2>&1
    sleep 2
}

warmup_model() {
    local result
    result=$("$PY" -c "
import sys; sys.path.insert(0, '$PROJ/scripts')
from gpu_lifecycle import warmup
r = warmup('$1')
print(r.get('status', 'unknown'))
" 2>&1)
    echo "$result"
}

warmup_embed() {
    curl -s -X POST "$OLLAMA_URL/api/embeddings" \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"$EMBED_MODEL\",\"prompt\":\"test\"}" \
        --max-time 15 > /dev/null 2>&1
}

# ── Safety check ─────────────────────────────────────────────────────────
log "=== Phase 1D Overnight Pilot Start (limit=$LIMIT_N, max=$MAX_LIMIT) ==="
log "Checking safety..."

ALPACA_MODE=$(grep -oP '(?<=ALPACA_MODE=)\S+' "$PROJ/.env" 2>/dev/null || echo "")
LLM_DISABLE=$(grep -oP '(?<=LLM_DISABLE_LIVE_EXECUTION=)\S+' "$PROJ/.env" 2>/dev/null || echo "")

if [ "$ALPACA_MODE" != "paper" ]; then
    log "ABORT: ALPACA_MODE=$ALPACA_MODE (expected paper)"
    exit 1
fi
if [ "$LLM_DISABLE" != "true" ]; then
    log "ABORT: LLM_DISABLE_LIVE_EXECUTION=$LLM_DISABLE (expected true)"
    exit 1
fi

HOLDINGS_OK=$("$PY" -c 'import json; d=json.load(open("'"$PROJ"'/data/portfolios/state/holdings.json")); v=d["portfolio_totals"]["total_value"]; assert v>1000000; print("OK")' 2>&1 || echo "FAIL")
if [ "$HOLDINGS_OK" != "OK" ]; then
    log "ABORT: Holdings guard failed"
    exit 1
fi
log "Safety: ALPACA_MODE=paper, LLM_DISABLE=true, holdings OK"

# ── Active hours gate ────────────────────────────────────────────────────
ACTIVE=$("$PY" -c "
import sys; sys.path.insert(0, '$PROJ/scripts')
from gpu_lifecycle import is_active_hours
print('yes' if is_active_hours() else 'no')
" 2>&1)

if [ "$ACTIVE" = "yes" ]; then
    log "ABORT: Active market hours — refusing BATCH_OVERNIGHT"
    exit 1
fi
log "Active hours gate: PASSED (outside market hours)"

# ── Record pre-swap GPU state ────────────────────────────────────────────
log "GPU state BEFORE swap:"
gpu_ps | tee -a "$LOG"

# ── Evict qwen3:14b ─────────────────────────────────────────────────────
log "Evicting $RESTORE_MODEL..."
unload_model "$RESTORE_MODEL"

# Verify eviction
STILL_LOADED=$(curl -s "$OLLAMA_URL/api/ps" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
for m in d.get('models',[]):
    if 'qwen3' in m.get('name',''):
        print('yes')
        sys.exit()
print('no')
" 2>&1)

if [ "$STILL_LOADED" = "yes" ]; then
    log "WARNING: qwen3 still resident after eviction attempt, proceeding anyway"
fi

# ── Run pilot ────────────────────────────────────────────────────────────
PILOT_EXIT=0
log "Starting pilot: LOCAL_LLM_MODEL=$PILOT_MODEL multi_strategy_classifier.py --batch --llm $LIMIT"
log "Timeout: $PILOT_TIMEOUT"

timeout "$PILOT_TIMEOUT" env \
    LOCAL_LLM_MODEL="$PILOT_MODEL" \
    "$PY" "$PROJ/scripts/multi_strategy_classifier.py" \
    --batch --llm $LIMIT \
    >> "$LOG" 2>&1 || PILOT_EXIT=$?

if [ "$PILOT_EXIT" -eq 124 ]; then
    log "TIMEOUT: Pilot exceeded $PILOT_TIMEOUT runtime cap"
elif [ "$PILOT_EXIT" -ne 0 ]; then
    log "PILOT FAILED with exit code $PILOT_EXIT"
else
    log "PILOT COMPLETED successfully"
fi

# ── GPU state after pilot ────────────────────────────────────────────────
log "GPU state AFTER pilot:"
gpu_ps | tee -a "$LOG"

# ── Unload gemma3-overnight ──────────────────────────────────────────────
log "Unloading $PILOT_MODEL..."
unload_model "$PILOT_MODEL"

# ── Restore qwen3:14b ───────────────────────────────────────────────────
log "Restoring $RESTORE_MODEL..."
RESTORE_STATUS=$(warmup_model "$RESTORE_MODEL")
if [ "$RESTORE_STATUS" != "ok" ]; then
    log "CRITICAL: Failed to restore $RESTORE_MODEL — status=$RESTORE_STATUS"
    log "Attempting emergency restore..."
    # Second attempt
    sleep 5
    RESTORE_STATUS=$(warmup_model "$RESTORE_MODEL")
    if [ "$RESTORE_STATUS" != "ok" ]; then
        log "CRITICAL: Emergency restore FAILED. Manual intervention required."
        log "Run: .venv/bin/python -c \"import sys;sys.path.insert(0,'scripts');from gpu_lifecycle import warmup;print(warmup('qwen3:14b'))\""
        exit 2
    fi
fi
log "Restored $RESTORE_MODEL: status=$RESTORE_STATUS"

# ── Restore nomic-embed-text ────────────────────────────────────────────
log "Restoring $EMBED_MODEL..."
warmup_embed
log "Restored $EMBED_MODEL"

# ── Final GPU state ──────────────────────────────────────────────────────
log "GPU state AFTER restore:"
gpu_ps | tee -a "$LOG"

# ── Summary ──────────────────────────────────────────────────────────────
log "=== Phase 1D Overnight Pilot Complete (limit=$LIMIT_N) ==="
log "Pilot exit code: $PILOT_EXIT"
log "qwen3 restore: $RESTORE_STATUS"

exit "$PILOT_EXIT"

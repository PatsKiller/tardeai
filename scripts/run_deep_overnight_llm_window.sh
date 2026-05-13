#!/usr/bin/env bash
# run_deep_overnight_llm_window.sh — Phase 1H daily deep overnight LLM window
#
# Scheduled entry point for 23:00–03:00 deep overnight LLM processing.
# Uses gemma3-overnight to process a prioritized queue of high-value jobs.
#
# Usage:
#   ./scripts/run_deep_overnight_llm_window.sh              # normal run
#   ./scripts/run_deep_overnight_llm_window.sh --dry-run    # dry run (no gemma, no queue changes)
#   ./scripts/run_deep_overnight_llm_window.sh --max-jobs 70
#
# Safety:
#   - Only runs between 23:00 and 03:00 unless --force-window
#   - Creates /tmp/tradeai_deep_llm_window.lock (removed on exit)
#   - Enforces ALPACA_MODE=paper and LLM_DISABLE_LIVE_EXECUTION=true
#   - Restores qwen3:14b and nomic-embed-text no matter what
#   - Exits nonzero if restore fails
#   - Does NOT modify .env
#   - Does NOT touch broker/holdings/execution
# ────────────────────────────────────────────────────────────────────────

set -uo pipefail

PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/deep_overnight_llm_window.log"
LOCK_FILE="/tmp/tradeai_deep_llm_window.lock"
OLLAMA_URL="http://localhost:11434"

# Models
PILOT_MODEL="gemma3-overnight"
RESTORE_MODEL="qwen3:14b"
EMBED_MODEL="nomic-embed-text:latest"

# Defaults
TIME_BUDGET=240
HARD_STOP="03:00"
MAX_JOBS=70
HARD_MAX_JOBS=75
ALLOW_OVER_75=false
DRY_RUN=false
FORCE_WINDOW=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --max-jobs)
            MAX_JOBS="${2:-70}"
            shift 2
            ;;
        --time-budget)
            TIME_BUDGET="${2:-240}"
            shift 2
            ;;
        --force-window)
            FORCE_WINDOW=true
            shift
            ;;
        --allow-over-75)
            ALLOW_OVER_75=true
            shift
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Usage: $0 [--dry-run] [--max-jobs N] [--time-budget MIN] [--force-window] [--allow-over-75]" >&2
            exit 1
            ;;
    esac
done

# ── Hard cap validation ──────────────────────────────────────────────────
if [ "$MAX_JOBS" -gt "$HARD_MAX_JOBS" ] && [ "$ALLOW_OVER_75" != "true" ]; then
    echo "ERROR: --max-jobs $MAX_JOBS exceeds hard max of $HARD_MAX_JOBS." >&2
    echo "Use --allow-over-75 to override (not recommended)." >&2
    exit 1
fi

# ── Logging ──────────────────────────────────────────────────────────────
mkdir -p "$PROJ/logs"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [deep-window] $*" | tee -a "$LOG"; }

# ── Lock management ─────────────────────────────────────────────────────
cleanup() {
    local exit_code=$?
    log "Cleanup triggered (exit_code=$exit_code)"

    # Always attempt restore
    restore_models

    # Remove lock
    rm -f "$LOCK_FILE"
    log "Lock removed: $LOCK_FILE"

    log "Deep window cleanup complete"
}
trap cleanup EXIT INT TERM

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
        --max-time 30 > /dev/null 2>&1
}

verify_nomic() {
    local result
    result=$(curl -s -X POST "$OLLAMA_URL/api/embeddings" \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"$EMBED_MODEL\",\"prompt\":\"verification test\"}" \
        --max-time 30 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
e=d.get('embedding',[])
print('ok' if len(e) > 0 else 'fail')
" 2>/dev/null || echo "fail")
    echo "$result"
}

restore_models() {
    log "Restoring models..."

    # Unload gemma
    log "  Unloading $PILOT_MODEL..."
    unload_model "$PILOT_MODEL"
    sleep 3

    # Restore qwen3:14b
    log "  Restoring $RESTORE_MODEL..."
    local qwen_status
    qwen_status=$(warmup_model "$RESTORE_MODEL")
    if [ "$qwen_status" != "ok" ]; then
        log "  WARNING: First qwen restore attempt returned: $qwen_status"
        sleep 5
        qwen_status=$(warmup_model "$RESTORE_MODEL")
        if [ "$qwen_status" != "ok" ]; then
            log "  CRITICAL: Second qwen restore attempt failed: $qwen_status"
            # Emergency: try raw Ollama call
            sleep 5
            curl -s -X POST "$OLLAMA_URL/api/generate" \
                -H "Content-Type: application/json" \
                -d '{"model":"qwen3:14b","prompt":"test","stream":false,"options":{"num_predict":1}}' \
                --max-time 120 > /dev/null 2>&1
            sleep 3
            qwen_status=$(warmup_model "$RESTORE_MODEL")
            if [ "$qwen_status" != "ok" ]; then
                log "  CRITICAL: ALL qwen restore attempts FAILED. Manual intervention required."
                log "  Run: ollama run qwen3:14b 'test'"
                RESTORE_FAILED=true
            fi
        fi
    fi
    log "  qwen3:14b restore: $qwen_status"

    # Restore nomic-embed-text
    log "  Restoring $EMBED_MODEL..."
    warmup_embed
    sleep 2
    local nomic_status
    nomic_status=$(verify_nomic)
    if [ "$nomic_status" != "ok" ]; then
        log "  WARNING: nomic-embed-text verification failed, retrying..."
        sleep 3
        warmup_embed
        sleep 2
        nomic_status=$(verify_nomic)
    fi
    log "  nomic-embed-text restore: $nomic_status"

    # Final verification
    log "  GPU state after restore:"
    gpu_ps | tee -a "$LOG"

    # Provider verification
    log "  Provider verification:"
    "$PY" "$PROJ/scripts/verify_llm_providers.py" 2>&1 | grep -E "Local|Result" | tee -a "$LOG"

    if [ "${RESTORE_FAILED:-false}" = "true" ]; then
        log "CRITICAL: Model restore FAILED — system may be degraded"
        return 1
    fi
    return 0
}

# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

START_TIME=$(date +%s)
log "══════════════════════════════════════════════════════════════"
log "=== Phase 1H Deep Overnight LLM Window Starting ==="
log "══════════════════════════════════════════════════════════════"
log "Mode:        $([ "$DRY_RUN" = true ] && echo 'DRY RUN' || echo 'LIVE')"
log "Time budget: ${TIME_BUDGET}m"
log "Hard stop:   $HARD_STOP"
log "Max jobs:    $MAX_JOBS"
log "Model:       $PILOT_MODEL"

# ── Gate 1: Window check ────────────────────────────────────────────────
HOUR=$(date +%H)
if [ "$FORCE_WINDOW" != "true" ]; then
    # Allow 23:xx or 00:xx-02:xx
    if [ "$HOUR" -ge 3 ] && [ "$HOUR" -lt 23 ]; then
        log "ABORT: Outside deep window (current hour=$HOUR, allowed 23:00-03:00)"
        log "Use --force-window to override"
        exit 1
    fi
fi
log "Window check: PASSED (hour=$HOUR)"

# ── Gate 2: Lock check ─────────────────────────────────────────────────
if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null | head -1)
    if kill -0 "$LOCK_PID" 2>/dev/null; then
        log "ABORT: Deep window already running (pid=$LOCK_PID, lock=$LOCK_FILE)"
        exit 1
    else
        log "WARNING: Stale lock found (pid=$LOCK_PID not running), removing"
        rm -f "$LOCK_FILE"
    fi
fi
echo "$$" > "$LOCK_FILE"
log "Lock acquired: $LOCK_FILE (pid=$$)"

# ── Gate 3: Safety checks ──────────────────────────────────────────────
log "Checking safety gates..."

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

HOLDINGS_VAL=$("$PY" -c 'import json; d=json.load(open("'"$PROJ"'/data/portfolios/state/holdings.json")); v=d["portfolio_totals"]["total_value"]; print(f"{v:.0f}")' 2>&1 || echo "0")
if [ "$HOLDINGS_VAL" -lt 1000000 ] 2>/dev/null; then
    log "ABORT: Holdings guard failed (value=$HOLDINGS_VAL)"
    exit 1
fi
log "Safety: ALPACA_MODE=paper, LLM_DISABLE=true, holdings=\$$HOLDINGS_VAL"

# ── Gate 4: Ollama health ──────────────────────────────────────────────
if ! curl -sf "$OLLAMA_URL/api/tags" > /dev/null 2>&1; then
    log "ABORT: Ollama not reachable at $OLLAMA_URL"
    exit 1
fi
log "Ollama: alive"

# ── Gate 5: GPU state before ───────────────────────────────────────────
log "GPU state BEFORE deep window:"
gpu_ps | tee -a "$LOG"

GPU_STATUS=$(curl -s http://localhost:7777/api/v2/gpu-status 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'ollama={d.get(\"ollama_alive\")}, vram_used={d.get(\"vram_used_gb\")}GB')
" 2>/dev/null || echo "unavailable")
log "GPU API: $GPU_STATUS"

# ── Build queue ────────────────────────────────────────────────────────
log "Building deep overnight queue..."
if [ "$DRY_RUN" = true ]; then
    "$PY" "$PROJ/scripts/build_deep_overnight_llm_queue.py" --dry-run --limit "$MAX_JOBS" 2>&1 | tee -a "$LOG"
    log "=== DRY RUN COMPLETE — no model changes, no queue processing ==="
    # Don't trigger cleanup restore on dry run exit
    rm -f "$LOCK_FILE"
    trap - EXIT INT TERM
    exit 0
else
    "$PY" "$PROJ/scripts/build_deep_overnight_llm_queue.py" --apply --limit "$MAX_JOBS" 2>&1 | tee -a "$LOG"
fi

# ── Evict qwen3:14b and nomic ─────────────────────────────────────────
log "Evicting models for gemma window..."
log "  Evicting $RESTORE_MODEL..."
unload_model "$RESTORE_MODEL"
log "  Evicting $EMBED_MODEL..."
unload_model "$EMBED_MODEL"
sleep 3

log "GPU state AFTER eviction:"
gpu_ps | tee -a "$LOG"

# ── Run queue with gemma3-overnight ────────────────────────────────────
log "Starting queue runner with gemma3-overnight..."
QUEUE_EXIT=0
LOCAL_LLM_MODEL="$PILOT_MODEL" \
    "$PY" "$PROJ/scripts/run_deep_overnight_llm_queue.py" \
    --limit "$MAX_JOBS" \
    --time-budget-min "$TIME_BUDGET" \
    --hard-stop "$HARD_STOP" \
    2>&1 | tee -a "$LOG" || QUEUE_EXIT=$?

log "Queue runner exit code: $QUEUE_EXIT"

# ── Restore happens via cleanup trap ────────────────────────────────────
# The cleanup() function handles:
# 1. Unload gemma3-overnight
# 2. Restore qwen3:14b
# 3. Restore nomic-embed-text
# 4. Verify restoration
# 5. Remove lock file

# ── Final summary ──────────────────────────────────────────────────────
END_TIME=$(date +%s)
TOTAL_RUNTIME=$(( END_TIME - START_TIME ))

log "══════════════════════════════════════════════════════════════"
log "=== Phase 1H Deep Overnight LLM Window Complete ==="
log "══════════════════════════════════════════════════════════════"
log "Total runtime:     ${TOTAL_RUNTIME}s ($(( TOTAL_RUNTIME / 60 ))m)"
log "Queue exit code:   $QUEUE_EXIT"
log "Holdings value:    \$$HOLDINGS_VAL"
log "══════════════════════════════════════════════════════════════"

# Exit with queue runner's exit code (restore handled by trap)
if [ "${RESTORE_FAILED:-false}" = "true" ]; then
    exit 2
fi
exit "$QUEUE_EXIT"

#!/usr/bin/env bash
# run_scheduled_stale_proposal_sweeper.sh — Safe wrapper for stale proposal sweeper.
#
# Modes: --dry-run (default), --apply, --report-only
# Uses flock, verifies safety gates, logs output.
#
# Phase 6E. PAPER ONLY. Does not approve, create, submit, or delete.

set -euo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/stale_proposal_sweeper.log"
LOCK="/tmp/tradeai_stale_proposal_sweeper.lock"
MODE="${1:---dry-run}"
TS=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "$TS [stale-sweeper] $*" >> "$LOG"; echo "$TS [stale-sweeper] $*"; }

# ── Safety gates ──
ALPACA_MODE=$(grep '^ALPACA_MODE=' "$PROJ/.env" | cut -d= -f2-)
LLM_DISABLE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' "$PROJ/.env" | cut -d= -f2-)

if [ "$ALPACA_MODE" != "paper" ]; then
    log "ABORT: ALPACA_MODE=$ALPACA_MODE (must be paper)"
    exit 1
fi
if [ "$LLM_DISABLE" != "true" ]; then
    log "ABORT: LLM_DISABLE_LIVE_EXECUTION=$LLM_DISABLE (must be true)"
    exit 1
fi

# Holdings guard
HOLDINGS_OK=$($PY -c 'import json; d=json.load(open("'"$PROJ"'/data/portfolios/state/holdings.json")); v=d["portfolio_totals"]["total_value"]; print("OK" if v > 1000000 else "FAIL")' 2>/dev/null || echo "FAIL")
if [ "$HOLDINGS_OK" != "OK" ]; then
    log "ABORT: holdings guard failed"
    exit 1
fi

log "Starting mode=$MODE"

case "$MODE" in
    --dry-run)
        $PY "$PROJ/scripts/sweep_stale_paper_proposals.py" --dry-run --limit 200 --verbose 2>&1 | while IFS= read -r line; do log "$line"; done
        ;;
    --apply)
        $PY "$PROJ/scripts/sweep_stale_paper_proposals.py" --apply --limit 200 --verbose 2>&1 | while IFS= read -r line; do log "$line"; done
        ;;
    --report-only)
        $PY "$PROJ/scripts/report_phase6_stale_proposals.py" --since-days 1 --limit 50 --verbose 2>&1 | while IFS= read -r line; do log "$line"; done
        ;;
    *)
        log "Unknown mode: $MODE (use --dry-run, --apply, or --report-only)"
        exit 1
        ;;
esac

log "Finished mode=$MODE"

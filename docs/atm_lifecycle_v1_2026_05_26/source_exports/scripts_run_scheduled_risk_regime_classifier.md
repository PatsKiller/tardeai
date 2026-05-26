# Source Export: scripts/run_scheduled_risk_regime_classifier.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/run_scheduled_risk_regime_classifier.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `2c6c519da1c72a58cb620cfec32908549079b41c74d9ddd0d6052a5e87642ac2` |
| **File Size** | 2988 bytes |

## Full Source

```sh
#!/usr/bin/env bash
# REGIME-CRON-1: Scheduled risk-regime collect + classify + rotation signals.
# Proposal-only. No auto-rotation. No trades. No orders. No strategy activation.
# Exit codes: 0=success, 1=safety-abort, 99=flock-skip
set -euo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
set -a; source "$PROJ/.env"; set +a
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/regime_classifier.log"
LOCK="/tmp/tradeai_regime_classifier.lock"
TS=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "$TS [regime-classifier] $*" >> "$LOG"; echo "$TS [regime-classifier] $*"; }

# Safety guards
ALPACA_MODE=$(grep '^ALPACA_MODE=' "$PROJ/.env" | cut -d= -f2-)
LLM_DISABLE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' "$PROJ/.env" | cut -d= -f2-)
[ "$ALPACA_MODE" != "paper" ] && { log "ABORT: ALPACA_MODE=$ALPACA_MODE"; exit 1; }
[ "$LLM_DISABLE" != "true" ] && { log "ABORT: LLM_DISABLE=$LLM_DISABLE"; exit 1; }

# Holdings guard
HOLDINGS_OK=$($PY -c 'import json; d=json.load(open("'"$PROJ"'/data/portfolios/state/holdings.json")); print("OK" if d["portfolio_totals"]["total_value"] > 1000000 else "FAIL")' 2>/dev/null || echo "FAIL")
[ "$HOLDINGS_OK" != "OK" ] && { log "ABORT: holdings guard failed"; exit 1; }

log "Starting"

# Flock — skip if previous instance running
exec {fd}>"$LOCK" && flock -n "$fd" || {
    log "Locked, skipping"
    $PY -c "import sys; sys.path.insert(0,'$PROJ/scripts'); from pipeline_run_telemetry import record_stage_run; from datetime import datetime,timezone; record_stage_run('regime_classifier','Governance','skipped',datetime.now(timezone.utc),datetime.now(timezone.utc),source='cron_flock_blocked')" 2>/dev/null || true
    exit 0
}

_TELEM_START=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)

# Step 1: Collect fresh indicators
set +e
$PY "$PROJ/scripts/market_regime_collector.py" --apply 2>&1 | while IFS= read -r line; do log "collector: $line"; done
_C_EXIT=$?; set -e
[ $_C_EXIT -ne 0 ] && { log "Collector failed (exit=$_C_EXIT)"; }

# Step 2: Classify regime and write snapshot
set +e
$PY "$PROJ/scripts/market_regime_classifier.py" --apply --verbose 2>&1 | while IFS= read -r line; do log "classifier: $line"; done
_CL_EXIT=$?; set -e
[ $_CL_EXIT -ne 0 ] && { log "Classifier failed (exit=$_CL_EXIT)"; }

# Step 3: Generate rotation signals (proposal-only, no auto-apply)
set +e
$PY "$PROJ/scripts/strategy_rotation_engine.py" --apply 2>&1 | while IFS= read -r line; do log "rotation: $line"; done
_R_EXIT=$?; set -e
[ $_R_EXIT -ne 0 ] && { log "Rotation engine failed (exit=$_R_EXIT)"; }

# Telemetry
_TELEM_STATUS="success"
[ $_C_EXIT -ne 0 ] || [ $_CL_EXIT -ne 0 ] && _TELEM_STATUS="failed"
$PY -c "import sys; sys.path.insert(0,'$PROJ/scripts'); from pipeline_run_telemetry import record_stage_run; from datetime import datetime,timezone; record_stage_run('regime_classifier','Governance','$_TELEM_STATUS',datetime.fromisoformat('$_TELEM_START'),datetime.now(timezone.utc),source='cron')" 2>/dev/null || true

log "Finished ($_TELEM_STATUS)"
```

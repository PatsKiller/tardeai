#!/bin/bash
# Phase 194 — Protection learning pipeline orchestrator.
# Runs the read-only/advisory protection chain in dependency order. Paper-only.
# NONE of these place/modify/cancel orders or touch GO/WAIT/strategy/live. The only
# write that can modify a paper order (apply_paper_protection_adjustment.py) is NOT here —
# it runs only on explicit operator approval.
set -uo pipefail
# Resolve the tree from this script's own location (dev tree OR a promoted release dir — the cron
# runs it from $PROJ=…/portfolio-server/CURRENT, where the old hard-coded dev-tree path silently ran
# the DEV copy of every step). Release dirs have no .venv, so the interpreter is resolved like
# scripts/market_day_gate.sh: the caller's $PY (crontab exports it), a local .venv, then the
# canonical venv under $HOME, then python3.
PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJ" || exit 1
PY_RESOLVED=""
for cand in "${PY:-}" "$PROJ/.venv/bin/python" "$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python"; do
    [ -n "$cand" ] && [ -x "$cand" ] && { PY_RESOLVED="$cand"; break; }
done
[ -n "$PY_RESOLVED" ] || PY_RESOLVED="$(command -v python3 || true)"
PY="$PY_RESOLVED"
LOG="$PROJ/logs/protection_pipeline.log"
ts() { date -u '+%Y-%m-%d %H:%M:%S UTC'; }
# Capture the step's exit status BEFORE anything else runs: the old `|| echo "[$(ts)] WARN … rc=$?"`
# expanded $(ts) first, so $? was ts's own status and every failure logged rc=0.
run() {
    echo "[$(ts)] >>> $1" >> "$LOG"
    local rc=0
    "$PY" "scripts/$1" >> "$LOG" 2>&1 || rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "[$(ts)] WARN $1 rc=$rc" >> "$LOG"
        FAILED=$((FAILED + 1))
    fi
}
FAILED=0
if [ -z "$PY" ]; then
    echo "[$(ts)] ERROR no python interpreter found (PY unset, no .venv) — pipeline not run" >> "$LOG"
    exit 1
fi

echo "[$(ts)] === protection pipeline start ===" >> "$LOG"
run verify_paper_trade_broker_stops.py                # persist/verify broker stop metadata (190B)
run trade_execution_analyzer.py                       # MFE/MAE (percent) on newly closed trades (194)
run profit_protection_advisory.py                     # TradeAI advisories (191)
run hermes_profit_protection_check.py                 # Hermes second opinion (191E)
run generate_paper_protection_adjustment_proposals.py # adjustment proposals (192D)
run reconcile_protection_advisory_outcomes.py         # close-loop outcomes (193/194)
run tune_advisory_thresholds.py                       # threshold tuning backtest (198)
run prune_protection_proposals_retention.py           # prune old SUPERSEDED rows (bounded retention)
echo "[$(ts)] === protection pipeline done (failed_steps=$FAILED) ===" >> "$LOG"

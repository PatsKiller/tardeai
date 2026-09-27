#!/usr/bin/env bash
# Alpaca PAPER options lane — poll fills/closes (read-only; no order submit).
set -euo pipefail
# C-02 (2026-09-26): PROJECT_ROOT and PY are overridable so the cron can pin this lane to the
# served release (cd CURRENT) while keeping the shared venv (releases ship no .venv).
PROJECT_ROOT="${PROJECT_ROOT:-${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
PY="${PY:-.venv/bin/python}"
cd "$PROJECT_ROOT"
set -a
source "$PROJECT_ROOT/.env" 2>/dev/null || true
set +a
mkdir -p logs
exec bash scripts/safe_flock.sh /tmp/tradeai_alpaca_options_reconcile.lock \
  "$PY" scripts/alpaca_paper_options_executor.py --reconcile \
  >> logs/alpaca_paper_options_reconcile.log 2>&1
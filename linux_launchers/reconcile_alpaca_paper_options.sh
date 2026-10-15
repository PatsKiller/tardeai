#!/usr/bin/env bash
# Alpaca PAPER options lane — poll fills/closes (read-only; no order submit).
# n8n onboarding F09 (operator N8N Cutover Decision 2026-10-15; staged under AGENTS.md §23.14 until 12.0.0 is
# ratified): --dry-run is OFFLINE and wins over every live argument. It runs before any cd, .env source, lock,
# interpreter or broker call, makes NO broker call (not even a read) and writes nothing; it prints the plan and one
# LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run_requires_broker_read). Bash builtins only.
# Proof: tests/test_onboard_f09_b4_20261015.py.
if [[ " $* " == *" --dry-run "* ]]; then
    _f09_lane="reconcile-alpaca-paper-options"
    printf 'DRY-RUN %s: would %s; argv=%s; dry-run wins over live arguments; broker read required to plan: nothing done; nothing read, no broker call, no send, no file write\n' \
        "$_f09_lane" "poll Alpaca PAPER option fills and closes (--reconcile; no order submit) and record them" "$*"
    TZ=UTC printf 'LANE_OUTPUT {"attempted_count": 0, "emitted_at": "%(%Y-%m-%dT%H:%M:%S+00:00)T", "empty_reason": "%s", "lane_id": "%s", "mode": "dry_run", "pid": %d, "produced_count": 0, "schema": "LaneOutput@v1", "skipped_reasons": {}, "started_at": null, "unit": "%s"}\n' \
        -1 "dry_run_requires_broker_read" "$_f09_lane" "$$" "paper options fills reconciled" >&2
    exit 0
fi

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
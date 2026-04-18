#!/usr/bin/env bash
# run_lookthrough.sh
# Monthly look-through data refresh + sector resolution.
# Called by portfolio-lookthrough systemd timer (1st Sunday of each month, 6AM).

set -euo pipefail

PROJECT_ROOT="${1:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
LOG_DIR="$PROJECT_ROOT/logs/phase3"
TS="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/run_lookthrough_${TS}.log"

echo "[lookthrough] Starting $(date)" | tee -a "$LOG"
echo "[lookthrough] Project root: $PROJECT_ROOT" | tee -a "$LOG"

# Iron rule: validate holdings before any run
HOLDINGS="$PROJECT_ROOT/data/portfolios/state/holdings.json"
TOTAL=$(python3 -c "import json; d=json.load(open('$HOLDINGS')); print(d['portfolio_totals']['total_value'])" 2>/dev/null || echo "0")
COUNT=$(python3 -c "import json; d=json.load(open('$HOLDINGS')); print(len(d.get('holdings',[])))" 2>/dev/null || echo "0")
echo "[lookthrough] Holdings: total=\$${TOTAL} count=${COUNT}" | tee -a "$LOG"
if [ "$COUNT" = "0" ] || [ "$TOTAL" = "0" ]; then
  echo "SAFETY ABORT: holdings empty" | tee -a "$LOG"
  exit 1
fi

cd "$PROJECT_ROOT"
source .venv/bin/activate

echo "[lookthrough] Step 1: Fetching fund/ETF data..." | tee -a "$LOG"
python3 scripts/phase3_lookthrough_fetcher.py --project-root . 2>&1 | tee -a "$LOG"

echo "[lookthrough] Step 2: Running look-through sector resolver..." | tee -a "$LOG"
python3 scripts/phase3_lookthrough_resolver.py --project-root . 2>&1 | tee -a "$LOG"

echo "[lookthrough] Step 3: Coverage audit..." | tee -a "$LOG"
python3 scripts/phase2_coverage_audit.py --project-root . 2>&1 | tee -a "$LOG"

echo "[lookthrough] Done $(date)" | tee -a "$LOG"
echo "[lookthrough] Log: $LOG"

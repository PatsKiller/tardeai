#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
LOG_DIR="$PROJECT_ROOT/logs"
STAMP="$(date '+%Y%m%d-%H%M%S')"
LOG_FILE="$LOG_DIR/run_price_cache-$STAMP.log"
mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT"
source .venv/bin/activate
{
  echo "[PRICE-CACHE] Refreshing Yahoo price cache..."
  python scripts/portfolio_price_cache.py --project-root .
  # After fresh prices, regenerate performance history with updated data
  echo "[PRICE-CACHE] Regenerating performance history with fresh prices..."
  python -c "
import sys, json
sys.path.insert(0, 'scripts')
from pathlib import Path
from portfolio_performance_history import compute_period_returns
portfolio = json.load(open('data/portfolios/state/holdings.json'))
state_dir = Path('data/portfolios/state')
result = compute_period_returns(portfolio, state_dir)
ph_path = state_dir / 'performance_history.json'
ph_path.write_text(json.dumps(result, indent=2))
avail = [p for p,d in result.get('periods',{}).items() if d and d.get('change_pct') is not None]
print(f'  [PRICE-CACHE] performance_history.json updated — {len(avail)} periods')
" || echo "[PRICE-CACHE] performance history update skipped (non-fatal)"
  # Backfill per-account periods with fresh prices
  echo "[PRICE-CACHE] Updating per-account period returns..."
  python backfill_acct_periods_v3.py || echo "[PRICE-CACHE] backfill skipped (non-fatal)"
} 2>&1 | tee "$LOG_FILE"

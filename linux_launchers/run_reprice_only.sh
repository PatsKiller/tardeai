#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
cd "$PROJECT_ROOT"
source .venv/bin/activate
STAMP="$(date '+%Y%m%d-%H%M%S')"
LOG_DIR="$PROJECT_ROOT/logs/ui_runs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/reprice-only-$STAMP.log"
{
  echo "[REPRICE] Starting repricing-only refresh..."
  echo "[REPRICE] $(date '+%F %T')"
  python3 - <<'PY'
from pathlib import Path
import shutil, sys
root = Path('.').resolve()
sys.path.insert(0, str(root / 'scripts'))
from portfolio_loader import load_all_portfolios, save_state
from portfolio_repricer import reprice_portfolio
portfolio = load_all_portfolios(str(root))
save_state(portfolio, str(root))
state_dir = root / 'data' / 'portfolios' / 'state'
portfolio = reprice_portfolio(portfolio, state_dir)
save_state(portfolio, str(root))
src = root / 'data' / 'portfolios' / 'reports' / 'portfolio_live.html'
dst = root / 'reports' / 'portfolio_live.html'
if src.exists():
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)
print('Repricing/state save complete')
PY
  echo "[REPRICE] Complete"
} | tee -a "$LOG_FILE"

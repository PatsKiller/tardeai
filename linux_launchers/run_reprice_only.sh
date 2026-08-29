#!/usr/bin/env bash
# Reprice-only refresh.
#
# 2026-08-29: repointed at the SERVED tree. This script used to do
# `cd $PROJECT_ROOT` and `root = Path('.')`, so both code and data came from
# the v12-rebuild checkout — a tree portfolio_server does not read. The served
# holdings.json is $DATA_ROOT/data/portfolios/state/holdings.json, which is a
# symlink into persistent-state. The two had drifted:
#
#     $PROJECT_ROOT  value 1,286,407.66  cash 578,107.50
#     served         value 1,287,999.68  cash 630,784.82
#
# and $PROJECT_ROOT/scripts/portfolio_repricer.py predates #641, so it also
# mis-classified the Fidelity rollover as ACCOUNT_RECONCILIATION_RESIDUAL
# instead of CLOSED_ROLLED_TO. Code AND data now come from DATA_ROOT.
#
# PROJECT_ROOT is still used for the venv and .env (the served tree has no
# .env of its own, and the repricer's _load_env(root) would find nothing).
set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
DATA_ROOT="${DATA_ROOT:-$HOME/trade-ai-releases/portfolio-server/CURRENT}"

cd "$PROJECT_ROOT"
source .venv/bin/activate

# Fail loudly rather than silently repricing the wrong tree — the bug this fixes.
if [[ ! -d "$DATA_ROOT/scripts" || ! -d "$DATA_ROOT/data/portfolios/state" ]]; then
  echo "[REPRICE] FATAL: DATA_ROOT=$DATA_ROOT is not a served tree" >&2
  exit 1
fi

# .env lives in PROJECT_ROOT; export so the repricer sees FINVIZ_API_TOKEN et al.
# Without this it prices 0/31 symbols and still reports success.
set -a; . "$PROJECT_ROOT/.env"; set +a
export TRADEAI_ROOT="$DATA_ROOT"

STAMP="$(date '+%Y%m%d-%H%M%S')"
LOG_DIR="$PROJECT_ROOT/logs/ui_runs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/reprice-only-$STAMP.log"
{
  echo "[REPRICE] Starting repricing-only refresh..."
  echo "[REPRICE] $(date '+%F %T')"
  echo "[REPRICE] data root: $DATA_ROOT"
  python3 - "$DATA_ROOT" "$PROJECT_ROOT" <<'PY'
from pathlib import Path
import shutil, sys
root = Path(sys.argv[1]).resolve()
project_root = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(root / 'scripts'))
from portfolio_loader import load_all_portfolios, save_state
from portfolio_repricer import reprice_portfolio
portfolio = load_all_portfolios(str(root))
save_state(portfolio, str(root))
state_dir = root / 'data' / 'portfolios' / 'state'
portfolio = reprice_portfolio(portfolio, state_dir)
save_state(portfolio, str(root))
# Source moves with the data; destination stays in PROJECT_ROOT so existing
# consumers of $PROJECT_ROOT/reports keep working, and a promote cannot
# overwrite it.
src = root / 'data' / 'portfolios' / 'reports' / 'portfolio_live.html'
dst = project_root / 'reports' / 'portfolio_live.html'
if src.exists():
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)
print('Repricing/state save complete')
PY
  echo "[REPRICE] Complete"
} | tee -a "$LOG_FILE"

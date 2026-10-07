#!/usr/bin/env bash
# Daily strategy + ATM parity audits (post-close). Exit non-zero on hard failures.
set -euo pipefail
# 2026-10-07 (cron tranche B step 1): default to the tree this script lives in, env PROJ still wins.
PROJ="${PROJ:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$PROJ"
PY="${PY:-$PROJ/.venv/bin/python}"   # the crontab exports PY (shared venv); the served tree has no .venv
[ -x "$PY" ] || { echo "run_scheduled_strategy_audits: PY not executable: $PY (export PY as the crontab does)" >&2; exit 78; }
LOG="${LOG:-$PROJ/logs/strategy_audits.log}"
TS="$(date -Iseconds)"

fail=0
{
  echo "=== strategy audits $TS ==="
  echo "--- audit_automated_open_trades ---"
  if ! "$PY" scripts/audit_automated_open_trades.py; then
    echo "FAIL: audit_automated_open_trades"
    fail=1
  fi
  echo "--- audit_proposal_source_parity ---"
  parity="$("$PY" scripts/audit_proposal_source_parity.py)"
  echo "$parity"
  if ! echo "$parity" | "$PY" -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('all_biases_fixed') else 1)"; then
    echo "FAIL: audit_proposal_source_parity all_biases_fixed=false"
    fail=1
  fi
  echo "=== done exit=$fail ==="
} >> "$LOG" 2>&1

exit "$fail"
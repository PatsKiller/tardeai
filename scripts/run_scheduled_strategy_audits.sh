#!/usr/bin/env bash
# Daily strategy + ATM parity audits (post-close). Exit non-zero on hard failures.
set -euo pipefail
PROJ="${PROJ:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
cd "$PROJ"
PY="${PY:-$PROJ/.venv/bin/python}"
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
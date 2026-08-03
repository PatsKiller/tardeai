#!/usr/bin/env bash
# check_ops_constitution.sh — lightweight ops constitution guard for CI
# Validates key rules; exits 0 on pass, 1 on violations.

set -euo pipefail

OP_MODE=0
if [[ "${1:-}" == "--ops-constitution" ]]; then OP_MODE=1; fi
[[ "$OP_MODE" -eq 1 ]] || exit 0

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${HERE}/.."
PG="apps/command-center-v3/src/pages"
CO="apps/command-center-v3/src/components"
OP_PAGES="$PG/HealthHub.tsx $PG/ConsumptionHub.tsx $PG/SystemHub.tsx $PG/RetirementHub.tsx"
OP_COMPS="$CO/health/HealthAgentsDashboard.tsx $CO/health/CoderDispatchLedger.tsx $CO/risk/RiskHealthStrip.tsx $CO/DataSourceHealth.tsx"
violations=0
w=0

green(){ echo -e "\033[32m  $*\033[0m"; }
amber(){ echo -e "\033[33m  $*\033[0m"; ((w++)) || true; }
red(){   echo -e "\033[31m  $*\033[0m"; ((violations++)) || true; }

echo "[ops-constitution] scanning $(echo $OP_PAGES | wc -w) pages + $(echo $OP_COMPS | wc -w) components..."

# R1: Freshness indicator (captured_at/last_run/polling/freshness label)
for f in $OP_PAGES; do
  [[ -f "$REPO/$f" ]] || continue
  hits=$(grep -cE "(captured_at|last_run|generated_at|last used|Last used|poll:|pollMs|refresh|Refresh|Freshness|freshness|last run|Last run)" "$REPO/$f" 2>/dev/null || echo 0)
  [[ "$hits" -gt 0 ]] && green "R1 ✓ $(basename $f) ($hits freshness refs)" || amber "R1 ✗ $(basename $f) — no freshness/polling/timestamp indicator"
done

# R2: Score thresholds visible
for f in $OP_PAGES $OP_COMPS; do
  [[ -f "$REPO/$f" ]] || continue
  has_score=$(grep -cE "(scoreColor|/100|overall_score|\\.score)" "$REPO/$f" 2>/dev/null || echo 0)
  has_thold=$(grep -cE "(threshold|>= 85|>= 65|\"healthy\"|\"degraded\"|title=.*score|title=.*thres)" "$REPO/$f" 2>/dev/null || echo 0)
  if [[ "$has_score" -gt 0 && "$has_thold" -eq 0 ]]; then
    amber "R2 ✗ $(basename $f) — scores without threshold visibility"
  elif [[ "$has_score" -gt 0 ]]; then
    green "R2 ✓ $(basename $f)"
  fi
done

# R3: Finding feed items have actions
for f in $OP_PAGES $OP_COMPS; do
  [[ -f "$REPO/$f" ]] || continue
  findings=$(grep -cE "(findings|Finding|finding)" "$REPO/$f" 2>/dev/null || echo 0)
  actions=$(grep -cE "(onClick|remediate|Fix now|Route to|Bulk|BULK)" "$REPO/$f" 2>/dev/null || echo 0)
  if [[ "$findings" -gt 3 && "$actions" -eq 0 ]]; then
    amber "R3 ✗ $(basename $f) — findings present but no action buttons"
  elif [[ "$findings" -gt 3 ]]; then
    green "R3 ✓ $(basename $f) ($actions action refs for $findings finding refs)"
  fi
done

# R4: Backend agents log to DB
for agent in health_agent.py watchlist_health_agent.py pipeline_health_agent.py system_freshness_monitor.py; do
  f="$REPO/scripts/$agent"
  [[ -f "$f" ]] || continue
  db_hits=$(grep -cE "(_db\(|CREATE TABLE|INSERT INTO|system_health_events|health_agent_snapshots)" "$f" 2>/dev/null || echo 0)
  [[ "$db_hits" -gt 0 ]] && green "R4 ✓ $agent (DB logging: $db_hits refs)" || amber "R4 ✗ $agent — no DB logging detected"
done

# R5: Visual hierarchy — hero present
for f in $OP_PAGES; do
  [[ -f "$REPO/$f" ]] || continue
  score_refs=$(grep -cE "(Score|score|hubTitle|hubSubtitle)" "$REPO/$f" 2>/dev/null || echo 0)
  [[ "$score_refs" -gt 0 ]] && green "R5 ✓ $(basename $f)" || amber "R5 ✗ $(basename $f) — no title/score hierarchy"
done

# R6: Data source doc-comments on useApi
for f in $OP_PAGES; do
  [[ -f "$REPO/$f" ]] || continue
  api_calls=$(grep -c "useApi.*'/api/" "$REPO/$f" 2>/dev/null || echo 0)
  comments=$(grep -cE "(Fetched from|Source:|GET /api|data source:|Endpoint:)" "$REPO/$f" 2>/dev/null || echo 0)
  if [[ "$api_calls" -gt 2 && "$comments" -eq 0 ]]; then
    amber "R6 ✗ $(basename $f) — $api_calls useApi calls without source comments"
  elif [[ "$api_calls" -gt 0 ]]; then
    green "R6 ✓ $(basename $f) ($api_calls api calls, $comments source comments)"
  fi
done

# Summary
echo ""
if [[ $violations -eq 0 ]]; then
  green "[ops-constitution] PASS ($w advisory notes)"
  exit 0
else
  red "[ops-constitution] FAIL — $violations violation(s), $w advisory notes"
  exit 1
fi

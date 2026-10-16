#!/usr/bin/env bash
# CW1 step 2 (cron grant as TRADEAI_FABRIC_GRANT): effect-key owner rows -> n8n for the keyed lanes, so the n8n
# executor's claim (n8n_claim true) is admitted and a cron line wrapped by effect_claim_cron.sh (cron_claim true) is
# fenced. Without an owner row every live run of a keyed lane is refused effect_no_owner (fail closed).
#   bash 02_effect_owners.sh [--apply]
set -euo pipefail
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
PY=${PY:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}
for lane in agent-outcome-linker catalyst-symbol-impact document-mentions-backfill etf-analyst-enrich etf-performance-enrich feedback-loop-processor finviz-proactive-research finviz-screener-runner hermes-analyst-signal-discovery hermes-momentum-catalyst-scalp hermes-news-bridge journal-tilt-morning-hook material-change-detector-stage1 proposal-backtest-engine sec-data-ingest source-attribution-monitor update-agent-performance watchlist-enrichment-sweep; do
  proc=$("$PY" "$SERVED/scripts/lib/effect_claim.py" lane-spec --lane "$lane" 2>/dev/null | cut -f1 || true)
  [[ -n "$proc" ]] || proc=$lane
  cur=$("$PY" "$SERVED/scripts/lib/effect_claim.py" show --process "$proc" | "$PY" -c 'import json,sys; o=json.load(sys.stdin).get("owner"); print("none none" if not o else "%s %s" % (o["owner"], o["epoch"]))')
  read -r owner epoch <<<"$cur"
  if [[ "$owner" == "n8n" ]]; then echo "  $proc already n8n (epoch $epoch)"; continue; fi
  ARGS=(set-owner --process "$proc" --owner n8n --by "operator:${TRADEAI_FABRIC_GRANT:-dry}" --note "CW1 canary")
  [[ "$epoch" != "none" ]] && ARGS+=(--expect-epoch "$epoch")
  if [[ "${1:-}" != "--apply" ]]; then echo "  DRY RUN: effect_claim.py ${ARGS[*]}"; continue; fi
  [[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || { echo "REFUSED: TRADEAI_FABRIC_GRANT not set"; exit 1; }
  "$PY" "$SERVED/scripts/lib/effect_claim.py" "${ARGS[@]}"
done

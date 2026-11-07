#!/usr/bin/env bash
# W5 step 1 (config-write + service grants): add this wave's lanes to the relay/gateway live list, restart the relay.
#   bash 01_relay_live_lanes.sh            dry run: prints the new list
#   bash 01_relay_live_lanes.sh --apply    backup, write, read back, restart tradeai-n8n-run-relay
# Run ONLY after `readlink -f ~/trade-ai-releases/portfolio-server/CURRENT` names a release that contains this wave.
set -euo pipefail
F=${LIVE_LANES_ENV:-$HOME/.config/tradeai/n8n-live-lanes.env}
ADD="reconcile-pullback-outcomes build-hermes-canonical-status directive-keyword-enhancer fee-efficiency-analyzer overnight-batch-tax finviz-market-movers hermes-usefulness-backfill ask-alerts sec-filings-feed tmp-scratch-cleanup reconcile-watch-outcomes aegis-evening-packet validate-expense-ratios journal-review-builder proposal-llm-review-worker social-scalp-scanner active-trader-session-review enrich-proposal-technicals hermes-discovery-ingestors news-ingestion-tail sec-fundamentals-ingest agent-calibration-engine reclassify-momentum-proposals generate-analyst-reports-autonomous-weekly due-diligence-questions"
CUR=$(sed -n 's/^TRADEAI_N8N_RELAY_LIVE_LANES=//p' "$F")
NEW=$(printf '%s\n' $CUR $ADD | awk 'NF && !seen[$0]++' | paste -sd' ')
echo "before: $CUR"; echo "after : $NEW"
[[ "${1:-}" == "--apply" ]] || { echo "DRY RUN — nothing written"; exit 0; }
cp -p "$F" "$F.bak-$(date -u +%Y%m%dT%H%M%SZ)-W5"
printf 'TRADEAI_N8N_RELAY_LIVE_LANES=%s\n' "$NEW" > "$F.tmp" && chmod 600 "$F.tmp" && mv "$F.tmp" "$F"
grep -c . "$F" >/dev/null; for l in $ADD; do grep -qw -- "$l" "$F" || { echo "READ-BACK FAILED: $l"; exit 1; }; done
systemctl --user restart tradeai-n8n-run-relay.service
sleep 2; systemctl --user is-active tradeai-n8n-run-relay.service
echo "read back OK; relay restarted"

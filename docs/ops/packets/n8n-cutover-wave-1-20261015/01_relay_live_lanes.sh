#!/usr/bin/env bash
# CW1 step 1 (config-write + service grants): add this wave's lanes to the relay/gateway live list, restart the relay.
#   bash 01_relay_live_lanes.sh            dry run: prints the new list
#   bash 01_relay_live_lanes.sh --apply    backup, write, read back, restart tradeai-n8n-run-relay
# Run ONLY after `readlink -f ~/trade-ai-releases/portfolio-server/CURRENT` names a release that contains this wave.
set -euo pipefail
F=${LIVE_LANES_ENV:-$HOME/.config/tradeai/n8n-live-lanes.env}
ADD="agent-outcome-linker catalyst-graph catalyst-symbol-impact classify-instruments document-mentions-backfill etf-analyst-enrich etf-performance-enrich feedback-loop-processor finviz-enrichment finviz-proactive-research finviz-screener-runner finviz-sector-research hermes-analyst-signal-discovery hermes-governance-api hermes-momentum-catalyst-scalp hermes-news-bridge identity-sweep-stage0 journal-tilt-morning-hook material-change-detector-stage1 materialize-watchlist-strategy-cards proposal-backtest-engine sec-data-ingest source-attribution-monitor update-agent-performance watchlist-enrichment-sweep"
CUR=$(sed -n 's/^TRADEAI_N8N_RELAY_LIVE_LANES=//p' "$F")
NEW=$(printf '%s\n' $CUR $ADD | awk 'NF && !seen[$0]++' | paste -sd' ')
echo "before: $CUR"; echo "after : $NEW"
[[ "${1:-}" == "--apply" ]] || { echo "DRY RUN — nothing written"; exit 0; }
cp -p "$F" "$F.bak-$(date -u +%Y%m%dT%H%M%SZ)-CW1"
printf 'TRADEAI_N8N_RELAY_LIVE_LANES=%s\n' "$NEW" > "$F.tmp" && chmod 600 "$F.tmp" && mv "$F.tmp" "$F"
grep -c . "$F" >/dev/null; for l in $ADD; do grep -qw -- "$l" "$F" || { echo "READ-BACK FAILED: $l"; exit 1; }; done
systemctl --user restart tradeai-n8n-run-relay.service
sleep 2; systemctl --user is-active tradeai-n8n-run-relay.service
echo "read back OK; relay restarted"

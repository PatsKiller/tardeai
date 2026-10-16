#!/usr/bin/env bash
# CW1 rollback. Each step is independent; run the ones that were applied, newest first.
#   R1 cron lines back : python3 scripts/pipelines/cutover/_cutover.py rollback --lane <lane> --apply   (per lane;
#                        uncomments exactly the `n8n-cutover <lane>` tagged lines) — or restore the 04 backup file.
#   R2 effect owners   : effect_claim.py set-owner --process <p> --owner cron --expect-epoch <e>  (keyed: agent-outcome-linker catalyst-symbol-impact document-mentions-backfill etf-analyst-enrich etf-performance-enrich feedback-loop-processor finviz-proactive-research finviz-screener-runner hermes-analyst-signal-discovery hermes-momentum-catalyst-scalp hermes-news-bridge journal-tilt-morning-hook material-change-detector-stage1 proposal-backtest-engine sec-data-ingest source-attribution-monitor update-agent-performance watchlist-enrichment-sweep)
#   R3 relay live list : restore ~/.config/tradeai/n8n-live-lanes.env.bak-*-CW1 and restart tradeai-n8n-run-relay
#   R4 registry        : revert the wave PR (rows back to shadow / dry_run) and promote; or dispatch.mode off.
# Lanes: agent-outcome-linker catalyst-graph catalyst-symbol-impact classify-instruments document-mentions-backfill etf-analyst-enrich etf-performance-enrich feedback-loop-processor finviz-enrichment finviz-proactive-research finviz-screener-runner finviz-sector-research hermes-analyst-signal-discovery hermes-governance-api hermes-momentum-catalyst-scalp hermes-news-bridge identity-sweep-stage0 journal-tilt-morning-hook material-change-detector-stage1 materialize-watchlist-strategy-cards proposal-backtest-engine sec-data-ingest source-attribution-monitor update-agent-performance watchlist-enrichment-sweep
echo "read the header; nothing is run automatically"

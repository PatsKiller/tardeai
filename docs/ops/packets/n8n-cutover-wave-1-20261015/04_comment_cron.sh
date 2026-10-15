#!/usr/bin/env bash
# CW1 step 4 (cron grant): after EVERY lane below has >= 1 live n8n RUN_DONE (03 evidence), comment all of the wave's
# cron lines in ONE crontab write: `# RETIRED <date> n8n-cutover <lane> <line>`. Backup first, read back after.
#   bash 04_comment_cron.sh            dry run (prints the edits)
#   bash 04_comment_cron.sh --apply
set -euo pipefail
REPO=${REPO:-$(cd "$(dirname "$0")/../../../.." && pwd)}
PY=${PY:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}
LANES=${LANES:-agent-outcome-linker,catalyst-graph,catalyst-symbol-impact,classify-instruments,document-mentions-backfill,etf-analyst-enrich,etf-performance-enrich,feedback-loop-processor,finviz-enrichment,finviz-proactive-research,finviz-screener-runner,finviz-sector-research,hermes-analyst-signal-discovery,hermes-governance-api,hermes-momentum-catalyst-scalp,hermes-news-bridge,identity-sweep-stage0,journal-tilt-morning-hook,material-change-detector-stage1,materialize-watchlist-strategy-cards,proposal-backtest-engine,sec-data-ingest,source-attribution-monitor,update-agent-performance,watchlist-enrichment-sweep}
"$PY" "$REPO/scripts/n8n_cutover_wave.py" comment-cron --code-root "$REPO" --lanes "$LANES" ${1:+$1}

#!/usr/bin/env bash
# W5 step 4 (cron grant): after EVERY lane below has >= 1 live n8n RUN_DONE (03 evidence), comment all of the wave's
# cron lines in ONE crontab write: `# RETIRED <date> n8n-cutover <lane> <line>`. Backup first, read back after.
#   bash 04_comment_cron.sh            dry run (prints the edits)
#   bash 04_comment_cron.sh --apply
set -euo pipefail
REPO=${REPO:-$(cd "$(dirname "$0")/../../../.." && pwd)}
PY=${PY:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}
LANES=${LANES:-reconcile-pullback-outcomes,build-hermes-canonical-status,directive-keyword-enhancer,fee-efficiency-analyzer,overnight-batch-tax,finviz-market-movers,hermes-usefulness-backfill,ask-alerts,sec-filings-feed,tmp-scratch-cleanup,reconcile-watch-outcomes,aegis-evening-packet,validate-expense-ratios,journal-review-builder,proposal-llm-review-worker,social-scalp-scanner,active-trader-session-review,enrich-proposal-technicals,hermes-discovery-ingestors,news-ingestion-tail,sec-fundamentals-ingest,agent-calibration-engine,reclassify-momentum-proposals,generate-analyst-reports-autonomous-weekly,due-diligence-questions}
"$PY" "$REPO/scripts/n8n_cutover_wave.py" comment-cron --code-root "$REPO" --lanes "$LANES" ${1:+$1}

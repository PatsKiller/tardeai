#!/usr/bin/env bash
# CW3 step 4 (cron grant): after EVERY lane below has >= 1 live n8n RUN_DONE (03 evidence), comment all of the wave's
# cron lines in ONE crontab write: `# RETIRED <date> n8n-cutover <lane> <line>`. Backup first, read back after.
#   bash 04_comment_cron.sh            dry run (prints the edits)
#   bash 04_comment_cron.sh --apply
set -euo pipefail
REPO=${REPO:-$(cd "$(dirname "$0")/../../../.." && pwd)}
PY=${PY:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}
LANES=${LANES:-opening-intelligence-render,pattern-extractor,wire-advisory-lessons,build-symbol-profiles-at-0-19,hermes-discovery-scorecard,incubator-rolloff-engine}
"$PY" "$REPO/scripts/n8n_cutover_wave.py" comment-cron --code-root "$REPO" --lanes "$LANES" ${1:+$1}

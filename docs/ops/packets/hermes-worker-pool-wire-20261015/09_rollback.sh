#!/usr/bin/env bash
# hermes-research-worker-pool — ROLLBACK (prints the commands; nothing runs without --apply).
#   bash 09_rollback.sh            # DRY RUN: show what would happen
#   bash 09_rollback.sh --apply    # operator only, after deciding to roll back
# This branch changes code + config only. No crontab line, systemd unit, n8n workflow, relay env or DB schema
# changed, so rollback = serve the previous release (the standard promote path) — nothing else to undo:
#   * the cron line `5 * * * * ... hermes_research_worker_pool.py --run --json` is unchanged; a release carries its
#     own code AND its own config/hermes_research_worker_lanes.yaml, so the previous release runs as before;
#   * the n8n dispatcher keeps firing the same allowlisted argv (`--run --json --dry-run`), dry_run only;
#   * data/runtime/hermes_worker_pool_state.json gains last_output_at / tracking_since per lane. The old code reads
#     only last_run_at and rewrites a lane's entry on its next run — harmless; do NOT delete the file (rail 6), it
#     also holds the cadence state;
#   * candidates written by the three new lanes are ordinary operator-gated Discovery Inbox rows (status NEW,
#     promotion impossible). Leave them; the operator can reject them in the inbox. Do not bulk-delete.
# A narrower lever than a full rollback, if one lane is noisy: set that lane `enabled: false` with a
# `disabled_reason` in config/hermes_research_worker_lanes.yaml via a PR (the pool refuses a disabled lane
# without a reason). Never silence the alarm by raising expected_output_hours without evidence.
set -euo pipefail
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
SERVED=$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")
echo "served now: $SERVED"
echo "previous releases (newest first):"
ls -1dt "$HOME"/trade-ai-releases/portfolio-server/*-main-exact-* 2>/dev/null | head -5
echo
echo "R1: promote the previous main sha through the standard release path (prepare + promote under the release grant;"
echo "    scripts/make_release.sh builds the pinned dir). No unit, crontab or n8n change is part of this rollback."
echo "R2: verify: bash $(dirname "$0")/02_live_n8n_run.sh --no-wait   (dry fire back to the one-line preview)"
[[ "${1:-}" == "--apply" ]] || { echo "DRY RUN — nothing changed"; exit 0; }
echo "REFUSED: rollback is the operator's release action (AGENTS.md §17); run the promote of the previous sha yourself."
exit 1

#!/usr/bin/env bash
# hermes-scorer step 4 (cron grant + approved inventory row cron:L449): retire crontab L451 AFTER the first live n8n
# RUN_DONE with rows written. Operator 2026-10-21, verbatim: "comment out whats working now this can be a fallback".
#   bash 02_retire_cron_line.sh --since 2026-10-21T17:00:00Z            dry run (default): proof + the exact edit
#   bash 02_retire_cron_line.sh --since 2026-10-21T17:00:00Z --apply    backup, comment ONLY the scorer line, read back
# The edit is made by the repo's cutover tool, `scripts/n8n_cutover_wave.py comment-cron` (one crontab write, backup
# first, read back after). The line is COMMENTED, never deleted (AGENTS.md §0 rail 6), with the repo's cutover tag:
#   # RETIRED <YYYY-MM-DD> n8n-cutover hermes-watchlist-scorer <original line>
# That tag is what `_cutover.py rollback --lane`, check_registry_runtime_truth and 03_fallback.sh parse; a free-text
# "(fallback: uncomment)" inside the tag would be restored INTO the crontab line on rollback, so it is not added.
# --apply refuses unless the coordination ledger shows a live RUN_DONE for the lane since --since and the receipt
# shows produced_count >= 1. Touches no broker, no secret value, no registry file.
set -euo pipefail
LANE=hermes-watchlist-scorer
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
PY=${PY:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}
STATE=${STATE:-$HOME/trade-ai-releases/persistent-state}
LEDGER=${LEDGER:-$STATE/data/governance/n8n_coordination_ledger.sqlite}
RECEIPT=${RECEIPT:-$STATE/data/runtime/${LANE}_last.json}
DATE=${CUTOVER_DATE:-$(TZ=America/New_York date +%F)}
APPLY=0; SINCE=""
while [[ $# -gt 0 ]]; do
  case "$1" in --apply) APPLY=1; shift ;; --since) SINCE=${2:-}; shift 2 ;; *) echo "usage: $0 --since ISO [--apply]"; exit 2 ;; esac
done
fail(){ echo "REFUSED: $*"; exit 1; }
[[ -n "$SINCE" ]] || fail "--since <ISO time of the live-list add> is required"

echo "== proof: live n8n RUN_DONE since $SINCE (read-only ledger) =="
PROOF=0
"$PY" "$SERVED/scripts/n8n_cutover_wave.py" evidence --lanes "$LANE" --since "$SINCE" --ledger "$LEDGER" \
  | "$PY" -c 'import json,sys; d=json.load(sys.stdin)[0]; [print("  ", r) for r in d["live_runs"][-5:]]; sys.exit(0 if d["live_done"] else 1)' \
  || PROOF=1
"$PY" - "$RECEIPT" <<'EOF' || PROOF=1
import json, sys
r = json.load(open(sys.argv[1]))
n = r.get("produced_count")
print(f"   receipt ok_at={r.get('ok_at')} produced_count={n} run_id={r.get('run_id')}")
sys.exit(0 if isinstance(n, int) and n >= 1 else 1)
EOF
[[ $PROOF == 0 ]] && echo "  proof: PASS" || echo "  proof: NOT YET (no live RUN_DONE with rows written since $SINCE)"

echo "== the edit (n8n_cutover_wave.py comment-cron) =="
ARGS=(comment-cron --code-root "$SERVED" --lanes "$LANE" --date "$DATE")
"$PY" "$SERVED/scripts/n8n_cutover_wave.py" "${ARGS[@]}"
[[ $APPLY == 1 ]] || { echo "DRY RUN - crontab unchanged"; exit 0; }

[[ $PROOF == 0 ]] || fail "no live n8n RUN_DONE with rows written yet: the cron line is still the only proven writer"
"$PY" "$SERVED/scripts/n8n_cutover_wave.py" "${ARGS[@]}" --apply
# Read back once into a variable. Never `crontab -l | grep -v ... | grep -q`: grep -q exits at the first match, the
# upstream stage takes SIGPIPE, and pipefail turns a FOUND line into "not found" (2026-10-22 SIGPIPE fix).
CT="$(crontab -l)" || fail "READ-BACK FAILED: crontab -l failed"
grep -c "^# RETIRED $DATE n8n-cutover $LANE .*scripts/hermes_watchlist_scorer.py" <<<"$CT" | grep -qx 1 \
  || fail "READ-BACK FAILED: the retired line is not in the crontab (backup under ~/.local/state/tradeai/backups)"
ACTIVE_LINES="$(grep -v '^[[:space:]]*#' <<<"$CT" || true)"
if grep -qF 'scripts/hermes_watchlist_scorer.py' <<<"$ACTIVE_LINES"; then
  fail "READ-BACK FAILED: an uncommented scorer line remains"
fi
echo "APPLIED: cron L451 retired (fallback: bash 03_fallback.sh --apply)."
echo "NEXT (agent, registry PR): python3 scripts/n8n_cutover_wave.py cutover --lanes $LANE --wave HS-20261021"
echo "  and set the health contract stage to cutover, then release it (README step 5)."

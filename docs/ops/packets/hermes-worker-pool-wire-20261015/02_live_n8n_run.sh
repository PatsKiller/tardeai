#!/usr/bin/env bash
# hermes-research-worker-pool — STEP 2: the live n8n run (read-only observation; no n8n, crontab or unit action).
#   bash 02_live_n8n_run.sh                # after the promote: wait for the next :05 dispatcher fire and read it
#   bash 02_live_n8n_run.sh --no-wait      # just print the last 5 ledger rows + both receipts
# The lane is already a dispatcher SHADOW lane (lane_registry stage shadow, dispatch mode dry_run, W4, cron 5 * * * *):
# tradeai-dispatcher -> relay -> gateway coordination/run -> tradeai-n8n-run-executor runs
#   flock -n -E <c> /tmp/hermes_worker_pool.lock.dryrun timeout -k 30 900 $PY scripts/hermes_research_worker_pool.py --run --json --dry-run
# every hour. Before this branch that dry run printed one line and exited 0 (89 RUN_DONE rows 2026-10-11..15 while
# three lanes produced nothing). After the promote the SAME fire runs the plan and ends RUN_FAILED (exit 3) if any
# enabled lane has no runner or an overdue output clock. Pass criteria for the first post-promote fire:
#   ledger row d:hermes-research-worker-pool:dry_run:<slot> state RUN_DONE, exit 0, receipt code_sha = served sha,
#   stdout_tail ends `DRY-RUN-SUMMARY {"ok": true, "failures": [], ...}`, output_signal mtime unchanged;
#   and the cron twin's receipt data/runtime/hermes-research-worker-pool_last.json status ok with
#   summary.lane_outcomes for all nine lanes (tax_retirement / system_ops / custom_domain NOT no_runner).
set -euo pipefail
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
STATE=${STATE:-$HOME/trade-ai-releases/persistent-state}
LEDGER="$STATE/data/governance/n8n_coordination_ledger.sqlite"
SERVED=$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")
echo "served release: $SERVED"
if [[ "${1:-}" != "--no-wait" ]]; then
  NOW=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
  echo "waiting for a dispatcher fire after $NOW (fires at :05 ET; up to 65 min)"
  for _ in $(seq 1 78); do
    N=$("$PY" - "$LEDGER" "$NOW" <<'EOF'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
print(c.execute("SELECT count(*) FROM runs WHERE lane_id='hermes-research-worker-pool' AND requested_at > ? "
                "AND state NOT IN ('REQUESTED','RUNNING')", (sys.argv[2],)).fetchone()[0])
EOF
)
    [[ "$N" -ge 1 ]] && break
    sleep 50
  done
fi
"$PY" - "$LEDGER" <<'EOF'
import json, sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
for r in c.execute("SELECT run_id, mode, state, exit_code, requested_at, duration_s, verdict, receipt_json FROM runs "
                   "WHERE lane_id='hermes-research-worker-pool' ORDER BY requested_at DESC LIMIT 5"):
    rec = json.loads(r["receipt_json"] or "{}")
    tail = (rec.get("stdout_tail") or "").strip().splitlines()
    print(json.dumps({"run_id": r["run_id"], "state": r["state"], "exit": r["exit_code"], "at": r["requested_at"],
                      "duration_s": r["duration_s"], "verdict": r["verdict"], "code_sha": rec.get("code_sha"),
                      "signal_mtime_unchanged": rec.get("output_signal_mtime_before") == rec.get("output_signal_mtime_after"),
                      "last_line": tail[-1][:400] if tail else None}))
EOF
echo "== cron twin receipt"
cat "$STATE/data/runtime/hermes-research-worker-pool_last.json"
echo
echo "== worker state (output clocks)"
cat "$STATE/data/runtime/hermes_worker_pool_state.json"

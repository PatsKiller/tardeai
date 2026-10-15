#!/usr/bin/env bash
# hermes-research-worker-pool — STEP 1: dry runs (read-only; nothing written, no model call).
#   bash 01_dry_run.sh                  # the CLI plan from the SERVED release (what cron and n8n run)
#   CODE=<tree> bash 01_dry_run.sh      # the same from another tree (e.g. this branch's worktree)
#   bash 01_dry_run.sh --executor       # also: one n8n-executor dry_run spawn in a throwaway state root
# Expected after the promote: exit 0, last line `DRY-RUN-SUMMARY {"ok": true, "failures": [], ...}` with all nine
# lanes listed. Before the first live run the output clocks read `untracked`; afterwards `within_window`.
# Exit 3 = a lane is enabled without a runner or its output clock is past expected_output_hours (that is the
# alarm working — read the plan, do not "fix" it by disabling the lane without a disabled_reason).
set -euo pipefail
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
CODE=${CODE:-$HOME/trade-ai-releases/portfolio-server/CURRENT}
echo "== code: $CODE ($(git -C "$CODE" rev-parse --short HEAD 2>/dev/null || readlink -f "$CODE"))"
echo "== worker state (read-only): $CODE/data/runtime/hermes_worker_pool_state.json"
cat "$CODE/data/runtime/hermes_worker_pool_state.json" 2>/dev/null || echo "(absent)"
echo
echo "== \$PY scripts/hermes_research_worker_pool.py --run --json --dry-run"
RC=0
(cd "$CODE" && "$PY" scripts/hermes_research_worker_pool.py --run --json --dry-run) || RC=$?
echo "exit=$RC"
echo "== --list-lanes (runner registration per lane)"
(cd "$CODE" && "$PY" scripts/hermes_research_worker_pool.py --list-lanes) || true

if [[ "${1:-}" == "--executor" ]]; then
  T=$(mktemp -d /tmp/hwp-exec-proof.XXXXXX)
  echo "== n8n executor dry_run path, throwaway state root $T (lock $T/pool.lock; the worker state file is read-only)"
  (cd "$CODE" && TRADEAI_VENV_PYTHON="$PY" "$PY" - "$T" <<'EOF'
import json, os, sys
from pathlib import Path
sys.path.insert(0, os.getcwd())
from scripts import n8n_run_executor as X
tmp = Path(sys.argv[1]); (tmp / "data/runtime").mkdir(parents=True)
allow = json.loads(Path("config/n8n_run_allowlist.json").read_text())
entry = dict(next(e for e in allow["lanes"] if e["lane_id"] == "hermes-research-worker-pool"), lock=str(tmp / "pool.lock"))
row = {"run_id": "d:packet-proof", "lane_id": "hermes-research-worker-pool", "mode": "dry_run"}
r = X.execute(row, entry, env=dict(os.environ), state_root=tmp, code_root=Path.cwd())
print(json.dumps({k: r[k] for k in ("state", "exit_code", "mode", "duration_s", "output_signal_mtime_before",
                                    "output_signal_mtime_after", "code_sha")}, indent=1))
print((r.get("stdout_tail") or "").strip().splitlines()[-1])
EOF
  )
fi
exit $RC

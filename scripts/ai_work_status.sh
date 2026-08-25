#!/usr/bin/env bash
# Read-only local work-policy status. Never contacts or mutates GitHub.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
base="origin/main"
if ! git rev-parse --verify origin/main >/dev/null 2>&1; then
  base="$(git rev-parse --abbrev-ref @{upstream} 2>/dev/null || echo HEAD)"
fi

commits_ahead=0
if git rev-parse --verify "$base" >/dev/null 2>&1; then
  commits_ahead="$(git rev-list --count "${base}..HEAD" 2>/dev/null || echo 0)"
fi

changed_files="$(git diff --name-only "${base}...HEAD" 2>/dev/null | sed '/^$/d' | wc -l | tr -d ' ')"
untracked_files="$(git ls-files --others --exclude-standard | sed '/^$/d' | wc -l | tr -d ' ')"

budget="$(python3 - <<'PY'
import json
from scripts.lib.tradeai_push_budget import load_state, remaining, MAX_WITHOUT_OVERRIDE
st = load_state()
count = int(st.get("authorized_push_count") or 0)
print(json.dumps({
    "count": count,
    "remaining": remaining(count),
    "max": MAX_WITHOUT_OVERRIDE,
    "tranche_id": st.get("tranche_id"),
    "last_push_at": st.get("last_push_at"),
}))
PY
)"

count="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["count"])' "$budget")"
remain="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["remaining"])' "$budget")"

ready="false"
if [[ "$commits_ahead" != "0" && "${TRADEAI_REMOTE_PUSH_AUTHORIZED:-0}" != "1" ]]; then
  ready="false"
fi
if [[ "$commits_ahead" != "0" ]]; then
  ready="local_candidate"
fi

cat <<EOF
branch: $branch
base: $base
commits_ahead: $commits_ahead
changed_files: $changed_files
untracked_files: $untracked_files
local_acceptance_status: unknown (run scripts/ai_local_acceptance.sh)
remote_pushes_this_tranche: $count
remote_push_budget_remaining: $remain
remote_push_default_authorized=false
ready_to_sync: $ready
EOF

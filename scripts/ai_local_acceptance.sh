#!/usr/bin/env bash
# Canonical local acceptance before requesting remote sync.
# Does not invoke remotes, GitHub CLI workflows, or synchronize branches.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

changed_paths() {
  python3 - <<'PY'
import subprocess
cmds = [
    ["git", "diff", "--name-only", "origin/main...HEAD"],
    ["git", "diff", "--name-only", "--cached"],
    ["git", "ls-files", "--others", "--exclude-standard"],
]
paths = set()
for cmd in cmds:
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        continue
    for line in out.splitlines():
        if line.strip():
            paths.add(line.strip())
print("\n".join(sorted(paths)))
PY
}

PATHS="$(changed_paths)"
policy_only=1
cio=0
frontend=0
tests=0
if [[ -z "$PATHS" ]]; then
  policy_only=0
fi
while IFS= read -r p; do
  [[ -z "$p" ]] && continue
  case "$p" in
    AI_WORK_POLICY.md|AGENTS.md|CLAUDE.md|.github/copilot-instructions.md) ;;
    .cursor/rules/*|.githooks/*) ;;
    scripts/install_ai_work_policy.sh|scripts/install_git_hooks.sh|scripts/ai_local_acceptance.sh|scripts/ai_work_status.sh|scripts/lib/tradeai_push_budget.py) ;;
    tests/test_ai_work_policy*|docs/ops/GITHUB_ACTIONS_COST_REDUCTION_PLAN.md|docs/ops/AI_WORK_POLICY*) ;;
    scripts/lib/cio_*|scripts/cio_*|tests/test_cio_*|tests/test_r1*) cio=1; policy_only=0 ;;
    apps/command-center-v3/*) frontend=1; policy_only=0 ;;
    tests/*) tests=1; policy_only=0 ;;
    *) policy_only=0 ;;
  esac
done <<< "$PATHS"

targeted_green=false
regression_green=false
release_equivalent_green=false
authority_green=false

echo "== Trade AI local acceptance =="
echo "python: $PY"

echo
echo "== Policy hook self-test =="
if [[ ! -x .githooks/pre-push ]]; then
  echo "ERROR: .githooks/pre-push missing" >&2
  exit 1
fi
if TRADEAI_REMOTE_PUSH_AUTHORIZED=0 .githooks/pre-push >/dev/null 2>&1; then
  echo "ERROR: pre-push allowed unauthorized push" >&2
  exit 1
fi
echo "pre-push blocks unauthorized sync: OK"
authority_green=true
targeted_green=true

if [[ -f tests/test_ai_work_policy_hooks.py ]]; then
  echo
  echo "== Policy unit tests =="
  "$PY" -m pytest -q tests/test_ai_work_policy_hooks.py
fi

if [[ "$policy_only" == "1" ]]; then
  regression_green=true
  release_equivalent_green=true
  echo
  echo "DIFF is policy/docs/hooks only — skipping heavy CIO/release suites."
else
  echo
  echo "== Target/repository validation =="
  TRADE_AI_CI=1 "$PY" scripts/run_release_ci_equivalent.py --source-only
  release_equivalent_green=true
  if [[ "$cio" == "1" ]]; then
    "$PY" scripts/run_cio_hardening_ci.py
    "$PY" scripts/run_cio_adversarial_suite.py
    authority_green=true
  fi
  if [[ "$frontend" == "1" && -f apps/command-center-v3/package.json ]]; then
    (cd apps/command-center-v3 && npx tsc --noEmit)
  fi
  if [[ "$tests" == "1" ]]; then
    "$PY" -m pytest -q tests/test_ai_work_policy_hooks.py
  fi
  regression_green=true
fi

cat <<EOF

LOCAL_ACCEPTANCE:
  targeted_green: $targeted_green
  regression_green: $regression_green
  release_equivalent_green: $release_equivalent_green
  authority_green: $authority_green
  diff_review_required: true
  ready_to_request_sync: $targeted_green
EOF

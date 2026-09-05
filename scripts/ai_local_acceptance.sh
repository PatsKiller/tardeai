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
    scripts/lib/cio_*|scripts/cio_*|tests/test_cio_*|tests/test_r1*|tests/test_r20*) cio=1; policy_only=0 ;;
    # Telegram notification regression (CSV replay + chokepoint ratchet) is
    # part of CIO hardening. Without this, Integrator local-acceptance could
    # skip tests/test_telegram_notification_normalization.py while independent
    # QA ran it as the full notification suite.
    scripts/check_telegram_chokepoint.py|scripts/check_provider_chokepoint.py|scripts/check_comms_gateway_enforcement.py|scripts/evaluate_telegram*|config/telegram_chokepoint_baseline.json|config/provider_chokepoint_baseline.json|tests/test_telegram*|tests/test_provider_chokepoint*|tests/test_comms_*|tests/fixtures/telegram*|scripts/lib/autonomy_watchdog/telegram*|scripts/lib/comms/*|scripts/telegram_transport.py|scripts/telegram_alert.py|scripts/alert_outbox.py) cio=1; policy_only=0 ;;
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
  # Lane registry. Deliberately OUTSIDE the cio branch below: a scheduler is not
  # a CIO concern, and the first version of this line sat inside that branch,
  # whose case patterns (scripts/lib/cio_*, tests/test_cio_*) match none of the
  # lane-registry files — so acceptance reported ready_to_request_sync: true
  # having never run the gate, and a change to the registry would not have run
  # its own gate either.
  echo
  echo "== Lane registry =="
  "$PY" scripts/check_lane_registry.py --fail-on-new
  if [[ "$cio" == "1" ]]; then
    "$PY" scripts/run_cio_hardening_ci.py
    "$PY" scripts/run_cio_adversarial_suite.py
    # The cio-hardening CI job runs these as separate steps, so local acceptance
    # could pass while CI failed on something provable locally in seconds. That
    # happened twice: PR #624 on a new uncalled versioned contract, and PR #631
    # on line-ending churn (a write_text() on a CRLF file, 1010 churn lines for
    # a 16-line edit). Mirror both steps here.
    "$PY" scripts/check_dark_contracts.py --fail-on-new
    "$PY" scripts/check_line_endings.py
    authority_green=true
  fi
  if [[ "$frontend" == "1" && -f apps/command-center-v3/package.json ]]; then
    (
      cd apps/command-center-v3
      # CI-equivalent: npm ci then tsc. node_modules is gitignored.
      if [[ ! -x node_modules/.bin/tsc ]]; then
        echo "command-center-v3 toolchain missing; npm ci (same as GitHub frontend jobs)"
        npm ci --no-fund --no-audit
      fi
      npx tsc --noEmit
    )
  fi
  if [[ "$tests" == "1" && -f tests/test_ai_work_policy_hooks.py ]]; then
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

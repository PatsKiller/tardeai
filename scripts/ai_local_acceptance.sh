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
    # Maturity-ladder libraries are CIO concerns even though they do not carry
    # a cio_ prefix. Without these patterns a change to the wake, the L3
    # judgment path, the LLM cost gate or the free-first circulation lane ran
    # NO CIO hardening locally, and the first thing to notice was GitHub: the
    # 2026-09-12 tranche reached CI and failed ci_self_guards on six new test
    # files that local acceptance never looked at.
    scripts/lib/l3_*|scripts/lib/judgment_schema.py|scripts/lib/model_policy.py) cio=1; policy_only=0 ;;
    scripts/lib/persistent_agent_wake.py|scripts/lib/memory_*|scripts/lib/governed_commitment.py) cio=1; policy_only=0 ;;
    scripts/lib/commitment_outcome_sweep.py|scripts/sweep_commitment_outcomes.py) cio=1; policy_only=0 ;;
    scripts/lib/llm_*|scripts/lib/provider_cost/*|scripts/lib/deepseek_client.py) cio=1; policy_only=0 ;;
    scripts/lib/free_first_*|scripts/free_first_refresh.py|scripts/run_free_first_circulation.sh) cio=1; policy_only=0 ;;
    scripts/lib/lane_registry.py|config/lane_registry.json|scripts/check_lane_registry.py) cio=1; policy_only=0 ;;
    scripts/lib/persistent_overlay.py|scripts/check_state_root_split.py) cio=1; policy_only=0 ;;
    apps/command-center-v3/*) frontend=1; policy_only=0 ;;
    # tests/ LAST among these: a new test file must reach the CIO branch so the
    # coverage gate that registers it actually runs. Matching tests/* first
    # would set tests=1 and skip it.
    tests/*) cio=1; tests=1; policy_only=0 ;;
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
# Probe the HOOK, not the ambient authority state. The hook treats a live
# operator git-push grant as authorization (see .githooks/pre-push: "Operator
# scope grant covers the push-budget override for this window"), so with a
# grant active this self-test used to fail -- and because this script is
# `set -e`, IT TOOK EVERY LATER GATE WITH IT. Acceptance was therefore weakest
# in exactly the situation where authority was highest: any campaign holding a
# push grant ran no release-equivalent, no lane registry, no CIO hardening.
# Point the guard ledger at an empty directory for the probe only; the real
# ledger at $HOME/.cursor/approvals is never read or written here.
probe_dir="$(mktemp -d)"
trap 'rm -rf "$probe_dir"' EXIT
if GUARD_APPROVALS_DIR="$probe_dir" TRADEAI_REMOTE_PUSH_AUTHORIZED=0 \
   .githooks/pre-push >/dev/null 2>&1; then
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

  # That step REGENERATES three provenance stamps, each carrying a fresh
  # timestamp:
  #
  #     docs/project/CI_EVIDENCE_LATEST.md
  #     docs/project/RELEASE_MANIFEST_LATEST.md
  #     docs/diligence/current/OPTIONS_RISK_BLOCK_MATRIX.md
  #
  # docs/INDEX.md records a fingerprint over the tracked tree, so rewriting them
  # changes the fingerprint the docs gates below then check — and those gates
  # fail on a drift this script caused itself, seconds earlier. The run
  # invalidates the very index it is about to verify.
  #
  # Measured 2026-09-12: three acceptance cycles were spent on this before the
  # cause was traced, each one "fixed" by restoring the files by hand and
  # re-running. Restore them here instead. The principle is the same one the
  # release tooling already applies to its own build stamp: a provenance file
  # the previous step rewrote carries no intent, and the next run rewrites it
  # again, so comparing it against the index proves nothing.
  #
  # (Deliberately not naming that script: tests/test_ai_work_policy_hooks.py
  # asserts this file never mentions it, so local acceptance can never be wired
  # to a deploy. The gate is a substring check and it is right to be.)
  #
  # Only these three, only when unmodified apart from the regeneration, and
  # never anything the author actually edited: each is restored from HEAD, so a
  # genuine local change to one of them survives as a staged change and a
  # deliberate edit is not silently discarded.
  for stamp in docs/project/CI_EVIDENCE_LATEST.md \
               docs/project/RELEASE_MANIFEST_LATEST.md \
               docs/diligence/current/OPTIONS_RISK_BLOCK_MATRIX.md; do
    if [[ -f "$stamp" ]] && ! git diff --quiet --cached -- "$stamp" 2>/dev/null; then
      continue   # the author staged a real change to this file; leave it alone
    fi
    git checkout -- "$stamp" 2>/dev/null || true
  done
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
    # Run every CIO gate and report ALL of them, rather than stopping at the
    # first. Under `set -e` a run_cio_hardening_ci.py failure skipped the four
    # gates below it, so an author fixed one thing, re-ran, and met the next
    # failure only on the following cycle. Worse, the skipped gates are the ones
    # GitHub runs as SEPARATE steps: on 2026-09-12 a hardening failure hid a
    # dark-contract violation locally, and CI found it after the push. Same
    # shape as the pre-push probe at the top of this file — one early failure
    # silently cancelling later coverage.
    cio_failed=()
    "$PY" scripts/run_cio_hardening_ci.py       || cio_failed+=("cio_hardening")
    "$PY" scripts/run_cio_adversarial_suite.py  || cio_failed+=("cio_adversarial")
    # The cio-hardening CI job runs these as separate steps, so local acceptance
    # could pass while CI failed on something provable locally in seconds. That
    # happened twice: PR #624 on a new uncalled versioned contract, and PR #631
    # on line-ending churn (a write_text() on a CRLF file, 1010 churn lines for
    # a 16-line edit). Mirror both steps here.
    "$PY" scripts/check_dark_contracts.py --fail-on-new || cio_failed+=("dark_contracts")
    "$PY" scripts/check_line_endings.py                   || cio_failed+=("line_endings")
    if (( ${#cio_failed[@]} )); then
      echo
      echo "CIO GATES FAILED: ${cio_failed[*]}" >&2
      exit 1
    fi
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

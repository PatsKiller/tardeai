#!/usr/bin/env bash
# Default local acceptance wrapper. Path-aware: policy/docs/hooks-only diffs
# skip the heavy CIO/release suites. Code diffs run the full local gates.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

is_policy_only() {
  python3 - <<'PY'
import subprocess, sys
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
allowed = (
    "AI_WORK_POLICY.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".cursor/rules/",
    ".github/copilot-instructions.md",
    ".githooks/",
    "scripts/install_ai_work_policy.sh",
    "scripts/install_git_hooks.sh",
    "scripts/ai_local_acceptance.sh",
    "tests/test_ai_work_policy",
    "docs/ops/AI_WORK_POLICY",
)
if not paths:
    sys.exit(1)
for p in paths:
    if any(p == a.rstrip("/") or p.startswith(a) for a in allowed):
        continue
    sys.exit(1)
sys.exit(0)
PY
}

echo "== Trade AI local acceptance =="
echo "python: $PY"

echo
echo "== Policy hook self-test =="
if [[ ! -x .githooks/pre-push ]]; then
  echo "ERROR: .githooks/pre-push missing or not executable" >&2
  exit 1
fi
if TRADEAI_REMOTE_PUSH_AUTHORIZED=0 .githooks/pre-push >/dev/null 2>&1; then
  echo "ERROR: pre-push allowed unauthorized push" >&2
  exit 1
fi
echo "pre-push blocks unauthorized sync: OK"

if [[ -f tests/test_ai_work_policy_hooks.py ]]; then
  echo
  echo "== Policy unit tests =="
  "$PY" -m pytest -q tests/test_ai_work_policy_hooks.py
fi

if is_policy_only; then
  echo
  echo "DIFF is policy/docs/hooks only — skipping heavy CIO/release suites."
  echo
  echo "LOCAL ACCEPTANCE GREEN (policy-path)"
  echo "Remote push remains separately authorized."
  exit 0
fi

echo
echo "== Target/repository validation =="
"$PY" scripts/run_cio_hardening_ci.py
"$PY" scripts/run_cio_adversarial_suite.py
TRADE_AI_CI=1 "$PY" scripts/run_release_ci_equivalent.py --source-only

echo
echo "LOCAL ACCEPTANCE GREEN"
echo "Remote push remains separately authorized."

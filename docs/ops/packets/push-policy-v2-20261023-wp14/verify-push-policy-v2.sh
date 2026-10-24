#!/usr/bin/env bash
# Read-only package proof; tests use fixture repos and TMPDIR, never a real remote.
# Usage: bash verify-push-policy-v2.sh TREE --stage none|proposed|ratified
set -euo pipefail
TREE="$(cd "${1:?tree required}" && pwd)"
[[ "${2:-}" == --stage ]] || { echo 'REFUSED: --stage none|proposed|ratified required' >&2; exit 2; }
STAGE="${3:-}"
case "$STAGE" in none|proposed|ratified) ;; *) echo 'REFUSED: invalid stage' >&2; exit 2;; esac
REPO="${TRADEAI_REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
PY="${TRADEAI_PP2_PYTHON:-$REPO/.venv/bin/python}"
[[ -x "$PY" ]] || PY=python3
export TMPDIR="${TMPDIR:-$HOME/.cache/rtc}" TRADE_AI_CI=1
mkdir -p "$TMPDIR"
cd "$TREE"
echo "== verify push policy v2 stage=$STAGE tree=$TREE =="
bash -n .githooks/pre-push
if command -v shellcheck >/dev/null; then shellcheck .githooks/pre-push; fi
if [[ "$STAGE" == none ]]; then
  ! grep -q '^Push-Policy-v2:' AI_WORK_POLICY.md
  [[ ! -e tests/test_push_policy_v2_20261023.py ]]
  FILES=()
else
  marker=PROPOSED
  [[ "$STAGE" == ratified ]] && marker=ACTIVE
  grep -qx "Push-Policy-v2: $marker" AI_WORK_POLICY.md
  FILES=(tests/test_push_policy_v2_20261023.py)
  RUFF="${TRADEAI_PP2_RUFF:-$REPO/.venv/bin/ruff}"
  [[ -x "$RUFF" ]] || RUFF="$(command -v ruff || true)"
  [[ -n "$RUFF" ]] || { echo 'REFUSED: ruff is required' >&2; exit 2; }
  "$RUFF" check scripts/lib/tradeai_push_budget.py tests/test_push_policy_v2_20261023.py
  "$RUFF" format --check scripts/lib/tradeai_push_budget.py tests/test_push_policy_v2_20261023.py
fi
"$PY" -m pytest -q -p no:cacheprovider "${FILES[@]}" \
  tests/test_ai_work_policy_hooks.py \
  tests/test_guard_grant_mechanics_20261021.py \
  tests/test_push_budget_common_dir_20261021.py \
  tests/test_guard_push_auth.py \
  tests/test_guard_push_scope_20260925.py \
  tests/test_agents_policy_17_0_0_release_train.py \
  tests/test_agents_policy_4_1_0_amendment.py \
  tests/test_stop_cron_pushes_20261010.py \
  tests/test_agent_hooks_ci_hermetic.py \
  tests/test_agent_session_and_lease.py \
  tests/test_ci_gates_registry_20261021.py \
  tests/test_ci_fail_all_skipped_20261021.py

echo '-- unauthorized hook invocation must refuse; no git push is performed --'
set +e
out="$(env -u TRADEAI_REMOTE_PUSH_AUTHORIZED -u TRADEAI_REMOTE_PUSH_OVERRIDE \
  HOME="$TMPDIR/pp2-home" GUARD_APPROVALS_DIR="$TMPDIR/pp2-empty-approvals" \
  bash .githooks/pre-push </dev/null 2>&1)"
rc=$?
set -e
echo "$out" | sed 's/^/  | /'
[[ $rc -ne 0 ]] || { echo 'FAIL: hook allowed unauthorized invocation' >&2; exit 1; }
echo "VERIFY OK stage=$STAGE unauthorized_rc=$rc"

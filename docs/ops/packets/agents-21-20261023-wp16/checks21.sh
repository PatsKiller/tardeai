#!/usr/bin/env bash
# Operator worktree only; source-only and fixture tests. No broker/DB/provider call.
set -euo pipefail
ROOT=${1:?usage: checks21.sh WORKTREE}
PY=${TRADEAI_POLICY_PYTHON:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}
cd "$ROOT"
export TRADE_AI_CI=1 TMPDIR="${TMPDIR:-$HOME/.cache/rtc}"
"$PY" -m pytest -q -p no:cacheprovider tests/test_agents_policy_*.py tests/test_agents_section_zero_parity.py tests/test_ci_gates_registry_20261021.py
"$PY" scripts/check_agents_policy_state.py --on-branch
"$PY" scripts/check_agents_policy_state.py --on-main

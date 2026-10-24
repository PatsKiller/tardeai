#!/usr/bin/env bash
set -euo pipefail
PY="${PY:-python3}"
export TRADE_AI_CI=1
"$PY" -m pytest -q -p no:cacheprovider tests/test_agents_policy_*.py tests/test_agents_section_zero_parity.py tests/test_ci_gates_registry_20261021.py
"$PY" scripts/check_agents_policy_state.py --on-main
"$PY" scripts/report_docs_inventory.py --check-index
git diff --check

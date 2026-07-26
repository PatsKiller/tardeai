#!/usr/bin/env bash
set -euo pipefail

: "${AGENT_RUNTIME_UI_VALIDATION_ACK:?set AGENT_RUNTIME_UI_VALIDATION_ACK=AGENT_RUNTIME_UI_VALIDATION_ONLY}"
: "${AGENT_RUNTIME_UI_SOURCE_REF:?set AGENT_RUNTIME_UI_SOURCE_REF to an exact commit SHA}"

if [[ "${AGENT_RUNTIME_UI_VALIDATION_ACK}" != "AGENT_RUNTIME_UI_VALIDATION_ONLY" ]]; then
  echo "BLOCKED: invalid validation acknowledgement"
  exit 2
fi
if [[ ! "${AGENT_RUNTIME_UI_SOURCE_REF}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BLOCKED: AGENT_RUNTIME_UI_SOURCE_REF must be an exact 40-character commit SHA"
  exit 2
fi

REPO=${REPO:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PYTHON_BIN=${PYTHON_BIN:-}

if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${REPO}/.venv/bin/python" ]]; then
    PYTHON_BIN="${REPO}/.venv/bin/python"
  else
    PYTHON_BIN=python3
  fi
fi

git -C "${REPO}" cat-file -e "${AGENT_RUNTIME_UI_SOURCE_REF}^{commit}"
VALIDATED_SHA=$(git -C "${REPO}" rev-parse "${AGENT_RUNTIME_UI_SOURCE_REF}^{commit}")
if [[ "${VALIDATED_SHA}" != "${AGENT_RUNTIME_UI_SOURCE_REF}" ]]; then
  echo "BLOCKED: resolved commit does not match requested exact SHA"
  exit 2
fi

TMP_DIR=$(mktemp -d /tmp/agent-runtime-ui-validation.XXXXXX)
cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

git -C "${REPO}" archive "${VALIDATED_SHA}" -- \
  apps/command-center-v3 \
  config/agent_maturity_catalog.json \
  config/design_token_baseline.json \
  scripts/agent_runtime \
  scripts/check_design_tokens.sh \
  scripts/test_chip_scope.mjs \
  tests/test_agent_runtime_monitoring.py \
  | tar -x -C "${TMP_DIR}"

cd "${TMP_DIR}"
"${PYTHON_BIN}" -m compileall -q scripts/agent_runtime/monitoring.py
"${PYTHON_BIN}" -m pytest -q tests/test_agent_runtime_monitoring.py

grep -Fq "agent-runtime-monitoring-v1" apps/command-center-v3/src/lib/agentRuntimeMonitoring.ts
grep -Fq "FIXTURE" apps/command-center-v3/src/pages/AgentRuntimeHub.tsx
grep -Fq "NOT RUN" apps/command-center-v3/src/pages/AgentRuntimeHub.tsx
grep -Fq "ZERO FINANCIAL AUTHORITY" apps/command-center-v3/src/pages/AgentRuntimeHub.tsx
grep -Fq "Legacy analytics" apps/command-center-v3/src/pages/AgentRuntimeHub.tsx
grep -Fq "<AgentRuntimeHub onDrill={setDrill} />" apps/command-center-v3/src/App.tsx

cd apps/command-center-v3
npm ci --ignore-scripts
npm run build

echo "validated_commit|${VALIDATED_SHA}"
echo "validation_scope|TEMPORARY_AGENT_RUNTIME_UI_BUILD_AND_TESTS_ONLY"
echo "monitoring_contract|agent-runtime-monitoring-v1"
echo "evidence_source|FIXTURE"
echo "authoritative_persistence_adapter|NOT_CONNECTED"
echo "operational_agents_claimed|0"
echo "design_token_guard|PASS"
echo "live_dist_change|NONE"
echo "database_write|NONE"
echo "model_provider_call|NONE"
echo "schedule_change|NONE"
echo "service_restart|NONE"
echo "broker_or_order_action|NONE"
echo "approval_or_2fa_action|NONE"
echo "final_status|PASS_AGENT_RUNTIME_UI_VALIDATION"

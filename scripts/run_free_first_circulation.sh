#!/usr/bin/env bash
# CURRENT-pinned FREE_FIRST_ONLY circulation. Never dispatches a paid provider.
# Invoked by tradeai-free-first-circulation.service after flock -n.
set -euo pipefail
ROOT="${TRADEAI_CURRENT:-/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT}"
PY="${TRADEAI_VENV_PYTHON:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}"
cd "$ROOT"
SOURCE_COMMIT="$(tr -d '[:space:]' < SOURCE_COMMIT 2>/dev/null || true)"
BUILD_SHA="$(tr -d '[:space:]' < BUILD_SHA 2>/dev/null || true)"
RUN_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[free-first $START] run_id=$RUN_ID mode=FREE_FIRST_ONLY source_sha=${SOURCE_COMMIT:-missing} build_sha=${BUILD_SHA:-missing} cwd=$ROOT paid_allowed=false"
# --max-searx 1 enables residual SearXNG only (circulate_symbol still skips resolved names).
# --circulate is the production Hermes→RAG→structured path. Not the paid CIO drain.
export MEMORY_BEHAVIOR_INFLUENCE="${MEMORY_BEHAVIOR_INFLUENCE:-0}"
export FREE_FIRST_RUN_ID="$RUN_ID"
exec "$PY" scripts/free_first_refresh.py --root "$ROOT" --circulate --json --max-searx 1

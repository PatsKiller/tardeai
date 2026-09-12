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
# The unit sets TimeoutStartSec=900. Circulation wall time grew with the
# universe -- 2m42s on 2026-08-23, 14m40s on 2026-09-07 -- and from 2026-09-08
# every run was SIGTERM'd at 900s. 93 consecutive kills, and because the receipt
# is written only after the work returns, not one of them left a durable record:
# the newest receipt stayed at 2026-09-07 and the health predicate read it as
# current. Stop under our own control, with margin, so the run always reports.
#
# Margin covers process start, profile load and receipt write. Keep
# DEADLINE + MARGIN < TimeoutStartSec, and raise TimeoutStartSec first if this
# ever needs to grow.
UNIT_TIMEOUT_S="${TRADEAI_FREE_FIRST_UNIT_TIMEOUT_S:-900}"
DEADLINE_MARGIN_S="${TRADEAI_FREE_FIRST_MARGIN_S:-120}"
DEADLINE_S="${TRADEAI_FREE_FIRST_DEADLINE_S:-$((UNIT_TIMEOUT_S - DEADLINE_MARGIN_S))}"
# A bounded run that always starts at the head of the list never reaches the
# tail; the cursor makes successive partial runs sweep the whole universe.
CURSOR="${TRADEAI_FREE_FIRST_CURSOR:-$ROOT/data/cio/free_first_cursor.json}"
exec "$PY" scripts/free_first_refresh.py --root "$ROOT" --circulate --json --max-searx 1 \
  --deadline-seconds "$DEADLINE_S" --cursor-path "$CURSOR"

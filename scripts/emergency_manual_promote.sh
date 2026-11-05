#!/usr/bin/env bash
# emergency_manual_promote.sh — operator-only host CLI promote (AGENTS.md §25.10).
#
# Requires:
#   1) active release-write grant naming the exact SHA (ReleaseGrantBinding@v1)
#   2) TRADEAI_EMERGENCY_RELEASE_SHA=<40-hex> matching that SHA
#   3) STOP latch ABSENT
#   4) GlobalReleaseLock free
#
# Agents, n8n and Mergify never set TRADEAI_EMERGENCY_RELEASE_SHA.
# Receipt path=manual_emergency. See docs/ops/EMERGENCY_MANUAL_PROMOTE.md.
#
# Usage:
#   export TRADEAI_EMERGENCY_RELEASE_SHA=<full40>
#   bin/guard grant release-write --for 30m --uses 2 --reason "emergency promote #<pr> <sha>"
#   bash scripts/emergency_manual_promote.sh [--dry-run]

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="${TRADEAI_PY:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY=python3

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

SHA="${TRADEAI_EMERGENCY_RELEASE_SHA:-}"
if [[ -z "$SHA" ]]; then
  echo "REFUSED: TRADEAI_EMERGENCY_RELEASE_SHA is unset (operator must set it)" >&2
  exit 2
fi
if [[ ! "$SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "REFUSED: TRADEAI_EMERGENCY_RELEASE_SHA must be a full 40-hex SHA (got ${#SHA} chars)" >&2
  exit 2
fi

"$PY" - <<PY
import os, sys
sys.path.insert(0, "${ROOT}")
from scripts.lib.release_grant_binding import ReleaseAction, decide_from_disk

sha = os.environ["TRADEAI_EMERGENCY_RELEASE_SHA"]
verdict = decide_from_disk(ReleaseAction(action="promote", target_sha=sha))
if not verdict.allowed:
    print(f"REFUSED: release-write binding: {verdict.reason}", file=sys.stderr)
    raise SystemExit(3)
print(f"emergency: grant ok id={verdict.grant_id} matched_by={verdict.matched_by}")
PY

"$PY" - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from scripts.lib.deploy_on_main import stop_latched, state_dir
from scripts.lib.release_control import GlobalReleaseLock, LockBusy

stopped, detail = stop_latched()
if stopped:
    print(f"REFUSED: STOP latch {detail}", file=sys.stderr)
    raise SystemExit(4)
try:
    lock = GlobalReleaseLock(state_dir(), timeout_s=0.0)
    lock.acquire()
    lock.release()
except LockBusy:
    print("REFUSED: GlobalReleaseLock busy", file=sys.stderr)
    raise SystemExit(5)
print("emergency: STOP absent, lock free")
PY

BEFORE="$("$PY" -c 'from scripts.lib.deploy_on_main import current_pin_sha; print(current_pin_sha())')"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "emergency: DRY-RUN would prepare+promote SHA=$SHA (CURRENT before=$BEFORE)"
  "$PY" - <<PY
from scripts.lib.deploy_on_main import write_receipt, PATH_MANUAL_EMERGENCY
write_receipt(
    path_kind=PATH_MANUAL_EMERGENCY,
    outcome="would_promote",
    main_sha="${SHA}",
    current_sha_before="${BEFORE}",
    reason="operator_emergency_manual_promote_dry_run",
)
print("emergency: dry-run receipt written")
PY
  exit 0
fi

echo "emergency: prepare then promote for $SHA (before CURRENT pin=$BEFORE)"
bash "$ROOT/scripts/cio_phase2_exact_main_deploy.sh" prepare
bash "$ROOT/scripts/cio_phase2_exact_main_deploy.sh" promote

AFTER="$("$PY" -c 'from scripts.lib.deploy_on_main import current_pin_sha; print(current_pin_sha())')"

"$PY" - <<PY
from scripts.lib.deploy_on_main import write_receipt, PATH_MANUAL_EMERGENCY
write_receipt(
    path_kind=PATH_MANUAL_EMERGENCY,
    outcome="promoted",
    main_sha="${SHA}",
    current_sha_before="${BEFORE}",
    current_sha_after="${AFTER}",
    reason="operator_emergency_manual_promote",
)
print("emergency: receipt written path=manual_emergency")
PY

if [[ -f "$ROOT/scripts/post_release_tester.py" ]]; then
  if ! "$PY" "$ROOT/scripts/post_release_tester.py"; then
    echo "WARN: post_release_tester failed — paging operator" >&2
    "$PY" -c "from scripts.delivery_failure_alerts import page_p1; page_p1(kind='emergency_promote_verify', message='verify failed after emergency promote')" || true
    exit 1
  fi
fi

echo "emergency: OK CURRENT was $BEFORE now $AFTER"

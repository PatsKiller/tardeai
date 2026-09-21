#!/usr/bin/env bash
# Idempotent bitemporal v2 packaging heal — isolated M2 only (:55432 / m2_shadow).
#
# Closes the PR #1158 gap: destructive r10 rebuilds strip
# trade-ai-bitemporal-schema-v2.sql aliases/views/triggers.
#
# NEVER defaults to production :5432. Pass M2_DSN / TEST_DB_DSN explicitly.
# Production apply remains §17 DEFERRED (AGENTS.md).
#
# Usage:
#   M2_DSN='postgresql://m2:m2shadow@127.0.0.1:55432/m2_shadow' \
#     bash scripts/init_bitemporal_db.sh
#   bash scripts/init_bitemporal_db.sh --dsn 'postgresql://…@127.0.0.1:55432/…'
#
# Exit 0: healthy or successfully healed.
# Exit 1: missing file / heal failed / production DSN refused.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="${PYTHON:-python3}"
fi

DSN_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dsn) DSN_ARG="${2:-}"; shift 2 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
if [[ -n "$DSN_ARG" ]]; then
  export M2_DSN="$DSN_ARG"
fi

exec "$PY" - <<'PY'
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from scripts.lib.bitemporal_schema_heal import (
    ensure_bitemporal_packaging_v2,
    resolve_isolated_dsn,
)
from scripts.lib.memory_m2_benchmark import connect

now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

try:
    dsn = resolve_isolated_dsn()
except Exception as exc:
    print(f"[ERROR] {exc}", file=sys.stderr)
    sys.exit(1)

# Belt: refuse host :5432 even if an auth env would allow the DSN string through
# resolve_isolated_dsn — packaging heal never targets production.
hostport = dsn.rsplit("@", 1)[-1]
if ":5432" in hostport.split("/")[0]:
    print("[ERROR] M2_DSN_PRODUCTION_PORT_FORBIDDEN", file=sys.stderr)
    sys.exit(1)

print(f"[INFO] [{now}] bitemporal packaging health check (isolated DSN only)")
conn = connect(dsn)
try:
    result = ensure_bitemporal_packaging_v2(conn)
finally:
    conn.close()

action = result.get("action")
if action == "skip":
    print("[OK] Bitemporal Schema v2 packaging HEALTHY — skip DDL")
else:
    print("[ALERT] packaging MISSING/STRIPPED — applied trade-ai-bitemporal-schema-v2.sql")
    print("[SUCCESS] packaging healed")

after = result.get("after") or {}
required = (
    "view_fact_ok",
    "save_fn_ok",
    "block_fn_ok",
    "block_trg_ok",
    "excl_ok",
    "fact_ok",
)
ok = all(after.get(k) for k in required)
print(json.dumps({"action": action, "healthy": bool(after.get("healthy")), "signals": {k: after.get(k) for k in required}}, sort_keys=True))
sys.exit(0 if ok else 1)
PY

#!/usr/bin/env bash
# Convergence — Phase MOUNT (bootstrap-safe, fixes the deploy_read_mount.sh:104 "require pre-existing
# 503" flaw). Installs the exact-ref backend mount + static bundle so the read plane answers, WITHOUT
# a reader DSN → must land at HTTP 503 / read_only / connected:false / zero-authority. STATE-AWARE:
#   404 / 000 → mount ABSENT → (apply) install exact-ref backend+static, expect 503, auto-restore on fail
#   503       → already mounted-disconnected → MOUNT already satisfied
#   200       → already connected (this host) → MOUNT+CONNECT already done → verify only
# DRY-RUN by default. --apply performs the install; --apply requires the MOUNT ack. No CONNECT here.
set -u -o pipefail
umask 077
REPO="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
BASE="http://127.0.0.1:7777"; EP="$BASE/api/v3/agent-runtime/runs?limit=1"
LIB="$(dirname "$0")/convergence_lib.py"
APPLY=""; ACK=""
for a in "$@"; do case "$a" in --apply) APPLY=1;; --ack=*) ACK="${a#--ack=}";; esac; done

resp="$(curl -sS --max-time 8 -w $'\n%{http_code}' "$EP" 2>/dev/null || printf '\n000')"
code="${resp##*$'\n'}"; body="${resp%$'\n'*}"
state="$(PY_BODY="$body" PY_CODE="$code" python3 - "$LIB" <<'PY'
import os,sys,json,importlib.util
spec=importlib.util.spec_from_file_location("cl",sys.argv[1]); cl=importlib.util.module_from_spec(spec); spec.loader.exec_module(cl)
try: b=json.loads(os.environ["PY_BODY"])
except Exception: b={}
print(cl.classify_agent_runtime(int(os.environ["PY_CODE"]), b))
PY
)"
echo "agent_runtime_http|$code"
echo "agent_runtime_state|$state"

case "$state" in
  CONNECTED_READ_ONLY)
    echo "mount_phase|ALREADY_CONNECTED — mount+connect already satisfied on this host; no action"
    echo "agent_runtime_mount_phase|PREPARED_NOT_RUN"; exit 0 ;;
  MOUNTED_DISCONNECTED)
    echo "mount_phase|ALREADY_MOUNTED_DISCONNECTED — MOUNT contract already met; proceed to CONNECT"
    echo "agent_runtime_mount_phase|PREPARED_NOT_RUN"; exit 0 ;;
  MOUNT_ABSENT|UNEXPECTED_HTTP_000|UNEXPECTED_HTTP_*)
    echo "mount_phase|MOUNT_ABSENT — bootstrap path (this is what the old packet could NOT do from 404)"
    if [ -z "$APPLY" ]; then
      echo "  plan: install exact-ref backend mount + staged static (NO reader DSN); require post HTTP 503/read_only/connected:false/zero-authority; auto-restore on fail"
      echo "agent_runtime_mount_phase|PREPARED_NOT_RUN"; exit 0
    fi
    [ "$ACK" = "MOUNT_AGENT_RUNTIME_EXACT_REF" ] || { echo "final_status|BLOCKED_MOUNT_ACK_MISSING"; exit 2; }
    echo "final_status|APPLY_PATH_NOT_EXERCISED_IN_DRAFT"; exit 0 ;;
  *)
    echo "mount_phase|MALFORMED_CONTRACT ($state) — BLOCK, no action"
    echo "agent_runtime_mount_phase|BLOCKED"; exit 2 ;;
esac

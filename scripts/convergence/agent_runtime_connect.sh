#!/usr/bin/env bash
# Convergence — Phase CONNECT. Runs ONLY after MOUNT passed AND a SEPARATE explicit ack. Provisions
# nothing itself beyond wiring the reader: requires the isolated agent-runtime schema + exact read-only
# reader role to already exist (a separate dry-run-first schema/role packet handles absent schema).
# Writes the mode-0600 env file + user-systemd drop-in, restarts ONE user service, requires post
# HTTP 200 / read_only / connected:true / zero-authority / reader_role=agentic_runtime_reader; rolls
# back on any failure. The DSN is NEVER printed or persisted in evidence. DRY-RUN by default.
set -u -o pipefail
umask 077
BASE="http://127.0.0.1:7777"; EP="$BASE/api/v3/agent-runtime/runs?limit=1"
LIB="$(dirname "$0")/convergence_lib.py"
READER_ENV="$HOME/.config/tradeai/agent-read-api.env"
DROPIN="$HOME/.config/systemd/user/portfolio-server.service.d/10-agent-read-api.conf"
EXPECT_ROLE="agentic_runtime_reader"
APPLY=""; ACK=""; MOUNT_PASSED=""
for a in "$@"; do case "$a" in --apply) APPLY=1;; --ack=*) ACK="${a#--ack=}";; --mount-passed) MOUNT_PASSED=1;; esac; done

# gate: CONNECT requires MOUNT passed AND a separate explicit acknowledgement (lib-enforced logic)
if ! MP="$MOUNT_PASSED" AK="$ACK" python3 - "$LIB" <<'PY'
import os,sys,importlib.util
spec=importlib.util.spec_from_file_location("cl",sys.argv[1]); cl=importlib.util.module_from_spec(spec); spec.loader.exec_module(cl)
try:
    cl.can_run_connect(bool(os.environ.get("MP")), os.environ.get("AK")=="CONNECT_AGENT_RUNTIME_EXACT_REF")
except cl.PhaseGateError as e:
    print("CONNECT_GATE_BLOCKED|"+str(e)); sys.exit(3)
print("CONNECT_GATE_OK")
PY
then
  echo "agent_runtime_connect_phase|BLOCKED_GATE"; exit 2
fi

# current posture
resp="$(curl -sS --max-time 8 -w $'\n%{http_code}' "$EP" 2>/dev/null || printf '\n000')"
code="${resp##*$'\n'}"; body="${resp%$'\n'*}"
ok="$(PY_BODY="$body" PY_CODE="$code" python3 - "$LIB" "$EXPECT_ROLE" <<'PY'
import os,sys,json,importlib.util
spec=importlib.util.spec_from_file_location("cl",sys.argv[1]); cl=importlib.util.module_from_spec(spec); spec.loader.exec_module(cl)
try: b=json.loads(os.environ["PY_BODY"])
except Exception: b={}
print("YES" if cl.connect_contract_ok(int(os.environ["PY_CODE"]), b, sys.argv[2]) else "NO")
PY
)"
echo "agent_runtime_http|$code"
if [ "$ok" = "YES" ]; then
  echo "connect_phase|ALREADY_CONNECTED — contract satisfied (200/read_only/connected:true/$EXPECT_ROLE/zero-authority); no action"
  echo "agent_runtime_connect_phase|PREPARED_NOT_RUN"; exit 0
fi

if [ -z "$APPLY" ]; then
  echo "connect_phase|PLAN (dry-run): require SHADOW_READER_DSN (never printed) → write 0600 $READER_ENV + drop-in $DROPIN → daemon-reload → restart portfolio-server.service → require 200/read_only/connected:true/$EXPECT_ROLE/zero-authority → rollback on fail"
  echo "reader_env_target|$READER_ENV (mode 0600)"
  echo "dropin_target|$DROPIN"
  echo "agent_runtime_connect_phase|PREPARED_NOT_RUN"; exit 0
fi
echo "final_status|APPLY_PATH_NOT_EXERCISED_IN_DRAFT (requires SHADOW_READER_DSN + separate authorization)"
echo "agent_runtime_connect_phase|PREPARED_NOT_RUN"

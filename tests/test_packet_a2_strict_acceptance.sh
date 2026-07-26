#!/usr/bin/env bash
# =============================================================================
# Focused tests for the A2 STRICT acceptance contract.
# =============================================================================
# Two surfaces are proven, both with throwaway git repos, PATH command-shims, and
# LOCAL fixture HTTP responses. NO real SHADOW_READER_DSN and NO real database are
# ever used; the packet is NEVER run against Postgres.
#
#   PART A — wrapper --preflight (packet_a2_read_plane_deploy.sh):
#     * accepts EXACTLY HTTP 503 + a truthful read_only, zero-authority, disconnected
#       body; rejects 000 / 200 / redirect / 404 / 500 and unhealthy 503 bodies;
#     * malformed / writer DSNs stay rejected; a password loaded with
#       rw/prod/postgres/admin is neither scanned nor printed;
#     * performs ZERO host mutation — proven by PATH fail-shims (cp/install/mkdir/ln/
#       systemctl-mutate/psql/pg_isready) that drop a sentinel + fail if ever invoked,
#       AND by before/after filesystem assertions.
#
#   PART B — inner --execute (deploy_read_mount.sh), the true mutation gate:
#     * REFUSES before any mutation when the pre-connect baseline != 503;
#     * a 503-after, a 200-with-non-read-only body, and a 200-with-authority=true each
#       trigger automatic rollback of BOTH backend and static;
#     * an execution-agent-enabled body triggers rollback;
#     * the valid 503-before + 200-after path SUCCEEDS;
#     * only the ONE named service is ever restarted.
#
# The pre-connect and post-connect reads hit the SAME URL, so the curl shim is a tiny
# state machine: the 1st read on READ_API_URL returns the PRE scenario, the 2nd+ the
# POST scenario. Health/agents reads are status-only and independent.
# =============================================================================
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_PACKET="$SELF_DIR/../scripts/operator_packets/packet_a2_read_plane_deploy.sh"
SRC_INNER="$SELF_DIR/../scripts/agent_runtime/deploy_read_mount.sh"
SRC_SERVER="$SELF_DIR/../scripts/portfolio_server.py"
[[ -f "$SRC_PACKET" ]] || { echo "cannot find packet under test: $SRC_PACKET" >&2; exit 1; }
[[ -f "$SRC_INNER"  ]] || { echo "cannot find inner under test: $SRC_INNER"  >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s\n     -> %s\n' "$1" "$2"; }

SENT="$WORK/sentinels"; mkdir -p "$SENT"
CURLSTATE="$WORK/curlstate"; mkdir -p "$CURLSTATE"

# --- valid fixture bodies (single line each) ---------------------------------
PRE_OK='{"read_only": true, "connected": false, "read_plane": "disconnected", "authority": {"mutation": false, "provider_call": false, "service_control": false, "schedule_change": false, "financial_action": false}}'
POST_OK='{"read_only": true, "connected": true, "reader_role": "agentic_runtime_reader", "execution_agents_enabled": false, "authority": {"mutation": false, "provider_call": false, "service_control": false, "schedule_change": false, "financial_action": false}}'
POST_NON_RO='{"read_only": false, "connected": true, "reader_role": "agentic_runtime_reader"}'
POST_AUTHZ='{"read_only": true, "connected": true, "reader_role": "agentic_runtime_reader", "authority": {"service_control": true}}'
POST_EXECAGENT='{"read_only": true, "connected": true, "reader_role": "agentic_runtime_reader", "execution_agents_enabled": true}'
PRE_503_CONNECTED='{"read_only": true, "connected": true}'        # 503 but claims healthy — must block
PRE_503_AUTHZ='{"read_only": true, "connected": false, "authority": {"mutation": true}}'

# --- curl shim: LOCAL fixtures only, never a real network --------------------
make_curl_shim() {
  local dst="$1"
  cat > "$dst" <<'SH'
#!/usr/bin/env bash
# Fixture curl. Classifies the URL, honours -w. READ_API is a 1st/2nd read machine.
url=""; wfmt=""; want_w=0
prev=""
for a in "$@"; do
  if [[ "$prev" == "-w" ]]; then wfmt="$a"; prev=""; continue; fi
  case "$a" in
    -w) want_w=1; prev="-w" ;;
    http://*|https://*) url="$a" ;;
    *) : ;;
  esac
done
: > "$SENT/curl.called"
status="000"; body=""
case "$url" in
  *health*) status="${SCEN_HEALTH:-200}" ;;
  *agents*) status="${SCEN_AGENTS:-200}" ;;
  *read*)
    n="$(cat "$CURLSTATE/read.n" 2>/dev/null || echo 0)"; n=$((n+1)); echo "$n" > "$CURLSTATE/read.n"
    if [[ "$n" -eq 1 ]]; then status="${SCEN_PRE_STATUS:-503}"; body="${SCEN_PRE_BODY:-}";
    else status="${SCEN_POST_STATUS:-200}"; body="${SCEN_POST_BODY:-}"; fi ;;
esac
if [[ "$want_w" == 1 ]]; then
  if [[ "$wfmt" == '%{http_code}' ]]; then printf '%s' "$status"; else printf '%s\n%s' "$body" "$status"; fi
else
  printf '%s' "$body"
fi
exit 0
SH
  chmod +x "$dst"
}

# =============================================================================
# PART A — wrapper --preflight
# =============================================================================
echo "== PART A: wrapper --preflight strict pre-connect baseline + zero-mutation =="

PA_SHIMS="$WORK/pa_shims"; mkdir -p "$PA_SHIMS"
# fail-on-invoke mutating shims: proving preflight does NO host mutation / DB call.
for tool in cp install mkdir ln psql pg_isready; do
  cat > "$PA_SHIMS/$tool" <<SH
#!/usr/bin/env bash
echo "FORBIDDEN preflight call: $tool \$*" >&2
: > "$SENT/mutate_$tool.called"
exit 77
SH
  chmod +x "$PA_SHIMS/$tool"
done
# systemctl: read verbs OK; mutating verbs are forbidden (sentinel + fail).
cat > "$PA_SHIMS/systemctl" <<SH
#!/usr/bin/env bash
case "\$1" in
  restart|reload|start|stop|try-restart|reload-or-restart)
    echo "FORBIDDEN preflight systemctl \$*" >&2; : > "$SENT/mutate_systemctl.called"; exit 77 ;;
  cat|status|show|is-enabled|is-active|list-unit-files) echo "unit \$2"; exit 0 ;;
  *) echo "systemctl \$*"; exit 0 ;;
esac
SH
chmod +x "$PA_SHIMS/systemctl"
# npm: must NOT be invoked during preflight (dry-run only notes it).
cat > "$PA_SHIMS/npm" <<SH
#!/usr/bin/env bash
echo "FORBIDDEN preflight npm \$*" >&2; : > "$SENT/mutate_npm.called"; exit 77
SH
chmod +x "$PA_SHIMS/npm"
make_curl_shim "$PA_SHIMS/curl"
PA_PATH="$PA_SHIMS:$PATH"    # git + python3 stay real, after the shim dir

# throwaway repo with the REAL packet + REAL inner (dry-run is reused by preflight)
PAREPO="$WORK/pa_repo"
mkdir -p "$PAREPO/scripts/operator_packets" "$PAREPO/scripts/agent_runtime" "$PAREPO/apps/command-center-v3"
cp "$SRC_PACKET" "$PAREPO/scripts/operator_packets/packet_a2_read_plane_deploy.sh"
cp "$SRC_INNER"  "$PAREPO/scripts/agent_runtime/deploy_read_mount.sh"
chmod +x "$PAREPO/scripts/operator_packets/packet_a2_read_plane_deploy.sh" "$PAREPO/scripts/agent_runtime/deploy_read_mount.sh"
printf '# fixture backend\nprint("ok")\n' > "$PAREPO/scripts/portfolio_server.py"
printf '{"name":"cc","version":"0.0.0"}\n' > "$PAREPO/apps/command-center-v3/package.json"
printf '__pycache__/\n*.pyc\ndist/\nnode_modules/\n' > "$PAREPO/.gitignore"
git -C "$PAREPO" init -q
git -C "$PAREPO" add -A
git -C "$PAREPO" -c user.email=t@t -c user.name=t commit -q -m init
PA_SHA="$(git -C "$PAREPO" rev-parse HEAD)"
PA_PACKET="$PAREPO/scripts/operator_packets/packet_a2_read_plane_deploy.sh"

# host fixtures (read-only for preflight)
PA_DEPLOY="$WORK/pa_deploy"
mkdir -p "$PA_DEPLOY/releases" "$PA_DEPLOY/backups" "$PA_DEPLOY/prev"
ln -sfn "$PA_DEPLOY/prev" "$PA_DEPLOY/current"
PA_BACKEND="$WORK/pa_service_portfolio_server.py"
printf 'OLD-BACKEND\n' > "$PA_BACKEND"

READER_URL="postgresql://agentic_runtime_reader:SomePass@127.0.0.1:5433/trade_ai_agentic_lab"
TRAP_PW="aRwProdPostgresAdmin123"
READER_TRAP_PW="postgresql://agentic_runtime_reader:${TRAP_PW}@127.0.0.1:5433/trade_ai_agentic_lab"

# snapshot of the deploy root + backend (to prove zero mutation)
pa_snapshot() { ( cd "$PA_DEPLOY" && ls -laR . ; readlink current ; cat "$PA_BACKEND" ) 2>/dev/null; }

run_preflight() {   # $1=dsn  $2=pre_status  $3=pre_body ; sets RC/OUT
  rm -f "$SENT"/*.called 2>/dev/null || true
  rm -f "$CURLSTATE/read.n" 2>/dev/null || true
  OUT="$(cd "$PAREPO" && PATH="$PA_PATH" \
      SENT="$SENT" CURLSTATE="$CURLSTATE" \
      SCEN_PRE_STATUS="$2" SCEN_PRE_BODY="$3" SCEN_HEALTH=200 SCEN_AGENTS=200 \
      SHADOW_READER_DSN="$1" \
      DEPLOY_ROOT="$PA_DEPLOY" BACKEND_FILE="$PA_BACKEND" RESTART_SERVICE="trade-ai.service" \
      HEALTH_URL="http://h/health" AGENTS_URL="http://h/agents" READ_API_URL="http://h/read" \
      bash "$PA_PACKET" "$PA_SHA" --preflight 2>&1)"; RC=$?
}
no_mutation() { ! ls "$SENT"/mutate_*.called >/dev/null 2>&1; }

# ---- (A1) ACCEPT exactly 503 + truthful zero-authority disconnected body ----
SNAP_BEFORE="$(pa_snapshot)"
run_preflight "$READER_URL" 503 "$PRE_OK"
if [[ $RC -eq 0 && "$OUT" == *"PREFLIGHT PASSED"* && "$OUT" == *"pre_connect_status=503"* && "$OUT" == *"host_mutations=0"* ]]; then
  ok "preflight ACCEPTS exactly 503 + truthful zero-authority disconnected body"
else bad "preflight ACCEPTS 503 truthful body" "rc=$RC out=$OUT"; fi
if no_mutation; then ok "preflight ACCEPT path performed NO cp/install/mkdir/ln/systemctl-mutate/DB call"; \
  else bad "preflight ACCEPT no mutation" "sent=$(ls "$SENT" 2>/dev/null)"; fi
SNAP_AFTER="$(pa_snapshot)"
if [[ "$SNAP_BEFORE" == "$SNAP_AFTER" ]]; then ok "preflight left deploy root + backend byte-identical (fs unchanged)"; \
  else bad "preflight fs unchanged" "deploy root or backend changed"; fi
if [[ "$OUT" == *"reader_role=agentic_runtime_reader"* ]]; then ok "preflight prints reader ROLE NAME only"; \
  else bad "preflight prints reader role" "out=$OUT"; fi
if [[ "$OUT" != *"127.0.0.1"* && "$OUT" != *"SomePass"* && "$OUT" != *"5433"* ]]; then ok "preflight never prints DSN host/port/password"; \
  else bad "preflight leaks DSN" "out=$OUT"; fi

# ---- (A2) REJECT non-503 statuses, fail-closed, no mutation -----------------
for st in 000 200 301 302 404 500; do
  run_preflight "$READER_URL" "$st" "$PRE_OK"
  if [[ $RC -ne 0 && "$OUT" == *"pre-connect baseline"* ]] && no_mutation; then
    ok "preflight REJECTS HTTP $st (fail-closed, no mutation)"
  else bad "preflight REJECTS HTTP $st" "rc=$RC out=$OUT sent=$(ls "$SENT" 2>/dev/null)"; fi
done

# ---- (A3) REJECT a 503 whose body lies (connected / authority) --------------
run_preflight "$READER_URL" 503 "$PRE_503_CONNECTED"
if [[ $RC -ne 0 && "$OUT" == *"pre-connect baseline"* ]] && no_mutation \
   && { [[ "$OUT" == *"healthy-connected"* ]] || [[ "$OUT" == *"disconnected/unavailable"* ]]; }; then
  ok "preflight REJECTS a 503 body that claims connected (fail-closed, no mutation)"
else bad "preflight REJECTS 503-connected body" "rc=$RC out=$OUT"; fi
run_preflight "$READER_URL" 503 "$PRE_503_AUTHZ"
if [[ $RC -ne 0 && "$OUT" == *"authority"* ]] && no_mutation; then ok "preflight REJECTS 503 body with authority=true"; \
  else bad "preflight REJECTS 503-authority body" "rc=$RC out=$OUT"; fi

# ---- (A4) writer / malformed DSN still rejected (exit 4), no mutation --------
run_preflight "postgresql://agentic_runtime_lab_rw:x@127.0.0.1:5433/db" 503 "$PRE_OK"
if [[ $RC -eq 4 ]] && no_mutation; then ok "preflight REJECTS writer DSN (*_rw) exit 4"; \
  else bad "preflight REJECTS writer DSN" "rc=$RC out=$OUT"; fi
run_preflight "not-a-dsn" 503 "$PRE_OK"
if [[ $RC -eq 4 && "$OUT" == *"malformed"* ]] && no_mutation; then ok "preflight REJECTS malformed DSN exit 4"; \
  else bad "preflight REJECTS malformed DSN" "rc=$RC out=$OUT"; fi
run_preflight "postgresql://postgres:x@127.0.0.1:5433/db" 503 "$PRE_OK"
if [[ $RC -eq 4 ]] && no_mutation; then ok "preflight REJECTS superuser DSN (postgres) exit 4"; \
  else bad "preflight REJECTS superuser DSN" "rc=$RC out=$OUT"; fi

# ---- (A5) trap password (rw/prod/postgres/admin) accepted & never printed ---
run_preflight "$READER_TRAP_PW" 503 "$PRE_OK"
if [[ $RC -eq 0 && "$OUT" == *"PREFLIGHT PASSED"* ]]; then ok "preflight ACCEPTS reader DSN whose PASSWORD carries rw/prod/postgres/admin"; \
  else bad "preflight ACCEPTS trap-password reader" "rc=$RC out=$OUT"; fi
if [[ "$OUT" != *"$TRAP_PW"* && "$OUT" != *"$READER_TRAP_PW"* ]]; then ok "preflight output leaks no password / DSN value"; \
  else bad "preflight leaks trap password" "out=$OUT"; fi

# =============================================================================
# PART B — inner --execute (the true mutation gate)
# =============================================================================
echo
echo "== PART B: inner deploy_read_mount.sh strict pre/post-connect + rollback =="

PB_SHIMS="$WORK/pb_shims"; mkdir -p "$PB_SHIMS"
# real cp/mkdir/ln/install (the inner genuinely stages/backs-up/swaps); shim only
# curl + systemctl (restart-log) + npm (build).  psql/pg_isready are fail-shims:
# the inner must NEVER touch a DB driver.
for tool in psql pg_isready; do
  cat > "$PB_SHIMS/$tool" <<SH
#!/usr/bin/env bash
echo "FORBIDDEN inner DB call: $tool \$*" >&2; : > "$SENT/db_$tool.called"; exit 77
SH
  chmod +x "$PB_SHIMS/$tool"
done
RESTARTLOG="$WORK/restart.log"
cat > "$PB_SHIMS/systemctl" <<SH
#!/usr/bin/env bash
case "\$1" in
  restart) echo "\$2" >> "$RESTARTLOG"; exit 0 ;;
  start|stop|reload|try-restart|reload-or-restart) echo "UNEXPECTED systemctl \$*" >&2; echo "OTHER:\$2" >> "$RESTARTLOG"; exit 0 ;;
  *) exit 0 ;;
esac
SH
chmod +x "$PB_SHIMS/systemctl"
cat > "$PB_SHIMS/npm" <<'SH'
#!/usr/bin/env bash
# 'ci' no-op; 'run build' emits a dist that satisfies the static safety gate.
if [[ "$1" == "run" && "$2" == "build" ]]; then
  mkdir -p dist
  printf 'agent-runtime-command-center-read-api-v1\n' > dist/index.js
fi
exit 0
SH
chmod +x "$PB_SHIMS/npm"
make_curl_shim "$PB_SHIMS/curl"
PB_PATH="$PB_SHIMS:$PATH"

# throwaway repo with the REAL inner + a distinctive repo backend marker
PBREPO="$WORK/pb_repo"
mkdir -p "$PBREPO/scripts/agent_runtime" "$PBREPO/apps/command-center-v3"
cp "$SRC_INNER" "$PBREPO/scripts/agent_runtime/deploy_read_mount.sh"
chmod +x "$PBREPO/scripts/agent_runtime/deploy_read_mount.sh"
printf '# NEW-BACKEND-MARKER\nprint("new")\n' > "$PBREPO/scripts/portfolio_server.py"
printf '{"name":"cc","version":"0.0.0"}\n' > "$PBREPO/apps/command-center-v3/package.json"
printf '__pycache__/\n*.pyc\ndist/\nnode_modules/\n' > "$PBREPO/.gitignore"
git -C "$PBREPO" init -q
git -C "$PBREPO" add -A
git -C "$PBREPO" -c user.email=t@t -c user.name=t commit -q -m init
PB_SHA="$(git -C "$PBREPO" rev-parse HEAD)"
PB_INNER="$PBREPO/scripts/agent_runtime/deploy_read_mount.sh"

# fresh host fixtures per inner run
pb_reset_host() {
  PB_DEPLOY="$WORK/pb_deploy"; rm -rf "$PB_DEPLOY"
  mkdir -p "$PB_DEPLOY/releases" "$PB_DEPLOY/backups" "$PB_DEPLOY/prev"
  ln -sfn "$PB_DEPLOY/prev" "$PB_DEPLOY/current"
  PB_BACKEND="$WORK/pb_backend.py"; printf 'OLD-BACKEND-MARKER\nprint("old")\n' > "$PB_BACKEND"
  rm -f "$RESTARTLOG" "$CURLSTATE/read.n" 2>/dev/null || true
  : > "$RESTARTLOG"
  # clean the built dist so a fresh build is observable
  rm -rf "$PBREPO/apps/command-center-v3/dist"
}

run_inner() {   # $1=pre_status $2=pre_body $3=post_status $4=post_body ; RC/OUT
  pb_reset_host
  rm -f "$SENT"/db_*.called 2>/dev/null || true
  OUT="$(cd "$PBREPO" && printf 'DEPLOY %s\n' "$PB_SHA" | PATH="$PB_PATH" \
      SENT="$SENT" CURLSTATE="$CURLSTATE" \
      SCEN_PRE_STATUS="$1" SCEN_PRE_BODY="$2" SCEN_POST_STATUS="$3" SCEN_POST_BODY="$4" \
      SCEN_HEALTH=200 SCEN_AGENTS=200 \
      DEPLOY_ROOT="$PB_DEPLOY" BACKEND_FILE="$PB_BACKEND" RESTART_SERVICE="trade-ai.service" \
      HEALTH_URL="http://h/health" AGENTS_URL="http://h/agents" READ_API_URL="http://h/read" \
      AGENT_RUNTIME_READER_DSN="reader" \
      bash "$PB_INNER" "$PB_SHA" --execute 2>&1)"; RC=$?
}
backend_is_new() { grep -q 'NEW-BACKEND-MARKER' "$PB_BACKEND" 2>/dev/null; }
backend_is_old() { grep -q 'OLD-BACKEND-MARKER' "$PB_BACKEND" 2>/dev/null; }
current_into_releases() { readlink "$PB_DEPLOY/current" 2>/dev/null | grep -q "/releases/"; }
current_is_prev() { [[ "$(readlink -f "$PB_DEPLOY/current" 2>/dev/null)" == "$(readlink -f "$PB_DEPLOY/prev")" ]]; }
releases_empty() { [[ -z "$(ls -A "$PB_DEPLOY/releases" 2>/dev/null)" ]]; }
only_named_restart() { # every restart-log line is the one named service
  [[ -s "$RESTARTLOG" ]] || return 1
  ! grep -qv '^trade-ai\.service$' "$RESTARTLOG"
}
no_db_call() { ! ls "$SENT"/db_*.called >/dev/null 2>&1; }

# ---- (B1) valid 503-before + 200-after => SUCCESS ---------------------------
run_inner 503 "$PRE_OK" 200 "$POST_OK"
if [[ $RC -eq 0 && "$OUT" == *"STRICT pre-connect baseline OK"* && "$OUT" == *"STRICT post-connect acceptance OK"* ]]; then
  ok "inner SUCCEEDS on valid 503-before + 200-after"
else bad "inner SUCCEEDS valid path" "rc=$RC out=$OUT"; fi
if backend_is_new && current_into_releases; then ok "success installed new backend + flipped static into releases/"; \
  else bad "success installed new backend + static" "backend/current wrong"; fi
if only_named_restart && [[ "$(wc -l < "$RESTARTLOG")" -eq 1 ]]; then ok "success restarted ONLY trade-ai.service, exactly once"; \
  else bad "success restart once, named only" "log=$(cat "$RESTARTLOG")"; fi
if no_db_call; then ok "success path made NO psql/pg_isready DB call"; else bad "success no DB call" "sent=$(ls "$SENT")"; fi

# ---- (B2) execute REFUSES before any mutation when baseline != 503 ----------
run_inner 200 "$PRE_OK" 200 "$POST_OK"
if [[ $RC -ne 0 && "$OUT" == *"STRICT pre-connect baseline: READ_API HTTP 200"* ]]; then
  ok "inner REFUSES when pre-connect baseline != 503 (HTTP 200)"
else bad "inner REFUSES bad baseline" "rc=$RC out=$OUT"; fi
if backend_is_old && current_is_prev && releases_empty && [[ ! -s "$RESTARTLOG" ]]; then
  ok "baseline-refusal did ZERO mutation (backend/static untouched, no restart, no release staged)"
else bad "baseline-refusal zero mutation" "backend/current/releases/restart changed; log=$(cat "$RESTARTLOG")"; fi
# a 000 baseline blocks the same way
run_inner 000 "" 200 "$POST_OK"
if [[ $RC -ne 0 && "$OUT" == *"STRICT pre-connect baseline: READ_API HTTP 000"* ]] && backend_is_old && [[ ! -s "$RESTARTLOG" ]]; then
  ok "inner REFUSES on 000 baseline (connection failure), no mutation"
else bad "inner REFUSES 000 baseline" "rc=$RC out=$OUT"; fi

# ---- (B3) 503-after => FAILED deploy => rollback of backend AND static -------
run_inner 503 "$PRE_OK" 503 "$PRE_OK"
if [[ $RC -ne 0 && "$OUT" == *"ROLLBACK"* && "$OUT" == *"503-after is a FAILED deploy"* ]]; then
  ok "inner ROLLS BACK on a 503-after"
else bad "inner rollback on 503-after" "rc=$RC out=$OUT"; fi
if backend_is_old && current_is_prev; then ok "503-after rollback restored BOTH backend and static"; \
  else bad "503-after rollback restores both" "backend/current not restored"; fi
if only_named_restart && [[ "$(wc -l < "$RESTARTLOG")" -eq 2 ]]; then ok "503-after: deploy + rollback each restarted ONLY the named service"; \
  else bad "503-after restart named twice" "log=$(cat "$RESTARTLOG")"; fi

# ---- (B4) 200-after with a NON-read-only body => rollback -------------------
run_inner 503 "$PRE_OK" 200 "$POST_NON_RO"
if [[ $RC -ne 0 && "$OUT" == *"ROLLBACK"* && "$OUT" == *"not read_only"* ]] && backend_is_old && current_is_prev; then
  ok "inner ROLLS BACK on 200 with a non-read-only body (both restored)"
else bad "inner rollback on 200 non-read-only" "rc=$RC out=$OUT"; fi

# ---- (B5) 200-after with any authority=true => rollback ---------------------
run_inner 503 "$PRE_OK" 200 "$POST_AUTHZ"
if [[ $RC -ne 0 && "$OUT" == *"ROLLBACK"* && "$OUT" == *"non-zero authority"* ]] && backend_is_old && current_is_prev; then
  ok "inner ROLLS BACK on 200 with authority=true (both restored)"
else bad "inner rollback on 200 authority=true" "rc=$RC out=$OUT"; fi

# ---- (B6) 200-after showing an execution agent enabled => rollback ----------
run_inner 503 "$PRE_OK" 200 "$POST_EXECAGENT"
if [[ $RC -ne 0 && "$OUT" == *"ROLLBACK"* && "$OUT" == *"execution agent enabled/promoted"* ]] && backend_is_old && current_is_prev; then
  ok "inner ROLLS BACK on 200 showing an execution agent enabled (no exec-agent promotion accepted)"
else bad "inner rollback on execution-agent-enabled" "rc=$RC out=$OUT"; fi

echo
echo "== RESULT: $PASS passed, $FAIL failed =="
[[ $FAIL -eq 0 ]]

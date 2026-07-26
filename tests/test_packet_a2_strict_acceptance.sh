#!/usr/bin/env bash
# =============================================================================
# Focused tests for the A2 STRICT acceptance contract — THIS HOST's model.
# =============================================================================
# Two surfaces are proven, both with throwaway git repos, PATH command-shims, and
# LOCAL fixture HTTP responses. NO real SHADOW_READER_DSN and NO real database are
# ever used; the packet is NEVER run against Postgres and NEVER against a real
# systemctl. A FAKE reader DSN is used throughout.
#
# HOST MODEL under test:
#   * restart is USER-level: `systemctl --user restart <unit>` (NO sudo/system unit);
#   * /v3 is served DIRECTLY from a real STATIC_DIR (apps/command-center-v3/dist),
#     deployed by an atomic build-to-staging + swap (NOT a releases/current symlink);
#   * the CONNECT step writes a mode-0600 reader env-file (AGENT_RUNTIME_READ_API=1 +
#     AGENT_RUNTIME_READ_DSN=<dsn>) and a user-systemd drop-in (EnvironmentFile=...),
#     then `systemctl --user daemon-reload` — without which the read plane stays 503.
#
#   PART A — wrapper --preflight (packet_a2_read_plane_deploy.sh):
#     * accepts EXACTLY HTTP 503 + a truthful read_only, zero-authority, disconnected
#       body; rejects 000 / 200 / redirect / 404 / 500 and unhealthy 503 bodies;
#     * malformed / writer DSNs stay rejected; a password loaded with
#       rw/prod/postgres/admin is neither scanned nor printed;
#     * performs ZERO host mutation — proven by PATH fail-shims (cp/install/mkdir/ln/
#       systemctl-mutate/daemon-reload/npm/psql/pg_isready) that drop a sentinel + fail
#       if ever invoked, AND by before/after filesystem assertions;
#     * prints STATIC_DIR + reader env-file + drop-in + user restart unit (no DSN).
#
#   PART B — inner --execute (deploy_read_mount.sh), the true mutation gate:
#     * REFUSES before any mutation when the pre-connect baseline != 503;
#     * the valid 503-before + 200-after path SUCCEEDS: builds to staging, swaps the
#       new bundle into STATIC_DIR, writes the 0600 env-file + drop-in, restarts ONLY
#       the named USER unit once (via `systemctl --user`), DSN never printed;
#     * a 503-after, a 200-with-non-read-only body, a 200-with-authority=true, and an
#       execution-agent-enabled body each trigger the FULL rollback: DISCONNECT (remove
#       env-file + drop-in, daemon-reload, restart -> 503) + restore backend + restore
#       STATIC_DIR;
#     * only the ONE named USER unit is ever restarted; no system systemctl is used.
#
# The pre-connect and post-connect reads hit the SAME URL, so the curl shim is a tiny
# state machine: the 1st read on READ_API_URL returns the PRE scenario, the 2nd+ the
# POST scenario. Health/agents reads are status-only and independent.
# =============================================================================
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_PACKET="$SELF_DIR/../scripts/operator_packets/packet_a2_read_plane_deploy.sh"
SRC_INNER="$SELF_DIR/../scripts/agent_runtime/deploy_read_mount.sh"
[[ -f "$SRC_PACKET" ]] || { echo "cannot find packet under test: $SRC_PACKET" >&2; exit 1; }
[[ -f "$SRC_INNER"  ]] || { echo "cannot find inner under test: $SRC_INNER"  >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s\n     -> %s\n' "$1" "$2"; }

SENT="$WORK/sentinels"; mkdir -p "$SENT"
CURLSTATE="$WORK/curlstate"; mkdir -p "$CURLSTATE"

# --- FAKE reader DSN (NEVER real) --------------------------------------------
FAKE_DSN="postgresql://agentic_runtime_reader:FakePw@127.0.0.1:5433/trade_ai_agentic_lab"

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
# systemctl: --user read verbs OK; mutating verbs (incl. daemon-reload) forbidden.
cat > "$PA_SHIMS/systemctl" <<SH
#!/usr/bin/env bash
# forbid a SYSTEM (non --user) systemctl entirely on this host.
if [[ "\$1" != "--user" ]]; then
  echo "FORBIDDEN system systemctl \$*" >&2; : > "$SENT/mutate_systemctl.called"; exit 77
fi
shift
case "\$1" in
  restart|reload|start|stop|try-restart|reload-or-restart|daemon-reload)
    echo "FORBIDDEN preflight systemctl --user \$*" >&2; : > "$SENT/mutate_systemctl.called"; exit 77 ;;
  cat|status|show|is-enabled|is-active|list-unit-files) echo "unit \$2"; exit 0 ;;
  *) echo "systemctl --user \$*"; exit 0 ;;
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

# host fixtures (read-only for preflight): a real STATIC_DIR + backend + fresh HOME.
PA_STATIC="$WORK/pa_static_dist"
mkdir -p "$PA_STATIC"
printf '<html>OLD</html>\n' > "$PA_STATIC/index.html"
PA_BACKEND="$WORK/pa_service_portfolio_server.py"
printf 'OLD-BACKEND\n' > "$PA_BACKEND"
PA_HOME="$WORK/pa_home"; mkdir -p "$PA_HOME"
PA_BACKUP_ROOT="$WORK/pa_backups"; mkdir -p "$PA_BACKUP_ROOT"

READER_URL="$FAKE_DSN"
TRAP_PW="aRwProdPostgresAdmin123"
READER_TRAP_PW="postgresql://agentic_runtime_reader:${TRAP_PW}@127.0.0.1:5433/trade_ai_agentic_lab"

# snapshot of the static dir + backend + HOME (to prove zero mutation)
pa_snapshot() { ( ls -laR "$PA_STATIC" ; cat "$PA_BACKEND" ; ls -laR "$PA_HOME" ) 2>/dev/null; }

run_preflight() {   # $1=dsn  $2=pre_status  $3=pre_body ; sets RC/OUT
  rm -f "$SENT"/*.called 2>/dev/null || true
  rm -f "$CURLSTATE/read.n" 2>/dev/null || true
  OUT="$(cd "$PAREPO" && PATH="$PA_PATH" HOME="$PA_HOME" \
      SENT="$SENT" CURLSTATE="$CURLSTATE" \
      SCEN_PRE_STATUS="$2" SCEN_PRE_BODY="$3" SCEN_HEALTH=200 SCEN_AGENTS=200 \
      SHADOW_READER_DSN="$1" \
      STATIC_DIR="$PA_STATIC" BACKEND_FILE="$PA_BACKEND" RESTART_SERVICE="portfolio-server.service" \
      A2_BACKUP_ROOT="$PA_BACKUP_ROOT" \
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
if no_mutation; then ok "preflight ACCEPT path performed NO cp/install/mkdir/ln/systemctl-mutate/daemon-reload/npm/DB call"; \
  else bad "preflight ACCEPT no mutation" "sent=$(ls "$SENT" 2>/dev/null)"; fi
SNAP_AFTER="$(pa_snapshot)"
if [[ "$SNAP_BEFORE" == "$SNAP_AFTER" ]]; then ok "preflight left STATIC_DIR + backend + HOME byte-identical (fs unchanged)"; \
  else bad "preflight fs unchanged" "static/backend/home changed"; fi
# new-model summary fields present
if [[ "$OUT" == *"static_dir=$PA_STATIC"* ]]; then ok "preflight prints static_dir (live serving root)"; \
  else bad "preflight prints static_dir" "out=$OUT"; fi
if [[ "$OUT" == *"restart_service=portfolio-server.service (systemctl --user)"* ]]; then ok "preflight prints the USER restart unit"; \
  else bad "preflight prints user restart unit" "out=$OUT"; fi
if [[ "$OUT" == *"reader_env_file=$PA_HOME/.config/tradeai/agent-read-api.env"* ]]; then ok "preflight prints reader env-file path"; \
  else bad "preflight prints reader env-file path" "out=$OUT"; fi
if [[ "$OUT" == *"reader_dropin=$PA_HOME/.config/systemd/user/portfolio-server.service.d/10-agent-read-api.conf"* ]]; then ok "preflight prints reader drop-in path"; \
  else bad "preflight prints reader drop-in path" "out=$OUT"; fi
if [[ "$OUT" == *"reader_role=agentic_runtime_reader"* ]]; then ok "preflight prints reader ROLE NAME only"; \
  else bad "preflight prints reader role" "out=$OUT"; fi
if [[ "$OUT" != *"127.0.0.1"* && "$OUT" != *"FakePw"* && "$OUT" != *"5433"* ]]; then ok "preflight never prints DSN host/port/password"; \
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
echo "== PART B: inner deploy_read_mount.sh strict pre/post-connect + connect + rollback =="

PB_SHIMS="$WORK/pb_shims"; mkdir -p "$PB_SHIMS"
# real cp/mkdir/ln/install (the inner genuinely stages/backs-up/swaps); shim only
# curl + systemctl (--user restart/daemon-reload log) + npm (build).  psql/pg_isready
# are fail-shims: the inner must NEVER touch a DB driver.
for tool in psql pg_isready; do
  cat > "$PB_SHIMS/$tool" <<SH
#!/usr/bin/env bash
echo "FORBIDDEN inner DB call: $tool \$*" >&2; : > "$SENT/db_$tool.called"; exit 77
SH
  chmod +x "$PB_SHIMS/$tool"
done
RESTARTLOG="$WORK/restart.log"
RELOADLOG="$WORK/reload.log"
# systemctl: require --user; log restarts + daemon-reloads; a SYSTEM systemctl is a fault.
cat > "$PB_SHIMS/systemctl" <<SH
#!/usr/bin/env bash
if [[ "\$1" != "--user" ]]; then
  echo "SYSTEM systemctl \$*" >&2; : > "$SENT/system_systemctl.called"; exit 1
fi
shift
case "\$1" in
  restart) echo "\$2" >> "$RESTARTLOG"; exit 0 ;;
  daemon-reload) echo "daemon-reload" >> "$RELOADLOG"; exit 0 ;;
  start|stop|reload|try-restart|reload-or-restart) echo "UNEXPECTED systemctl --user \$*" >&2; echo "OTHER:\$2" >> "$RESTARTLOG"; exit 0 ;;
  *) exit 0 ;;
esac
SH
chmod +x "$PB_SHIMS/systemctl"
# npm: 'ci' no-op; 'run build ... --outDir DIR' emits a dist into DIR that satisfies
# the static safety gate and carries a NEW marker so the swap is observable.
cat > "$PB_SHIMS/npm" <<'SH'
#!/usr/bin/env bash
if [[ "$1" == "run" && "$2" == "build" ]]; then
  out="dist"; prev=""
  for a in "$@"; do
    if [[ "$prev" == "--outDir" ]]; then out="$a"; prev=""; fi
    [[ "$a" == "--outDir" ]] && prev="--outDir"
  done
  mkdir -p "$out"
  printf 'agent-runtime-command-center-read-api-v1\nNEW-STATIC-MARKER\n' > "$out/index.js"
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

PB_UNIT="portfolio-server.service"

# fresh host fixtures per inner run
pb_reset_host() {
  PB_STATIC="$WORK/pb_static_dist"; rm -rf "$PB_STATIC"
  mkdir -p "$PB_STATIC"; printf 'OLD-STATIC-MARKER\n' > "$PB_STATIC/index.js"
  PB_BACKEND="$WORK/pb_backend.py"; printf 'OLD-BACKEND-MARKER\nprint("old")\n' > "$PB_BACKEND"
  PB_HOME="$WORK/pb_home"; rm -rf "$PB_HOME"; mkdir -p "$PB_HOME"
  PB_BACKUP_ROOT="$WORK/pb_backups"; rm -rf "$PB_BACKUP_ROOT"; mkdir -p "$PB_BACKUP_ROOT"
  rm -f "$RESTARTLOG" "$RELOADLOG" "$CURLSTATE/read.n" 2>/dev/null || true
  : > "$RESTARTLOG"; : > "$RELOADLOG"
}

run_inner() {   # $1=pre_status $2=pre_body $3=post_status $4=post_body ; RC/OUT
  pb_reset_host
  rm -f "$SENT"/db_*.called "$SENT"/system_systemctl.called 2>/dev/null || true
  OUT="$(cd "$PBREPO" && printf 'DEPLOY %s\n' "$PB_SHA" | PATH="$PB_PATH" HOME="$PB_HOME" \
      SENT="$SENT" CURLSTATE="$CURLSTATE" \
      SCEN_PRE_STATUS="$1" SCEN_PRE_BODY="$2" SCEN_POST_STATUS="$3" SCEN_POST_BODY="$4" \
      SCEN_HEALTH=200 SCEN_AGENTS=200 \
      STATIC_DIR="$PB_STATIC" BACKEND_FILE="$PB_BACKEND" RESTART_SERVICE="$PB_UNIT" \
      A2_BACKUP_ROOT="$PB_BACKUP_ROOT" \
      HEALTH_URL="http://h/health" AGENTS_URL="http://h/agents" READ_API_URL="http://h/read" \
      SHADOW_READER_DSN="$FAKE_DSN" \
      bash "$PB_INNER" "$PB_SHA" --execute 2>&1)"; RC=$?
}

ENVFILE() { echo "$PB_HOME/.config/tradeai/agent-read-api.env"; }
DROPIN()  { echo "$PB_HOME/.config/systemd/user/$PB_UNIT.d/10-agent-read-api.conf"; }
backend_is_new() { grep -q 'NEW-BACKEND-MARKER' "$PB_BACKEND" 2>/dev/null; }
backend_is_old() { grep -q 'OLD-BACKEND-MARKER' "$PB_BACKEND" 2>/dev/null; }
static_is_new()  { grep -rq 'NEW-STATIC-MARKER' "$PB_STATIC" 2>/dev/null; }
static_is_old()  { grep -rq 'OLD-STATIC-MARKER' "$PB_STATIC" 2>/dev/null; }
envfile_present(){ [[ -f "$(ENVFILE)" ]]; }
envfile_absent() { [[ ! -e "$(ENVFILE)" ]]; }
dropin_present() { [[ -f "$(DROPIN)" ]]; }
dropin_absent()  { [[ ! -e "$(DROPIN)" ]]; }
envfile_mode_0600() { [[ "$(stat -c '%a' "$(ENVFILE)" 2>/dev/null)" == "600" ]]; }
envfile_has_wiring() { grep -q '^AGENT_RUNTIME_READ_API=1$' "$(ENVFILE)" 2>/dev/null \
                       && grep -q "^AGENT_RUNTIME_READ_DSN=$FAKE_DSN\$" "$(ENVFILE)" 2>/dev/null; }
dropin_has_envfile() { grep -q "^EnvironmentFile=$(ENVFILE)\$" "$(DROPIN)" 2>/dev/null; }
dsn_not_in_out() { [[ "$OUT" != *"$FAKE_DSN"* && "$OUT" != *"FakePw"* ]]; }
only_named_restart() { # every restart-log line is the one named USER service
  [[ -s "$RESTARTLOG" ]] || return 1
  ! grep -qv "^${PB_UNIT}\$" "$RESTARTLOG"
}
no_system_systemctl() { [[ ! -e "$SENT/system_systemctl.called" ]]; }
no_db_call() { ! ls "$SENT"/db_*.called >/dev/null 2>&1; }

# ---- (B1) valid 503-before + 200-after => SUCCESS ---------------------------
run_inner 503 "$PRE_OK" 200 "$POST_OK"
if [[ $RC -eq 0 && "$OUT" == *"STRICT pre-connect baseline OK"* && "$OUT" == *"STRICT post-connect acceptance OK"* ]]; then
  ok "inner SUCCEEDS on valid 503-before + 200-after"
else bad "inner SUCCEEDS valid path" "rc=$RC out=$OUT"; fi
if backend_is_new && static_is_new; then ok "success installed new backend + swapped new bundle into STATIC_DIR"; \
  else bad "success installed new backend + static" "backend/static wrong"; fi
if envfile_present && envfile_mode_0600 && envfile_has_wiring; then ok "success wrote 0600 reader env-file (API=1 + DSN)"; \
  else bad "success wrote 0600 env-file" "mode=$(stat -c '%a' "$(ENVFILE)" 2>/dev/null) present=$(envfile_present && echo y || echo n)"; fi
if dropin_present && dropin_has_envfile; then ok "success installed user-systemd drop-in (EnvironmentFile=<env file>)"; \
  else bad "success installed drop-in" "dropin missing/wrong"; fi
if [[ -s "$RELOADLOG" ]]; then ok "success ran systemctl --user daemon-reload"; else bad "success daemon-reload" "reloadlog empty"; fi
if only_named_restart && no_system_systemctl && [[ "$(wc -l < "$RESTARTLOG")" -eq 1 ]]; then ok "success restarted ONLY $PB_UNIT via systemctl --user, exactly once"; \
  else bad "success restart once, named user only" "log=$(cat "$RESTARTLOG") system=$(no_system_systemctl && echo none || echo yes)"; fi
if dsn_not_in_out; then ok "success NEVER printed the DSN / password"; else bad "success DSN leak" "out contains DSN"; fi
if no_db_call; then ok "success path made NO psql/pg_isready DB call"; else bad "success no DB call" "sent=$(ls "$SENT")"; fi

# ---- (B2) execute REFUSES before any mutation when baseline != 503 ----------
run_inner 200 "$PRE_OK" 200 "$POST_OK"
if [[ $RC -ne 0 && "$OUT" == *"STRICT pre-connect baseline: READ_API HTTP 200"* ]]; then
  ok "inner REFUSES when pre-connect baseline != 503 (HTTP 200)"
else bad "inner REFUSES bad baseline" "rc=$RC out=$OUT"; fi
if backend_is_old && static_is_old && envfile_absent && dropin_absent && [[ ! -s "$RESTARTLOG" ]] && [[ ! -s "$RELOADLOG" ]]; then
  ok "baseline-refusal did ZERO mutation (backend/static untouched, no env-file/drop-in, no restart/reload)"
else bad "baseline-refusal zero mutation" "backend/static/env/restart changed"; fi
# a 000 baseline blocks the same way
run_inner 000 "" 200 "$POST_OK"
if [[ $RC -ne 0 && "$OUT" == *"STRICT pre-connect baseline: READ_API HTTP 000"* ]] && backend_is_old && envfile_absent && [[ ! -s "$RESTARTLOG" ]]; then
  ok "inner REFUSES on 000 baseline (connection failure), no mutation"
else bad "inner REFUSES 000 baseline" "rc=$RC out=$OUT"; fi

# ---- (B3) 503-after => FAILED deploy => DISCONNECT + rollback ----------------
run_inner 503 "$PRE_OK" 503 "$PRE_OK"
if [[ $RC -ne 0 && "$OUT" == *"ROLLBACK"* && "$OUT" == *"503-after is a FAILED deploy"* ]]; then
  ok "inner ROLLS BACK on a 503-after"
else bad "inner rollback on 503-after" "rc=$RC out=$OUT"; fi
if backend_is_old && static_is_old; then ok "503-after rollback restored BOTH backend and STATIC_DIR"; \
  else bad "503-after rollback restores both" "backend/static not restored"; fi
if envfile_absent && dropin_absent; then ok "503-after rollback DISCONNECTED (removed env-file + drop-in)"; \
  else bad "503-after disconnect" "env-file/drop-in still present"; fi
if only_named_restart && no_system_systemctl && [[ "$(wc -l < "$RESTARTLOG")" -eq 2 ]]; then ok "503-after: deploy + rollback each restarted ONLY $PB_UNIT via --user"; \
  else bad "503-after restart named twice" "log=$(cat "$RESTARTLOG")"; fi
if dsn_not_in_out; then ok "503-after path NEVER printed the DSN"; else bad "503-after DSN leak" "out has DSN"; fi

# ---- (B4) 200-after with a NON-read-only body => DISCONNECT + rollback -------
run_inner 503 "$PRE_OK" 200 "$POST_NON_RO"
if [[ $RC -ne 0 && "$OUT" == *"ROLLBACK"* && "$OUT" == *"not read_only"* ]] \
   && backend_is_old && static_is_old && envfile_absent && dropin_absent; then
  ok "inner ROLLS BACK + DISCONNECTS on 200 with a non-read-only body"
else bad "inner rollback on 200 non-read-only" "rc=$RC out=$OUT"; fi

# ---- (B5) 200-after with any authority=true => DISCONNECT + rollback ---------
run_inner 503 "$PRE_OK" 200 "$POST_AUTHZ"
if [[ $RC -ne 0 && "$OUT" == *"ROLLBACK"* && "$OUT" == *"non-zero authority"* ]] \
   && backend_is_old && static_is_old && envfile_absent && dropin_absent; then
  ok "inner ROLLS BACK + DISCONNECTS on 200 with authority=true"
else bad "inner rollback on 200 authority=true" "rc=$RC out=$OUT"; fi

# ---- (B6) 200-after showing an execution agent enabled => DISCONNECT+rollback ---
run_inner 503 "$PRE_OK" 200 "$POST_EXECAGENT"
if [[ $RC -ne 0 && "$OUT" == *"ROLLBACK"* && "$OUT" == *"execution agent enabled/promoted"* ]] \
   && backend_is_old && static_is_old && envfile_absent && dropin_absent; then
  ok "inner ROLLS BACK + DISCONNECTS on 200 showing an execution agent enabled"
else bad "inner rollback on execution-agent-enabled" "rc=$RC out=$OUT"; fi

echo
echo "== RESULT: $PASS passed, $FAIL failed =="
[[ $FAIL -eq 0 ]]

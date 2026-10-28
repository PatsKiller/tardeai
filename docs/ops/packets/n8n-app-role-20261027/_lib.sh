# shellcheck shell=bash
# shellcheck disable=SC2034  # settings are read by the numbered scripts that source this file
# _lib.sh — shared settings and helpers for packet n8n-app-role-20261027. Sourced by the numbered scripts; never run.
#
# Secrets: no value is read, printed or logged here. Container env is read one allowlisted, non-secret key at a time
# (the docker template filters inside docker); any other key is reported only as set/unset. A password moves only as
# a file (DB_POSTGRESDB_PASSWORD_FILE, written by scripts/ops/n8n_db_app_role.py) or stays inside the db container
# (POSTGRES_PASSWORD, read there by psql \getenv). Every SQL text starts with a "-- q:<name>" marker line.
# Nothing here deletes a file (AGENTS.md §0 rule 6): evidence and backups are kept, superseded files are renamed.

PACKET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$PACKET_DIR/../../../.." && pwd)}"
PY="${PY:-python3}"

LAB_DIR="${N8N_LAB_DIR:-$HOME/m8m-bakeoff-lab}"
COMPOSE_FILE="docker-compose.n8n.yml"
LIVE_COMPOSE="$LAB_DIR/$COMPOSE_FILE"
COMPOSE_PROJECT="m8m-n8n"
N8N_SERVICE="n8n"
N8N_CONTAINER="${N8N_CONTAINER:-m8m-n8n}"
DB_CONTAINER="${N8N_DB_CONTAINER:-m8m-n8n-db}"
VOLUMES=("m8m-n8n_n8n-data" "m8m-n8n_n8n-pg")
DB_NAME="n8n"
BOOTSTRAP_ROLE="n8n"
APP_ROLE="n8n_app"

BACKUP_DIR="${N8N_BACKUP_DIR:-$HOME/trade-ai-releases/persistent-state/backups/n8n}"
STATE_ROOT="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"
RELAY_LOG="${N8N_RELAY_LOG:-$STATE_ROOT/data/runtime/n8n_relay/relay_log.jsonl}"
EVIDENCE_DIR="${N8N_APP_ROLE_EVIDENCE_DIR:-$HOME/n8n-maturity-verification/packets/n8n-app-role-20261027}"
PASSWORD_FILE="${N8N_APP_PASSWORD_FILE:-$HOME/.config/tradeai/n8n/n8n_app_pg_password}"
HEALTHZ_URL="${N8N_HEALTHZ_URL:-http://127.0.0.1:5678/healthz}"
ROLE_SCRIPT="$REPO_ROOT/scripts/ops/n8n_db_app_role.py"
COMPOSE_DIFF="$REPO_ROOT/docs/ops/packets/n8n-platform-hardening-20261022/compose/fw-p2-n8n-app-role.compose.diff.proposed"
BACKUP_TAG="pre-n8n-app-role"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NOW_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

say() { printf '%s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*"; }
fail() {
  printf 'REFUSED: %s\n' "$*" >&2
  exit 2
}

# --apply needs the operator's guard grant id(s) in N8N_APP_ROLE_GRANT (recorded in the receipt, never a secret).
require_grant() {
  [[ -n "${N8N_APP_ROLE_GRANT:-}" ]] ||
    fail "--apply needs N8N_APP_ROLE_GRANT=<guard grant id(s)> ($1); see README 'Grants'"
}

# Read-only SQL as the bootstrap role over the db container's local socket (no host port, no password on this side).
# SQL arrives on stdin, so nothing is shell-quoted; the session runs read-only transactions.
sql_ro() {
  docker exec -i -e "PGOPTIONS=-c default_transaction_read_only=on" "$DB_CONTAINER" \
    psql -X -q -v ON_ERROR_STOP=1 -U "$BOOTSTRAP_ROLE" -d "$DB_NAME" -tA
}

# Writable SQL on the same path. Called only from --apply branches.
sql_rw() {
  docker exec -i "$DB_CONTAINER" psql -X -q -v ON_ERROR_STOP=1 -U "$BOOTSTRAP_ROLE" -d "$DB_NAME" -tA
}

q() { # q NAME SQL... — one marked query through sql_ro
  local name="$1"
  shift
  printf '%s\n' "-- q:$name" "$@" | sql_ro
}

valid_role_name() { [[ "$1" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; }

# The value of one NON-SECRET container env key. Refuses any key not on the allowlist.
container_env_value() {
  local key="$1" container="${2:-$N8N_CONTAINER}"
  case "$key" in
    DB_POSTGRESDB_USER | DB_POSTGRESDB_PASSWORD_FILE | DB_POSTGRESDB_DATABASE | DB_POSTGRESDB_HOST) ;;
    *) fail "container_env_value: $key is not on the non-secret allowlist" ;;
  esac
  docker inspect "$container" --format \
    "{{range .Config.Env}}{{if eq (index (split . \"=\") 0) \"$key\"}}{{println .}}{{end}}{{end}}" 2>/dev/null |
    sed -n "s/^$key=//p" | head -n 1
}

# "set" or "unset" for any container env key. The template emits a fixed word, so a value never leaves docker.
container_env_is_set() {
  local key="$1" container="${2:-$N8N_CONTAINER}" out
  out="$(docker inspect "$container" --format \
    "{{range .Config.Env}}{{if eq (index (split . \"=\") 0) \"$key\"}}set{{end}}{{end}}" 2>/dev/null || true)"
  if [[ "$out" == *set* ]]; then echo set; else echo unset; fi
}

compose() {
  (cd "$LAB_DIR" && docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" "$@")
}

# Validate a compose file without printing it: `config` WITHOUT --quiet prints interpolated secrets.
compose_config_quiet() {
  local file="$1"
  (cd "$LAB_DIR" && docker compose -p "$COMPOSE_PROJECT" --project-directory "$LAB_DIR" -f "$file" config --quiet)
}

sha256_of() { sha256sum -- "$1" | cut -c1-64; }

healthz_ok() {
  curl -fsS --max-time 3 "$HEALTHZ_URL" 2>/dev/null | grep -q '"status":"ok"'
}

wait_healthz() {
  local limit="${1:-180}" waited=0
  while true; do
    if healthz_ok; then
      say "  healthz ok after ${waited}s"
      return 0
    fi
    ((waited < limit)) || return 1
    sleep 5
    waited=$((waited + 5))
  done
}

# hh:05-hh:09 or hh:35-hh:39 (N8N_CONFIGURATION.md §1: hh:07 / hh:37, clear of the :00/:15/:30/:45 fires).
quiet_minute_now() {
  local m
  m=$((10#$(date +%M)))
  ((m >= 5 && m <= 9)) || ((m >= 35 && m <= 39))
}

# NYSE session state from the repo calendar (CLOSED / PRE / RTH / POST), or UNKNOWN.
market_state() {
  "$PY" -c 'import sys
sys.path.insert(0, sys.argv[1])
from scripts.lib.cio_market_session import market_session
print(market_session()["state"])' "$REPO_ROOT" 2>/dev/null || echo UNKNOWN
}

# Restart window for --apply on a step that recreates n8n: quiet minute, and not PRE/RTH (n8n schedules the advisory
# market-data lanes then). --ignore-window skips both, for an operator who has decided otherwise.
require_restart_window() {
  local ignore="$1" st
  [[ "$ignore" == 1 ]] && {
    warn "--ignore-window: quiet-minute and market-session checks skipped"
    return 0
  }
  quiet_minute_now || fail "not a quiet minute (run at hh:05-hh:09 or hh:35-hh:39), or pass --ignore-window"
  st="$(market_state)"
  case "$st" in
    CLOSED | POST) say "  market session $st" ;;
    *) fail "market session is $st; run outside PRE/RTH, or pass --ignore-window" ;;
  esac
}

active_workflows() {
  q active_workflows "select id from workflow_entity where active order by id;"
}

latest_preflight_snapshot() {
  local d
  d="$(cat "$EVIDENCE_DIR/LATEST_PREFLIGHT" 2>/dev/null || true)"
  [[ -n "$d" && -f "$EVIDENCE_DIR/$d/active_workflows.txt" ]] && printf '%s\n' "$EVIDENCE_DIR/$d/active_workflows.txt"
}

# Compare the live active-workflow ids with a snapshot file. Prints the diff; returns 0 when equal.
compare_active_workflows() {
  local snapshot="$1" now
  now="$(active_workflows)"
  if [[ "$now" == "$(cat -- "$snapshot")" ]]; then
    say "  active workflows: $(grep -c . <<<"$now") ids, identical to $snapshot"
    return 0
  fi
  say "  active workflows DIFFER from $snapshot (< snapshot, > now):"
  diff -- "$snapshot" <(printf '%s\n' "$now") | sed 's/^/    /' || true
  return 1
}

# Newest relay {"op": "due"} line strictly after an ISO-8601 instant. Prints its "at"; returns 1 when none.
relay_due_after() {
  "$PY" - "$RELAY_LOG" "$1" <<'PY'
import collections, json, sys
from datetime import datetime
path, since = sys.argv[1], sys.argv[2]
def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
try:
    with open(path, encoding="utf-8", errors="replace") as fh:
        tail = collections.deque(fh, maxlen=5000)
except OSError:
    sys.exit(1)
best = None
for line in tail:
    try:
        row = json.loads(line)
        if row.get("op") == "due" and ts(row["at"]) > ts(since):
            best = row["at"]
    except (ValueError, KeyError, TypeError, AttributeError):
        continue
if best is None:
    sys.exit(1)
print(best)
PY
}

wait_relay_due_after() {
  local since="$1" limit="${2:-300}" waited=0 at
  while true; do
    if at="$(relay_due_after "$since")"; then
      say "  relay op:due at $at (after $since)"
      return 0
    fi
    ((waited < limit)) || return 1
    sleep 10
    waited=$((waited + 10))
  done
}

# Network (TCP, non-loopback) login as the bootstrap role, run INSIDE the db container with the container's own
# POSTGRES_PASSWORD. Loopback is trust in the image's pg_hba, so the probe uses the container's network address.
# Prints LOGIN_OK, LOGIN_FAILED or LOGIN_UNKNOWN. The password never leaves the container.
bootstrap_network_login() {
  # shellcheck disable=SC2016  # expanded inside the container, not here
  docker exec "$DB_CONTAINER" sh -c '
    ip="$(hostname -i 2>/dev/null | tr " " "\n" | grep -v "^127\." | grep -v ":" | head -n 1)"
    [ -n "$ip" ] || { echo LOGIN_UNKNOWN; exit 0; }
    if PGPASSWORD="$POSTGRES_PASSWORD" PGCONNECT_TIMEOUT=5 psql -X -q -h "$ip" -U "$POSTGRES_USER" \
         -d "$POSTGRES_DB" -tAc "select 1" >/dev/null 2>&1; then echo LOGIN_OK; else echo LOGIN_FAILED; fi' 2>/dev/null ||
    echo LOGIN_UNKNOWN
}

bootstrap_password_is_null() {
  q bootstrap_password_null "select rolpassword is null from pg_authid where rolname = '$BOOTSTRAP_ROLE';"
}

# Undo step 05: set the bootstrap role's password back to the db container's POSTGRES_PASSWORD, read INSIDE the
# container by psql \getenv. The value is never on an argv, a host env, stdout or the server log.
restore_bootstrap_password() {
  [[ "$(container_env_is_set POSTGRES_PASSWORD "$DB_CONTAINER")" == set ]] ||
    fail "POSTGRES_PASSWORD is not set in $DB_CONTAINER; cannot restore the $BOOTSTRAP_ROLE password by name"
  # shellcheck disable=SC2016  # expanded inside the container, not here
  docker exec -i "$DB_CONTAINER" sh -c 'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
-- q:restore_bootstrap_password
SET log_statement = 'none';
SET log_min_error_statement = 'panic';
\getenv pw POSTGRES_PASSWORD
ALTER ROLE n8n PASSWORD :'pw';
SQL
}

# Minimal JSON receipt: write_receipt FILE key=value ... (values are strings; never pass a secret).
write_receipt() {
  local file="$1"
  shift
  mkdir -p "$(dirname "$file")"
  "$PY" - "$file" "$@" <<'PY'
import json, os, sys
path, pairs = sys.argv[1], sys.argv[2:]
doc = {"schema": "N8nAppRolePacketReceipt@v1", "packet": "n8n-app-role-20261027"}
for p in pairs:
    k, _, v = p.partition("=")
    doc[k] = v
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=1, sort_keys=True)
    fh.write("\n")
os.replace(tmp, path)
print("  receipt " + path)
PY
}

# Value of one key in a receipt written above (empty when absent or unreadable).
receipt_value() {
  "$PY" -c 'import json, sys
try:
    print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))
except (OSError, ValueError):
    print("")' "$1" "$2"
}

# Age in hours of an ISO-8601 instant (large number when unreadable).
hours_since() {
  "$PY" -c 'import sys
from datetime import datetime, timezone
try:
    t = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
    print(int((datetime.now(timezone.utc) - t).total_seconds() // 3600))
except ValueError:
    print(99999)' "$1"
}

newest() { # newest GLOB-DIR PATTERN — newest file by mtime, or empty
  find "$1" -maxdepth 1 -name "$2" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -n 1 | cut -d' ' -f2-
}

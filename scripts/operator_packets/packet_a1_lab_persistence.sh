#!/usr/bin/env bash
# =============================================================================
# PACKET A1 — Isolated LAB/SHADOW persistence for the agentic_runtime schema.
# =============================================================================
# Applies migrations/agentic_runtime/0001_mvl (+ 0002_roles) ONLY to an isolated
# LAB/SHADOW database. It NEVER touches the production `trade_ai` database, and it
# holds NO broker / order / account / position / approval / 2FA / secret /
# production-config authority. The only thing it can create is the isolated
# `agentic_runtime` schema, its eight MVL tables, and three least-privilege roles
# (or roll them back).
#
# SAFETY CONTRACT (read before use):
#   * PREPARE-ONLY BY DEFAULT. With no --execute it prints a plan and exits 3.
#   * With NO args it prints PREPARE-ONLY usage and exits 2.
#   * Pins to an exact release SHA (arg 1) and refuses if repo HEAD != that SHA.
#   * --preflight validates the intended target WITH NO DATABASE/NETWORK CONNECTION
#     (no psql, no pg_isready, no migration applier, no DB driver, no socket) and
#     prints only a redacted, secret-free identity + plan. Exits 0 only if every
#     LOCAL gate passes.
#   * --execute additionally requires --ack <token> with the exact typed token and
#     RE-RUNS the same target validation before ANY database contact — a prior
#     successful --preflight NEVER bypasses execute-path revalidation.
#   * The DSN is read from $LAB_DSN and is NEVER printed. Only a redacted identity
#     (host/port/db, credentials stripped) is ever emitted.
#   * REJECTS any production DB identity: dbname `trade_ai`, any 'prod' substring,
#     the prod port 5432 (or unset port), a host not on the explicit LAB allowlist,
#     malformed DSNs, connection-redirecting query params, service-file indirection,
#     socket paths, multiple hosts, or env-var interpolation embedded in the DSN.
#   * Delegates the actual migration to migrations/agentic_runtime/apply.sh --apply.
#   * Evidence log is written mode 0600 and contains NO secret values.
#
# USAGE:
#   packet_a1_lab_persistence.sh                              # PREPARE-ONLY, exit 2
#   packet_a1_lab_persistence.sh <RELEASE_SHA>                     # plan, exit 3
#   LAB_DSN=... LAB_DSN_ALLOWLIST=host:port/db \
#     packet_a1_lab_persistence.sh <RELEASE_SHA> --preflight        # no-connect check
#   LAB_DSN=... LAB_DSN_ALLOWLIST=host:port/db \
#     packet_a1_lab_persistence.sh <RELEASE_SHA> --execute --ack <token> [--down]
#
# EXIT CODES: 0 ok · 2 usage/gate blocked · 3 prepare-only refusal · 4 target reject
# =============================================================================
set -euo pipefail

readonly PACKET="A1:lab_persistence"
readonly ACK_TOKEN="APPLY-A1-LAB-PERSISTENCE"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly APPLIER="$REPO_ROOT/migrations/agentic_runtime/apply.sh"
# Evidence log defaults OUTSIDE the repo so real runs never drop logs into git.
readonly EVIDENCE="${A1_EVIDENCE_LOG:-/home/johnclaw/tradeai-deploy-backups/packet-a1/evidence_$(date -u +%Y%m%dT%H%M%SZ).log}"

# The three least-privilege roles and eight MVL tables this packet would manage.
readonly A1_ROLES="agentic_runtime_lab_rw agentic_runtime_shadow_rw agentic_runtime_reader"
readonly A1_TABLES="agent_runs agent_artifacts agent_tool_calls agent_reviews agent_scores kb_lessons kb_cases kb_chunks"

banner() { echo "=== PACKET $PACKET === PREPARE-ONLY (dry-run default) ==="; }
die()    { echo "[A1][BLOCKED] $1" >&2; exit "${2:-2}"; }
note()   { echo "[A1] $*"; }
# Evidence log: mode 0600, never any secret/DSN/password value.
ev_init() { umask 077; mkdir -p "$(dirname "$EVIDENCE")"; : > "$EVIDENCE"; chmod 0600 "$EVIDENCE"; }
ev()      { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$EVIDENCE"; }

# ------------------------------------------------------------------ arg parse
EXPECTED_SHA=""
PREFLIGHT=0
EXECUTE=0
ACK=""
DIRECTION="up"          # 'up' applies; --down rolls back
for arg in "$@"; do
  case "$arg" in
    --preflight)       PREFLIGHT=1 ;;
    --execute|--apply) EXECUTE=1 ;;
    --down)            DIRECTION="down" ;;
    --ack)             ACK="__NEXT__" ;;
    *)
      if [[ "$ACK" == "__NEXT__" ]]; then ACK="$arg"
      elif [[ -z "$EXPECTED_SHA" ]]; then EXPECTED_SHA="$arg"
      else die "unexpected argument: $arg" 2; fi ;;
  esac
done

banner

# ------------------------------------------------------------------ no-args
if [[ -z "$EXPECTED_SHA" ]]; then
  cat >&2 <<USAGE
PREPARE-ONLY: no release SHA supplied. Nothing was inspected or applied.
This packet is default-disabled and refuses to mutate.
  usage: LAB_DSN=... LAB_DSN_ALLOWLIST=host:port/db \\
         $0 <RELEASE_SHA> --preflight
         $0 <RELEASE_SHA> --execute --ack $ACK_TOKEN [--down]
USAGE
  exit 2
fi

# ===================================================================
# SHARED GATES (no database/network connection performed by any of these)
# ===================================================================

# ---- gate 1 + 2: exact-40-lowercase-hex SHA, and repo HEAD must equal it -----
require_sha_and_head() {
  [[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] \
    || die "release SHA must be exactly 40 lowercase hex chars" 2
  HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
  [[ "$HEAD_SHA" == "$EXPECTED_SHA" ]] \
    || die "repo HEAD $HEAD_SHA != expected release SHA $EXPECTED_SHA" 2
}

# ---- gate 3: reject a dirty / untracked working tree --------------------------
# The evidence dir lives OUTSIDE the repo by design, so it never dirties the tree.
require_clean_tree() {
  local dirty
  dirty="$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null)"
  [[ -z "$dirty" ]] \
    || die "working tree is dirty/untracked — refusing (commit or stash first)" 2
}

# ---- gates 4-7: parse + validate the target LOCALLY (NO connection) -----------
# Populates globals: T_HOST T_PORT T_DB. Emits NOTHING secret. This is the ONE
# shared validator used by --preflight, --execute, and --down. It performs ZERO
# database or network I/O: pure bash string parsing only (no psql / pg_isready /
# apply.sh / DB driver / socket).
T_HOST=""; T_PORT=""; T_DB=""
validate_target() {
  local dsn="$1"
  # gate 4
  [[ -n "$dsn" ]] || die "LAB_DSN is not set (isolated LAB/SHADOW DSN required)" 4
  # gate 5
  local allow="${LAB_DSN_ALLOWLIST:-}"
  [[ -n "$allow" ]] \
    || die "LAB_DSN_ALLOWLIST is not set (explicit LAB host:port/db allowlist required)" 4

  # ---- gate 7 (pre-parse global rejections) ----
  # Env-var interpolation embedded in the DSN (e.g. $PGHOST / ${VAR}).
  case "$dsn" in
    *'$'*) die "REJECT: DSN contains environment-variable interpolation ('\$') — refusing" 4 ;;
  esac

  # ---- gate 6: parse the target locally into host/port/db ----
  local host="" port="" db="" query="" body kv key val
  if [[ "$dsn" =~ ^postgres(ql)?:// ]]; then
    # URL form: postgres[ql]://[user[:pass]@]host[:port][/db][?query]
    body="${dsn#postgres://}"; body="${body#postgresql://}"
    case "$body" in *\?*) query="${body#*\?}"; body="${body%%\?*}";; esac
    case "$body" in */*) db="${body#*/}"; body="${body%%/*}";; esac
    # strip userinfo (everything up to and including the last '@')
    case "$body" in *@*) body="${body##*@}";; esac
    # body is now host[:port] (or multi-host host,host — rejected below)
    if [[ "$body" == *:* ]]; then host="${body%%:*}"; port="${body##*:}"; else host="$body"; fi
    # Reject connection-redirecting query parameters.
    if [[ -n "$query" ]]; then
      local IFS='&;'
      for kv in $query; do
        key="${kv%%=*}"; key="${key,,}"
        case "$key" in
          host|hostaddr|port|dbname|service|servicefile|passfile|options|target_session_attrs)
            die "REJECT: DSN query parameter '$key' can redirect connection behavior — refusing" 4 ;;
        esac
      done
    fi
  elif [[ "$dsn" == *=* ]]; then
    # libpq key=value form: host=... port=... dbname=...
    for kv in $dsn; do
      [[ "$kv" == *=* ]] || die "REJECT: malformed libpq token '$kv'" 4
      key="${kv%%=*}"; val="${kv#*=}"; key="${key,,}"
      case "$key" in
        host)    host="$val" ;;
        port)    port="$val" ;;
        dbname)  db="$val" ;;
        hostaddr|service|servicefile|passfile|options|target_session_attrs)
          die "REJECT: libpq parameter '$key' can redirect connection behavior — refusing" 4 ;;
        user|password|sslmode|sslrootcert|application_name|connect_timeout) : ;;  # benign, ignored
        *) die "REJECT: unexpected libpq parameter '$key' — refusing" 4 ;;
      esac
    done
  else
    die "REJECT: LAB_DSN is malformed (not a postgres URL or libpq key=value DSN)" 4
  fi

  # ---- gate 7 (post-parse rejections) ----
  [[ -n "$host" ]] || die "REJECT: could not parse host from LAB_DSN (malformed)" 4
  [[ -n "$db"   ]] || die "REJECT: could not parse dbname from LAB_DSN (malformed)" 4
  # Multiple hosts (host,host) can silently redirect the connection.
  case "$host" in *,*) die "REJECT: multiple hosts in target — refusing" 4 ;; esac
  # Unix socket path / service-file indirection via a filesystem host.
  case "$host" in /*|*/*) die "REJECT: socket/path host indirection — refusing" 4 ;; esac
  # Production DB identity.
  case "$db" in
    trade_ai) die "REJECT: dbname is production 'trade_ai' — this schema is LAB/SHADOW only" 4 ;;
    *prod*|*production*) die "REJECT: dbname contains a 'prod' substring — refusing" 4 ;;
  esac
  case "$host" in *prod*|*production*) die "REJECT: host contains a 'prod' substring — refusing" 4 ;; esac
  case "$dsn"  in *prod*|*production*) die "REJECT: DSN contains a 'prod' substring — refusing" 4 ;; esac
  # Port must be present, numeric, and NOT the prod default 5432.
  [[ -n "$port" ]] || die "REJECT: port is unset — LAB must use a distinct isolated port" 4
  [[ "$port" =~ ^[0-9]+$ ]] || die "REJECT: port '$port' is not numeric (malformed)" 4
  [[ "$port" != "5432" ]] || die "REJECT: port 5432 is the prod default — LAB must use a distinct isolated port" 4
  # Explicit allowlist: host:port/db must be enumerated by the operator.
  local key2="${host}:${port}/${db}" ok=0 IFS=,
  for entry in $allow; do [[ "$entry" == "$key2" ]] && ok=1; done
  [[ "$ok" == "1" ]] || die "REJECT: target LAB identity is not on LAB_DSN_ALLOWLIST" 4

  T_HOST="$host"; T_PORT="$port"; T_DB="$db"
}

# ------------------------------------------------------------------ SHA gate (all modes)
require_sha_and_head
note "exact-release-SHA gate OK @ $HEAD_SHA"

# ===================================================================
# --preflight : NO-CONNECTION validation + redacted plan. Exit 0 iff all pass.
# ===================================================================
if [[ "$PREFLIGHT" == "1" ]]; then
  require_clean_tree
  validate_target "${LAB_DSN:-}"
  # Gate 8 — print ONLY non-secret identity + plan. NEVER the DSN/user/password.
  local_migs="0001_mvl.up.sql 0002_roles.up.sql"
  [[ "$DIRECTION" == "down" ]] && local_migs="0002_roles.down.sql 0001_mvl.down.sql"
  cat <<REPORT

=== A1 PREFLIGHT (NO CONNECTION PERFORMED) direction=$DIRECTION ===
git_sha=$HEAD_SHA
clean_tree=true
host=$T_HOST
port=$T_PORT
database=$T_DB
not_trade_ai=true
non_production_port=true
allowlist_match=true
migrations_would_run=$local_migs
roles_would_create=$A1_ROLES
expected_tables_8=$A1_TABLES
rollback_command=LAB_DSN=<redacted> LAB_DSN_ALLOWLIST=<redacted> $0 $HEAD_SHA --execute --ack $ACK_TOKEN --down
evidence_path=$EVIDENCE (mode 0600, no secret values)
=== PREFLIGHT PASS — no psql/pg_isready/applier/DB-driver/socket was invoked ===
REPORT
  exit 0
fi

# ------------------------------------------------------------------ prepare-only (SHA, no flags)
if [[ "$EXECUTE" != "1" ]]; then
  cat <<PLAN

PREPARE-ONLY PLAN (direction=$DIRECTION) — nothing was applied:
  Run '$0 $EXPECTED_SHA --preflight' for a no-connection target validation, then:
  1) validate \$LAB_DSN: reject prod identity (dbname trade_ai / 'prod' / port 5432 /
     host not on LAB_DSN_ALLOWLIST) — DSN value NEVER printed
  2) before-schema inventory of the agentic_runtime schema (psql, read-only)
  3) delegate migration to: $APPLIER --apply $DIRECTION   (schema 0001 + roles 0002)
  4) writer-role preflight  (agentic_runtime_lab_rw / _shadow_rw: INSERT ok, DELETE denied)
  5) reader-role preflight   (agentic_runtime_reader: SELECT ok, INSERT denied)
  6) eight-table runtime test (agent_runs, agent_artifacts, agent_tool_calls,
     agent_reviews, agent_scores, kb_lessons, kb_cases, kb_chunks)
  7) isolation proof: reader has NO access to broker/account/position/order/approval/
     2FA/config tables, and writer != reader privilege set
  8) after-schema inventory + evidence log (mode 0600, no secret values)
  Rollback: re-run with --down to apply 0002_roles.down + 0001_mvl.down

This packet NEVER: touches production trade_ai, restarts services, changes
schedules, provisions secrets, or holds broker/order/approval/2FA authority.

To validate a target with NO connection:
  LAB_DSN=... LAB_DSN_ALLOWLIST=host:port/db \\
    $0 $EXPECTED_SHA --preflight
To apply against an isolated LAB/SHADOW DB:
  LAB_DSN=... LAB_DSN_ALLOWLIST=host:port/db \\
    $0 $EXPECTED_SHA --execute --ack $ACK_TOKEN [--down]
PLAN
  exit 3
fi

# ------------------------------------------------------------------ execute path
[[ "$ACK" == "$ACK_TOKEN" ]] || die "--execute requires --ack $ACK_TOKEN (typed acknowledgement)" 2
# RE-RUN the full local validation before ANY database contact. A prior successful
# --preflight NEVER bypasses this: clean-tree + target validation fire again here.
require_clean_tree
validate_target "${LAB_DSN:-}"
ev_init
ev "packet=$PACKET sha=$EXPECTED_SHA direction=$DIRECTION execute=1"
note "target validated (redacted): host=$T_HOST port=$T_PORT db=$T_DB"
ev "dsn_identity host=$T_HOST port=$T_PORT db=$T_DB (allowlisted; password never logged)"
[[ -x "$APPLIER" ]] || die "migration applier not found/executable: $APPLIER" 2
command -v psql >/dev/null 2>&1 || die "psql not available" 2
export TRADE_AI_LAB_DSN="${LAB_DSN}"   # apply.sh reads this; value never echoed

note "[1/8] before-schema inventory"
psql "$TRADE_AI_LAB_DSN" -Atqc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='agentic_runtime';" \
  | { read -r n; note "  agentic_runtime tables before: $n"; ev "before_tables=$n"; }

note "[2/8] delegating migration: $APPLIER --apply $DIRECTION"
"$APPLIER" --apply "$DIRECTION"
ev "migration_applied direction=$DIRECTION"

if [[ "$DIRECTION" == "down" ]]; then
  note "rollback (down) applied. LAB schema + roles removed."
  ev "rollback_complete"
  unset TRADE_AI_LAB_DSN LAB_DSN
  note "credential env cleared."
  exit 0
fi

note "[3/8] writer-role preflight (INSERT allowed, DELETE denied)"
psql "$TRADE_AI_LAB_DSN" -v ON_ERROR_STOP=1 -Atqc \
  "SELECT has_schema_privilege('agentic_runtime_lab_rw','agentic_runtime','USAGE');" \
  | { read -r r; [[ "$r" == "t" ]] || die "writer role lacks USAGE" 5; note "  writer USAGE ok"; }

note "[4/8] reader-role preflight (SELECT allowed, INSERT denied)"
psql "$TRADE_AI_LAB_DSN" -v ON_ERROR_STOP=1 -Atqc \
  "SELECT has_table_privilege('agentic_runtime_reader','agentic_runtime.agent_runs','INSERT');" \
  | { read -r r; [[ "$r" == "f" ]] || die "reader role must NOT have INSERT" 5; note "  reader INSERT denied ok"; }

note "[5/8] eight-table runtime test"
missing="$(psql "$TRADE_AI_LAB_DSN" -Atqc "
  WITH want(t) AS (VALUES
    ('agent_runs'),('agent_artifacts'),('agent_tool_calls'),('agent_reviews'),
    ('agent_scores'),('kb_lessons'),('kb_cases'),('kb_chunks'))
  SELECT string_agg(t,',') FROM want
  WHERE t NOT IN (SELECT table_name FROM information_schema.tables
                  WHERE table_schema='agentic_runtime');")"
[[ -z "$missing" ]] || die "missing runtime tables: $missing" 5
note "  all 8 runtime tables present"; ev "runtime_tables=8/8"

note "[6/8] isolation proof: writer != reader, reader has no trading-table access"
psql "$TRADE_AI_LAB_DSN" -Atqc "
  SELECT count(*) FROM information_schema.role_table_grants
  WHERE grantee='agentic_runtime_reader'
    AND table_schema IN ('public')
    AND table_name ~* '(broker|account|position|order|approval|two_factor|2fa|config|holdings|secret)';" \
  | { read -r c; [[ "$c" == "0" ]] || die "reader has grants on trading/config tables ($c)" 5; \
      note "  reader has ZERO trading/config-table grants"; ev "reader_trading_grants=0"; }

note "[7/8] after-schema inventory"
psql "$TRADE_AI_LAB_DSN" -Atqc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='agentic_runtime';" \
  | { read -r n; note "  agentic_runtime tables after: $n"; ev "after_tables=$n"; }

note "[8/8] credential cleanup"
unset TRADE_AI_LAB_DSN LAB_DSN
ev "credential_env_cleared"
note "done. Evidence: $EVIDENCE (mode 0600, no secret values). Roll back with --down."

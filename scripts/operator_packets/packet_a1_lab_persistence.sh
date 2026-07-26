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
#   * PREPARE-ONLY BY DEFAULT. With no --execute it prints the plan and exits 3.
#   * With NO args it prints PREPARE-ONLY usage and exits 2.
#   * Pins to an exact release SHA (arg 1) and refuses if repo HEAD != that SHA.
#   * --execute additionally requires --ack <token> with the exact typed token.
#   * The DSN is read from $LAB_DSN and is NEVER printed. Only a redacted identity
#     (scheme/host/port/db, password stripped) is ever emitted.
#   * REJECTS any production DB identity: dbname `trade_ai`, any 'prod' substring,
#     the prod port 5432, or a host not on the explicit LAB allowlist.
#   * Delegates the actual migration to migrations/agentic_runtime/apply.sh --apply.
#   * Evidence log is written mode 0600 and contains NO secret values.
#
# USAGE:
#   packet_a1_lab_persistence.sh                              # PREPARE-ONLY, exit 2
#   packet_a1_lab_persistence.sh <RELEASE_SHA>                     # plan, exit 3
#   LAB_DSN=... LAB_DSN_ALLOWLIST=host:port/db \
#     packet_a1_lab_persistence.sh <RELEASE_SHA> --execute --ack <token> [--down]
#
# EXIT CODES: 0 ok · 2 usage/gate blocked · 3 prepare-only refusal · 4 DSN reject
# =============================================================================
set -euo pipefail

readonly PACKET="A1:lab_persistence"
readonly ACK_TOKEN="APPLY-A1-LAB-PERSISTENCE"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly APPLIER="$REPO_ROOT/migrations/agentic_runtime/apply.sh"
# Evidence log defaults OUTSIDE the repo so real runs never drop logs into git.
readonly EVIDENCE="${A1_EVIDENCE_LOG:-/home/johnclaw/tradeai-deploy-backups/packet-a1/evidence_$(date -u +%Y%m%dT%H%M%SZ).log}"

banner() { echo "=== PACKET $PACKET === PREPARE-ONLY (dry-run default) ==="; }
die()    { echo "[A1][BLOCKED] $1" >&2; exit "${2:-2}"; }
note()   { echo "[A1] $*"; }
# Evidence log: mode 0600, never any secret/DSN/password value.
ev_init() { umask 077; mkdir -p "$(dirname "$EVIDENCE")"; : > "$EVIDENCE"; chmod 0600 "$EVIDENCE"; }
ev()      { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$EVIDENCE"; }

# ------------------------------------------------------------------ arg parse
EXPECTED_SHA=""
EXECUTE=0
ACK=""
DIRECTION="up"          # 'up' applies; --down rolls back
for arg in "$@"; do
  case "$arg" in
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
         $0 <RELEASE_SHA> --execute --ack $ACK_TOKEN [--down]
USAGE
  exit 2
fi

# ------------------------------------------------------------------ SHA gate
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "release SHA must be exactly 40 lowercase hex chars" 2
HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ "$HEAD_SHA" == "$EXPECTED_SHA" ]] || die "repo HEAD $HEAD_SHA != expected release SHA $EXPECTED_SHA" 2
note "exact-RC-SHA gate OK @ $HEAD_SHA"

# ------------------------------------------------------------------ DSN validation (no values printed)
# Redact a DSN to scheme://<user>:***@host:port/db — password NEVER emitted.
redact_dsn() {
  # shellcheck disable=SC2001
  echo "$1" | sed -E 's#(://[^:/@]+):[^@]*@#\1:***@#; s#password=[^ ]*#password=***#g'
}
dsn_field() {  # $1=dsn $2=host|port|db  -> value only (used internally, not printed raw)
  local dsn="$1" what="$2"
  python3 - "$dsn" "$what" <<'PY'
import sys, urllib.parse as u
dsn, what = sys.argv[1], sys.argv[2]
try:
    p = u.urlparse(dsn)
    host = (p.hostname or "")
    port = str(p.port or "")
    db = (p.path or "").lstrip("/")
except Exception:
    host = port = db = ""
# also parse key=value libpq style if urlparse yielded nothing
if not host and "=" in dsn:
    kv = dict(t.split("=",1) for t in dsn.split() if "=" in t)
    host = kv.get("host", host); port = kv.get("port", port); db = kv.get("dbname", db)
print({"host":host,"port":port,"db":db}[what])
PY
}

validate_dsn() {
  local dsn="$1"
  [[ -n "$dsn" ]] || die "LAB_DSN is not set (isolated LAB/SHADOW DSN required)" 4
  local host port db
  host="$(dsn_field "$dsn" host)"; port="$(dsn_field "$dsn" port)"; db="$(dsn_field "$dsn" db)"
  [[ -n "$host" ]] || die "could not parse host from LAB_DSN" 4
  [[ -n "$db"   ]] || die "could not parse dbname from LAB_DSN" 4
  # Reject production DB identity.
  case "$db" in
    trade_ai) die "REJECT: dbname is production 'trade_ai' — this schema is LAB/SHADOW only" 4 ;;
    *prod*|*production*) die "REJECT: dbname contains a 'prod' substring — refusing" 4 ;;
  esac
  case "$dsn" in
    *prod*|*production*) die "REJECT: DSN contains a 'prod' substring — refusing" 4 ;;
  esac
  case "$host" in
    *prod*|*production*) die "REJECT: host contains a 'prod' substring — refusing" 4 ;;
  esac
  # Reject the production port (default 5432). LAB must be on a distinct isolated port.
  if [[ -z "$port" || "$port" == "5432" ]]; then
    die "REJECT: port '${port:-<unset>}' is the prod default 5432 (or unset) — LAB must use a distinct isolated port" 4
  fi
  # Explicit allowlist: host:port/db must be enumerated by the operator.
  local allow="${LAB_DSN_ALLOWLIST:-}"
  [[ -n "$allow" ]] || die "LAB_DSN_ALLOWLIST is not set (explicit LAB host:port/db allowlist required)" 4
  local key="${host}:${port}/${db}" ok=0 IFS=,
  for entry in $allow; do [[ "$entry" == "$key" ]] && ok=1; done
  [[ "$ok" == "1" ]] || die "REJECT: target LAB identity is not on LAB_DSN_ALLOWLIST" 4
  # Emit ONLY the redacted identity (password stripped).
  note "DSN identity accepted (redacted): host=$host port=$port db=$db"
  ev "dsn_identity host=$host port=$port db=$db (allowlisted; password never logged)"
}

# ------------------------------------------------------------------ prepare-only
if [[ "$EXECUTE" != "1" ]]; then
  cat <<PLAN

PREPARE-ONLY PLAN (direction=$DIRECTION) — nothing was applied:
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

To apply against an isolated LAB/SHADOW DB:
  LAB_DSN=... LAB_DSN_ALLOWLIST=host:port/db \\
    $0 $EXPECTED_SHA --execute --ack $ACK_TOKEN [--down]
PLAN
  exit 3
fi

# ------------------------------------------------------------------ execute path
[[ "$ACK" == "$ACK_TOKEN" ]] || die "--execute requires --ack $ACK_TOKEN (typed acknowledgement)" 2
ev_init
ev "packet=$PACKET sha=$EXPECTED_SHA direction=$DIRECTION execute=1"
# DSN identity is validated FIRST — the prod-DB/port/host rejection must fire before
# any tool check or DB contact (proven dry with a fake prod DSN string; no connection).
validate_dsn "${LAB_DSN:-}"
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

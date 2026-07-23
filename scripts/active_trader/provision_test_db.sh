#!/usr/bin/env bash
# Active Trader Stage 1 — provision the ISOLATED test database (run 20260722-01).
#
# Creates a completely separate, user-owned PostgreSQL 17 cluster (NOT the
# production cluster on :5432), with:
#   cluster:  ~/tradeai-lab/pg17  (port 5433, owner: current OS user)
#   database: trade_ai_test
#   role:     trade_ai_lab  (LOGIN only; no CREATEDB/CREATEROLE/SUPERUSER)
#
# The trade_ai_lab role exists ONLY in the lab cluster, so it provably cannot
# write to (or even authenticate against) the production trade_ai database.
#
# The role password is generated locally and stored ONLY in Bitwarden Secrets
# Manager project 'trade-ai-lab' as ACTIVE_TRADER_TEST_DATABASE_DSN.
# Nothing secret is printed, committed, uploaded, or emailed.
#
# Idempotent: safe to re-run; existing cluster/db/role are kept (password is
# rotated and the Bitwarden secret updated only with --rotate).
set -euo pipefail

PGBIN=/usr/lib/postgresql/17/bin
LAB_HOME="${TRADEAI_LAB_HOME:-$HOME/tradeai-lab}"
DATA_DIR="$LAB_HOME/pg17"
SOCK_DIR="$LAB_HOME/sock"
LOG_FILE="$LAB_HOME/pg17.log"
PORT="${TRADEAI_LAB_PG_PORT:-5433}"
DB=trade_ai_test
ROLE=trade_ai_lab
SECRET_NAME=ACTIVE_TRADER_TEST_DATABASE_DSN
LAB_PROJECT_ID=1b0a478d-87a3-4e2d-85f6-b4900015afa0   # trade-ai-lab

umask 077
mkdir -p "$LAB_HOME" "$SOCK_DIR"

if [ ! -f "$DATA_DIR/PG_VERSION" ]; then
  "$PGBIN/initdb" -D "$DATA_DIR" --auth-local=peer --auth-host=scram-sha-256 -E UTF8 >/dev/null
  {
    echo "port = $PORT"
    echo "listen_addresses = '127.0.0.1'"
    echo "unix_socket_directories = '$SOCK_DIR'"
    echo "max_connections = 40"
    echo "shared_buffers = 128MB"
  } >> "$DATA_DIR/postgresql.conf"
fi

if ! "$PGBIN/pg_ctl" -D "$DATA_DIR" status >/dev/null 2>&1; then
  "$PGBIN/pg_ctl" -D "$DATA_DIR" -l "$LOG_FILE" -w start >/dev/null
fi

psql_lab() { "$PGBIN/psql" -h "$SOCK_DIR" -p "$PORT" -d postgres -Atq "$@"; }

# Role (LOGIN only, least privilege) + database owned by it.
PW="$(openssl rand -base64 30 | tr -d '/+=' | head -c 32)"
if [ "$(psql_lab -c "SELECT 1 FROM pg_roles WHERE rolname='$ROLE'")" != "1" ]; then
  psql_lab -c "CREATE ROLE $ROLE LOGIN PASSWORD '$PW' NOSUPERUSER NOCREATEDB NOCREATEROLE" >/dev/null
  STORE_SECRET=1
elif [ "${1:-}" = "--rotate" ]; then
  psql_lab -c "ALTER ROLE $ROLE PASSWORD '$PW'" >/dev/null
  STORE_SECRET=1
else
  STORE_SECRET=0
fi
if [ "$(psql_lab -c "SELECT 1 FROM pg_database WHERE datname='$DB'")" != "1" ]; then
  psql_lab -c "CREATE DATABASE $DB OWNER $ROLE" >/dev/null
fi
# Defense in depth: lab role may connect only to its own database.
psql_lab -c "REVOKE CONNECT ON DATABASE postgres FROM PUBLIC" >/dev/null || true

# Store/refresh DSN in Bitwarden lab project (write token; value never printed).
if [ "$STORE_SECRET" = "1" ]; then
  DSN="postgresql://$ROLE:$PW@127.0.0.1:$PORT/$DB"
  export BWS_ACCESS_TOKEN="$(cat "$HOME/.openclaw/credentials/bws_write_token")"
  EXISTING_ID="$(bws secret list "$LAB_PROJECT_ID" 2>/dev/null | python3 -c '
import sys, json
name = "'"$SECRET_NAME"'"
try:
    for s in json.load(sys.stdin):
        if s.get("key") == name:
            print(s["id"]); break
except Exception:
    pass')"
  if [ -n "$EXISTING_ID" ]; then
    bws secret edit --key "$SECRET_NAME" --value "$DSN" --project-id "$LAB_PROJECT_ID" "$EXISTING_ID" -o none
  else
    bws secret create "$SECRET_NAME" "$DSN" "$LAB_PROJECT_ID" -o none
  fi
  unset BWS_ACCESS_TOKEN DSN
fi
unset PW

echo "lab cluster: $DATA_DIR (port $PORT) — db=$DB role=$ROLE"
echo "DSN stored in Bitwarden project trade-ai-lab as $SECRET_NAME (value not displayed)"

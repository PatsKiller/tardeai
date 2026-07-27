#!/usr/bin/env bash
# Active Trader Stage 4 — provision the READ-ONLY lab role for the read API.
#
# Creates role trade_ai_lab_ro in the user-owned LAB cluster (:5433) with:
#   * LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE
#   * CONNECT on trade_ai_test; USAGE on public; SELECT-only on all tables
#   * default_transaction_read_only = on   (writes refused at the session level)
#   * statement_timeout = 5s               (bounded queries)
# The fixture loader keeps using the WRITE identity (trade_ai_lab); the API
# runtime uses ONLY this read-only identity.
#
# DSN stored ONLY in Bitwarden project trade-ai-lab as ACTIVE_TRADER_READ_API_DSN
# via the LAB machine-account token. Nothing secret is printed or committed.
set -euo pipefail

PGBIN=/usr/lib/postgresql/17/bin
LAB_HOME="${TRADEAI_LAB_HOME:-$HOME/tradeai-lab}"
SOCK_DIR="$LAB_HOME/sock"
PORT="${TRADEAI_LAB_PG_PORT:-5433}"
DB=trade_ai_test
ROLE=trade_ai_lab_ro
SECRET_NAME=ACTIVE_TRADER_READ_API_DSN
LAB_PROJECT_ID=1b0a478d-87a3-4e2d-85f6-b4900015afa0

umask 077
psql_admin() { "$PGBIN/psql" -h "$SOCK_DIR" -p "$PORT" -d "$1" -Atq -c "$2"; }

PW="$(openssl rand -base64 30 | tr -d '/+=' | head -c 32)"
if [ "$(psql_admin postgres "SELECT 1 FROM pg_roles WHERE rolname='$ROLE'")" != "1" ]; then
  psql_admin postgres "CREATE ROLE $ROLE LOGIN PASSWORD '$PW' NOSUPERUSER NOCREATEDB NOCREATEROLE"
  STORE=1
elif [ "${1:-}" = "--rotate" ]; then
  psql_admin postgres "ALTER ROLE $ROLE PASSWORD '$PW'"
  STORE=1
else
  STORE=0
fi
psql_admin postgres "ALTER ROLE $ROLE SET default_transaction_read_only = on"
psql_admin postgres "ALTER ROLE $ROLE SET statement_timeout = '5s'"
psql_admin "$DB" "GRANT CONNECT ON DATABASE $DB TO $ROLE"
psql_admin "$DB" "GRANT USAGE ON SCHEMA public TO $ROLE"
psql_admin "$DB" "GRANT SELECT ON ALL TABLES IN SCHEMA public TO $ROLE"
psql_admin "$DB" "ALTER DEFAULT PRIVILEGES FOR ROLE trade_ai_lab IN SCHEMA public GRANT SELECT ON TABLES TO $ROLE"

if [ "$STORE" = "1" ]; then
  DSN="postgresql://$ROLE:$PW@127.0.0.1:$PORT/$DB?application_name=at-read-api"
  export BWS_ACCESS_TOKEN="$(cat "$HOME/.openclaw/credentials/bws_lab_token")"
  EXISTING_ID="$(bws secret list "$LAB_PROJECT_ID" 2>/dev/null | python3 -c '
import sys, json
try:
    for s in json.load(sys.stdin):
        if s.get("key") == "'"$SECRET_NAME"'": print(s["id"]); break
except Exception: pass')"
  if [ -n "$EXISTING_ID" ]; then
    bws secret edit --key "$SECRET_NAME" --value "$DSN" --project-id "$LAB_PROJECT_ID" "$EXISTING_ID" -o none
  else
    bws secret create "$SECRET_NAME" "$DSN" "$LAB_PROJECT_ID" -o none
  fi
  unset BWS_ACCESS_TOKEN DSN
fi
unset PW
echo "read-only role $ROLE ready on :$PORT/$DB — DSN in Bitwarden trade-ai-lab as $SECRET_NAME (not displayed)"

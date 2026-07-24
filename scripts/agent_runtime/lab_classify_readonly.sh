#!/usr/bin/env bash
# Read-only metadata classifier for the isolated agentic PostgreSQL LAB cluster.
#
# This script never reads table rows and contains no database mutation statement.
# It uses the LAB cluster's peer-authenticated Unix socket only for administrative
# metadata discovery. Runtime identities must later prove SCRAM access through
# explicit 127.0.0.1:5433 connections.
set -euo pipefail

readonly PSQL=/usr/bin/psql
readonly LAB_SOCKET=/home/johnclaw/tradeai-lab/sock
readonly LAB_PORT=5433
readonly EXPECTED_DATA_DIR=/home/johnclaw/tradeai-lab/pg17
readonly PROPOSED_DATABASE=trade_ai_agentic_lab

if [[ ! -x "$PSQL" ]]; then
  echo "BLOCKED_LAB_CLASSIFICATION: /usr/bin/psql is unavailable" >&2
  exit 2
fi
if [[ ! -S "$LAB_SOCKET/.s.PGSQL.$LAB_PORT" ]]; then
  echo "BLOCKED_LAB_CLASSIFICATION: expected LAB socket is unavailable" >&2
  exit 2
fi

PSQL_ARGS=(
  -w -X -v ON_ERROR_STOP=1
  -h "$LAB_SOCKET"
  -p "$LAB_PORT"
  -AtF '|'
)

identity="$($PSQL "${PSQL_ARGS[@]}" -d postgres -c \
  "select current_user,
          current_database(),
          current_setting('data_directory'),
          current_setting('port'),
          current_setting('listen_addresses'),
          current_setting('unix_socket_directories'),
          r.rolsuper,
          r.rolcreatedb,
          r.rolcreaterole
     from pg_roles r
    where r.rolname = current_user;")"

IFS='|' read -r current_user current_db data_dir configured_port listen_addresses socket_dirs is_super can_createdb can_createrole <<<"$identity"

if [[ "$data_dir" != "$EXPECTED_DATA_DIR" || "$configured_port" != "$LAB_PORT" ]]; then
  echo "REFUSED_NON_LAB_TARGET: unexpected data directory or port" >&2
  exit 3
fi
if [[ "$current_db" != "postgres" ]]; then
  echo "REFUSED_NON_ADMIN_METADATA_SESSION: expected postgres database" >&2
  exit 3
fi

printf '=== LAB SERVER IDENTITY ===\n'
printf 'current_user|%s\n' "$current_user"
printf 'current_database|%s\n' "$current_db"
printf 'data_directory|%s\n' "$data_dir"
printf 'configured_port|%s\n' "$configured_port"
printf 'listen_addresses|%s\n' "$listen_addresses"
printf 'unix_socket_directories|%s\n' "$socket_dirs"
printf 'superuser|%s\ncreatedb|%s\ncreaterole|%s\n' "$is_super" "$can_createdb" "$can_createrole"

printf '\n=== LAB DATABASE INVENTORY ===\n'
$PSQL "${PSQL_ARGS[@]}" -d postgres -c \
  "select datname,
          pg_get_userbyid(datdba) as owner,
          pg_database_size(datname) as bytes,
          datallowconn
     from pg_database
    where not datistemplate
    order by datname;"

mapfile -t databases < <($PSQL "${PSQL_ARGS[@]}" -d postgres -Atc \
  "select datname
     from pg_database
    where datallowconn
      and not datistemplate
    order by datname;")

for database in "${databases[@]}"; do
  printf '\n=== DATABASE METADATA: %s ===\n' "$database"
  $PSQL "${PSQL_ARGS[@]}" -d "$database" -c \
    "select n.nspname as schema_name,
            count(c.oid) filter (where c.relkind in ('r','p')) as table_count,
            count(c.oid) filter (where c.relkind in ('v','m')) as view_count,
            count(c.oid) filter (where c.relkind = 'S') as sequence_count,
            count(c.oid) filter (where c.relkind in ('r','p','v','m','S')) as relation_count
       from pg_namespace n
       left join pg_class c on c.relnamespace = n.oid
      where n.nspname not in ('pg_catalog','information_schema')
        and n.nspname not like 'pg_toast%'
      group by n.nspname
      order by n.nspname;"

  $PSQL "${PSQL_ARGS[@]}" -d "$database" -c \
    "select case when exists (
              select 1 from pg_namespace where nspname = 'agentic_runtime'
            ) then 'agentic_runtime_present'
              else 'agentic_runtime_absent'
            end,
            (select count(*)
               from pg_class c
               join pg_namespace n on n.oid = c.relnamespace
              where n.nspname not in ('pg_catalog','information_schema')
                and n.nspname not like 'pg_toast%'
                and c.relkind in ('r','p','v','m','S')) as user_relation_count;"
done

printf '\n=== ROLE AUTHORITY SUMMARY ===\n'
$PSQL "${PSQL_ARGS[@]}" -d postgres -c \
  "select rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole
     from pg_roles
    where rolname in (
      current_user,
      'trade_ai_lab',
      'trade_ai_lab_ro',
      'agentic_lab_migrator',
      'trade_ai_shadow_ro',
      'agentic_runtime_lab_rw'
    )
    order by rolname;"

printf '\n=== FAIL-CLOSED TARGET DECISION ===\n'
printf 'existing_database_reuse|NOT_AUTHORIZED_BY_THIS_SCRIPT\n'
printf 'proposed_new_empty_database|%s\n' "$PROPOSED_DATABASE"
printf 'production_port|5432_FORBIDDEN\n'
printf 'runtime_tcp_target|127.0.0.1:5433_AFTER_ROLE_PROVISIONING_ONLY\n'
printf 'classification_mode|READ_ONLY_METADATA_NO_ROW_CONTENTS\n'
printf 'status|CLASSIFICATION_OUTPUT_READY_FOR_OPERATOR_REVIEW\n'

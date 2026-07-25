#!/usr/bin/env bash
# Provision and prove the isolated agentic_runtime PostgreSQL LAB, stages 1 through 8.
#
# This operator-run script is intentionally pinned to the user-owned PostgreSQL 17
# cluster already classified at /home/johnclaw/tradeai-lab/pg17 on port 5433.
# It never connects to port 5432, never reuses trade_ai_test, never reads application
# rows, and never activates a service, model, agent, broker, order or configuration.
set -euo pipefail
umask 077

readonly PSQL=/usr/bin/psql
readonly PYTHON=/usr/bin/python3
readonly LAB_SOCKET=/home/johnclaw/tradeai-lab/sock
readonly LAB_PORT=5433
readonly LAB_HOST=127.0.0.1
readonly EXPECTED_DATA_DIR=/home/johnclaw/tradeai-lab/pg17
readonly LAB_DATABASE=trade_ai_agentic_lab
readonly MIGRATOR_ROLE=agentic_lab_migrator
readonly READER_ROLE=trade_ai_shadow_ro
readonly WRITER_ROLE=agentic_runtime_lab_rw
readonly REQUIRED_ACK=DISPOSABLE_LAB_NO_PRODUCTION_DATA
readonly SECRET_DIR=/home/johnclaw/tradeai-lab/secrets/agentic-runtime
readonly EVIDENCE_DIR=/home/johnclaw/tradeai-lab/evidence
readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly PROTECTED_SCHEMAS=(trade broker account position approval configuration lab_protected)

if [[ "${LAB_ACK:-}" != "$REQUIRED_ACK" ]]; then
  echo "BLOCKED_LAB_PROVISIONING: set LAB_ACK=$REQUIRED_ACK" >&2
  exit 2
fi
if [[ ! -x "$PSQL" || ! -x "$PYTHON" ]]; then
  echo "BLOCKED_LAB_PROVISIONING: required system executable unavailable" >&2
  exit 2
fi
if [[ ! -S "$LAB_SOCKET/.s.PGSQL.$LAB_PORT" ]]; then
  echo "BLOCKED_LAB_PROVISIONING: verified LAB socket unavailable" >&2
  exit 2
fi

unalias psql 2>/dev/null || true
unset PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD PGSERVICE PGSERVICEFILE

readonly REPO="${REPO:-$REPO_DEFAULT}"
readonly UP_SQL="$REPO/migrations/agentic_runtime/0001_mvl.up.sql"
readonly DOWN_SQL="$REPO/migrations/agentic_runtime/0001_mvl.down.sql"
if [[ ! -f "$UP_SQL" || ! -f "$DOWN_SQL" ]]; then
  echo "BLOCKED_LAB_PROVISIONING: migration files unavailable in REPO=$REPO" >&2
  exit 2
fi

mkdir -p "$SECRET_DIR" "$EVIDENCE_DIR"
chmod 700 "$SECRET_DIR" "$EVIDENCE_DIR"
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly EVIDENCE_FILE="$EVIDENCE_DIR/agentic-runtime-db-proof-$STAMP.txt"
readonly ROLLBACK_FILE="$EVIDENCE_DIR/agentic-runtime-rollback-$STAMP.sql"
readonly READER_PGPASS="$SECRET_DIR/trade-ai-shadow-ro-$STAMP.pgpass"
readonly WRITER_PGPASS="$SECRET_DIR/agentic-runtime-lab-rw-$STAMP.pgpass"
readonly BEFORE_MANIFEST="$(mktemp /tmp/agentic-runtime-before.XXXXXX)"
readonly AFTER_MANIFEST="$(mktemp /tmp/agentic-runtime-after.XXXXXX)"

cleanup_temp() {
  rm -f "$BEFORE_MANIFEST" "$AFTER_MANIFEST"
}
trap cleanup_temp EXIT

cat >"$ROLLBACK_FILE" <<SQL
-- Explicit LAB-only rollback. Review before running. This file is not executed automatically.
SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
 WHERE datname = '$LAB_DATABASE'
   AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS $LAB_DATABASE;
DROP ROLE IF EXISTS $WRITER_ROLE;
DROP ROLE IF EXISTS $READER_ROLE;
DROP ROLE IF EXISTS $MIGRATOR_ROLE;
SQL
chmod 600 "$ROLLBACK_FILE"

# Create and lock the evidence file BEFORE redirecting, so the mode-0600 chmod cannot
# race the asynchronous tee in the process substitution (which created the file lazily
# and intermittently failed the chmod under set -e).
: > "$EVIDENCE_FILE"
chmod 600 "$EVIDENCE_FILE"
exec > >(tee -a "$EVIDENCE_FILE") 2>&1

on_error() {
  local rc=$?
  echo "BLOCKED_DB_PROOF: command failed; no automatic rollback was attempted"
  echo "rollback_location|$ROLLBACK_FILE"
  echo "exit_code|$rc"
  exit "$rc"
}
trap on_error ERR

ADMIN_ARGS=(-w -X -v ON_ERROR_STOP=1 -h "$LAB_SOCKET" -p "$LAB_PORT")
TCP_BASE=(-w -X -v ON_ERROR_STOP=1 -h "$LAB_HOST" -p "$LAB_PORT" -d "$LAB_DATABASE")

identity="$($PSQL "${ADMIN_ARGS[@]}" -d postgres -AtF '|' -c \
  "select current_user,
          current_database(),
          current_setting('data_directory'),
          current_setting('port'),
          current_setting('listen_addresses'),
          r.rolsuper,
          r.rolcreatedb,
          r.rolcreaterole
     from pg_roles r
    where r.rolname = current_user;")"
IFS='|' read -r admin_user admin_db data_dir configured_port listen_addresses is_super can_createdb can_createrole <<<"$identity"

if [[ "$admin_db" != postgres || "$data_dir" != "$EXPECTED_DATA_DIR" || "$configured_port" != "$LAB_PORT" ]]; then
  echo "REFUSED_NON_LAB_TARGET: unexpected database, data directory or port" >&2
  exit 3
fi
if [[ "$listen_addresses" != "$LAB_HOST" || "$is_super" != t || "$can_createdb" != t || "$can_createrole" != t ]]; then
  echo "BLOCKED_LAB_PROVISIONING: LAB administrator authority or listener identity is incomplete" >&2
  exit 3
fi

printf '=== GATE ===\n'
printf 'status|PASS_LAB_CANDIDATE\n'
printf 'admin_role|%s\n' "$admin_user"
printf 'data_directory|%s\n' "$data_dir"
printf 'port|%s\n' "$configured_port"
printf 'target_database|%s\n' "$LAB_DATABASE"
printf 'existing_database_reuse|DENIED\n'
printf 'secret_delivery|HOST_LOCAL_MODE_0600\n'
printf 'rollback_location|%s\n' "$ROLLBACK_FILE"
printf 'up_migration_sha256|'; sha256sum "$UP_SQL" | awk '{print $1}'
printf 'down_migration_sha256|'; sha256sum "$DOWN_SQL" | awk '{print $1}'

existing_db="$($PSQL "${ADMIN_ARGS[@]}" -d postgres -Atc \
  "select count(*) from pg_database where datname = '$LAB_DATABASE';")"
existing_roles="$($PSQL "${ADMIN_ARGS[@]}" -d postgres -Atc \
  "select count(*) from pg_roles where rolname in ('$MIGRATOR_ROLE','$READER_ROLE','$WRITER_ROLE');")"
if [[ "$existing_db" != 0 || "$existing_roles" != 0 ]]; then
  echo "BLOCKED_LAB_PARTIAL_STATE: target database or roles already exist; inspect before retry" >&2
  exit 4
fi

reader_password="$($PYTHON - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
writer_password="$($PYTHON - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"

printf '%s:%s:%s:%s:%s\n' "$LAB_HOST" "$LAB_PORT" "$LAB_DATABASE" "$READER_ROLE" "$reader_password" >"$READER_PGPASS"
printf '%s:%s:%s:%s:%s\n' "$LAB_HOST" "$LAB_PORT" "$LAB_DATABASE" "$WRITER_ROLE" "$writer_password" >"$WRITER_PGPASS"
chmod 600 "$READER_PGPASS" "$WRITER_PGPASS"

printf '\n=== STAGE 1-3: EMPTY DATABASE AND SEPARATED IDENTITIES ===\n'
$PSQL "${ADMIN_ARGS[@]}" -d postgres <<SQL
CREATE ROLE $MIGRATOR_ROLE
  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
CREATE ROLE $READER_ROLE
  LOGIN PASSWORD '$reader_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
CREATE ROLE $WRITER_ROLE
  LOGIN PASSWORD '$writer_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
SQL

$PSQL "${ADMIN_ARGS[@]}" -d postgres -c \
  "CREATE DATABASE $LAB_DATABASE OWNER $MIGRATOR_ROLE TEMPLATE template0;"

$PSQL "${ADMIN_ARGS[@]}" -d postgres <<SQL
REVOKE ALL ON DATABASE $LAB_DATABASE FROM PUBLIC;
GRANT CONNECT ON DATABASE $LAB_DATABASE TO $READER_ROLE, $WRITER_ROLE;
SQL

$PSQL "${ADMIN_ARGS[@]}" -d "$LAB_DATABASE" <<SQL
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO $MIGRATOR_ROLE;

CREATE SCHEMA approved_canonical AUTHORIZATION $MIGRATOR_ROLE;
SET ROLE $MIGRATOR_ROLE;
CREATE VIEW approved_canonical.v_agentic_market_snapshot AS
SELECT 'SYNTHETIC_LAB'::text AS environment,
       CURRENT_DATE AS as_of,
       1::integer AS synthetic_observation_count;
RESET ROLE;
REVOKE ALL ON SCHEMA approved_canonical FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA approved_canonical FROM PUBLIC;
GRANT USAGE ON SCHEMA approved_canonical TO $READER_ROLE;
GRANT SELECT ON approved_canonical.v_agentic_market_snapshot TO $READER_ROLE;
SQL

for schema in "${PROTECTED_SCHEMAS[@]}"; do
  $PSQL "${ADMIN_ARGS[@]}" -d "$LAB_DATABASE" <<SQL
CREATE SCHEMA $schema AUTHORIZATION $MIGRATOR_ROLE;
SET ROLE $MIGRATOR_ROLE;
CREATE TABLE $schema.denial_target (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  note text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
RESET ROLE;
REVOKE ALL ON SCHEMA $schema FROM PUBLIC, $READER_ROLE, $WRITER_ROLE;
REVOKE ALL ON ALL TABLES IN SCHEMA $schema FROM PUBLIC, $READER_ROLE, $WRITER_ROLE;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA $schema FROM PUBLIC, $READER_ROLE, $WRITER_ROLE;
SQL
done

echo "database_created|$LAB_DATABASE"
echo "migration_executor|$MIGRATOR_ROLE|NOLOGIN"
echo "shadow_reader|$READER_ROLE|LOGIN"
echo "runtime_writer|$WRITER_ROLE|LOGIN"
echo "synthetic_view|approved_canonical.v_agentic_market_snapshot"
echo "synthetic_denial_schemas|${PROTECTED_SCHEMAS[*]}"

apply_migration_as_migrator() {
  local file="$1"
  {
    printf 'SET ROLE %s;\n' "$MIGRATOR_ROLE"
    cat "$file"
    printf '\nRESET ROLE;\n'
  } | $PSQL "${ADMIN_ARGS[@]}" -d "$LAB_DATABASE"
}

apply_runtime_grants() {
  $PSQL "${ADMIN_ARGS[@]}" -d "$LAB_DATABASE" <<SQL
REVOKE ALL ON SCHEMA agentic_runtime FROM PUBLIC, $READER_ROLE, $WRITER_ROLE;
REVOKE ALL ON ALL TABLES IN SCHEMA agentic_runtime FROM PUBLIC, $READER_ROLE, $WRITER_ROLE;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA agentic_runtime FROM PUBLIC, $READER_ROLE, $WRITER_ROLE;
GRANT USAGE ON SCHEMA agentic_runtime TO $WRITER_ROLE;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA agentic_runtime TO $WRITER_ROLE;
GRANT UPDATE (status, retrieval_count, model_calls, tool_calls, cost_usd,
              checkpoint_seq, checkpoint, cancellation_reason, updated_at, completed_at)
  ON agentic_runtime.agent_runs TO $WRITER_ROLE;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA agentic_runtime TO $WRITER_ROLE;
ALTER DEFAULT PRIVILEGES FOR ROLE $MIGRATOR_ROLE IN SCHEMA agentic_runtime
  GRANT SELECT, INSERT ON TABLES TO $WRITER_ROLE;
ALTER DEFAULT PRIVILEGES FOR ROLE $MIGRATOR_ROLE IN SCHEMA agentic_runtime
  GRANT USAGE, SELECT ON SEQUENCES TO $WRITER_ROLE;
SQL
}

reader_psql() {
  PGPASSFILE="$READER_PGPASS" $PSQL "${TCP_BASE[@]}" -U "$READER_ROLE" "$@"
}
writer_psql() {
  PGPASSFILE="$WRITER_PGPASS" $PSQL "${TCP_BASE[@]}" -U "$WRITER_ROLE" "$@"
}
expect_denied_reader() {
  local label="$1" sql="$2"
  if reader_psql -c "$sql" >/dev/null 2>&1; then
    echo "DENY|$label|FAIL_ALLOWED" >&2
    return 1
  fi
  echo "DENY|$label|PASS"
}
expect_denied_writer() {
  local label="$1" sql="$2"
  if writer_psql -c "$sql" >/dev/null 2>&1; then
    echo "DENY|$label|FAIL_ALLOWED" >&2
    return 1
  fi
  echo "DENY|$label|PASS"
}
expect_denied_migrator() {
  local label="$1" sql="$2"
  if printf 'SET ROLE %s;\n%s\n' "$MIGRATOR_ROLE" "$sql" | \
      $PSQL "${ADMIN_ARGS[@]}" -d "$LAB_DATABASE" >/dev/null 2>&1; then
    echo "DENY|$label|FAIL_ALLOWED" >&2
    return 1
  fi
  echo "DENY|$label|PASS_TRIGGER"
}

manifest() {
  $PSQL "${ADMIN_ARGS[@]}" -d "$LAB_DATABASE" -AtF '|' <<'SQL'
SELECT 'schema', n.nspname, pg_get_userbyid(n.nspowner), coalesce(array_to_string(n.nspacl, ','), '')
  FROM pg_namespace n
 WHERE n.nspname = 'agentic_runtime'
UNION ALL
SELECT 'relation', n.nspname || '.' || c.relname, pg_get_userbyid(c.relowner),
       c.relkind::text || '|' || coalesce(array_to_string(c.relacl, ','), '')
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'agentic_runtime'
UNION ALL
SELECT 'column', table_schema || '.' || table_name || '.' || column_name, ordinal_position::text,
       data_type || '|' || is_nullable || '|' || coalesce(column_default, '')
  FROM information_schema.columns
 WHERE table_schema = 'agentic_runtime'
UNION ALL
SELECT 'constraint', n.nspname || '.' || c.relname || '.' || con.conname,
       con.contype::text, pg_get_constraintdef(con.oid, true)
  FROM pg_constraint con
  JOIN pg_class c ON c.oid = con.conrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'agentic_runtime'
UNION ALL
SELECT 'trigger', event_object_schema || '.' || event_object_table || '.' || trigger_name,
       event_manipulation, action_statement
  FROM information_schema.triggers
 WHERE event_object_schema = 'agentic_runtime'
ORDER BY 1, 2, 3, 4;
SQL
}

printf '\n=== STAGE 4-5: SYNTHETIC SURFACES AND TCP IDENTITY PROOF ===\n'
reader_psql -Atc "select environment, synthetic_observation_count from approved_canonical.v_agentic_market_snapshot;" \
  | sed 's/^/ALLOW|reader_approved_view|/'
expect_denied_reader reader_agentic_runtime_select \
  "select count(*) from agentic_runtime.agent_runs;"
expect_denied_reader reader_public_create \
  "create table public.reader_should_fail(id integer);"
expect_denied_reader reader_protected_write \
  "insert into lab_protected.denial_target(note) values ('reader denied');"

printf '\n=== STAGE 6: MIGRATION UP AND GRANTS ===\n'
apply_migration_as_migrator "$UP_SQL"
apply_runtime_grants

table_names="$($PSQL "${ADMIN_ARGS[@]}" -d "$LAB_DATABASE" -Atc \
  "select table_name from information_schema.tables where table_schema='agentic_runtime' and table_type='BASE TABLE' order by table_name;")"
expected_names=$'agent_artifacts\nagent_reviews\nagent_runs\nagent_scores\nagent_tool_calls\nkb_cases\nkb_chunks\nkb_lessons'
if [[ "$table_names" != "$expected_names" ]]; then
  echo "BLOCKED_DB_PROOF: expected eight-table inventory mismatch" >&2
  printf 'observed_tables|%s\n' "${table_names//$'\n'/,}"
  exit 5
fi
echo "eight_table_inventory|PASS"
printf '%s\n' "$table_names" | sed 's/^/table|agentic_runtime./'

writer_psql <<'SQL'
INSERT INTO agentic_runtime.agent_runs
  (run_id, agent_id, agent_version, job_type, environment, objective,
   status, input_hash, validation_hash)
VALUES
  ('lab-proof-run', 'lab.producer', '1', 'LAB_PROOF', 'LAB', 'synthetic proof only',
   'CREATED', repeat('a',64), repeat('b',64));

INSERT INTO agentic_runtime.agent_artifacts
  (artifact_id, run_id, producer_agent_id, artifact_type, payload, payload_hash,
   input_hash, validation_hash, prompt_version, provider_family, model)
VALUES
  ('lab-proof-artifact', 'lab-proof-run', 'lab.producer', 'LAB_PROOF',
   '{"synthetic":true}'::jsonb, repeat('c',64), repeat('a',64), repeat('b',64),
   'lab-proof-v1', 'local', 'none');

INSERT INTO agentic_runtime.agent_tool_calls
  (tool_call_id, run_id, agent_id, tool_name, decision, decision_reason,
   arguments_hash, result_hash, completed_at)
VALUES
  ('lab-proof-tool', 'lab-proof-run', 'lab.producer', 'lab.synthetic', 'DENY',
   'proof only', repeat('d',64), repeat('e',64), now());

INSERT INTO agentic_runtime.agent_reviews
  (review_id, artifact_id, producer_agent_id, reviewer_agent_id, verdict,
   findings, artifact_hash)
VALUES
  ('lab-proof-review', 'lab-proof-artifact', 'lab.producer', 'lab.reviewer',
   'PASS', '[]'::jsonb, repeat('c',64));

INSERT INTO agentic_runtime.agent_scores
  (score_id, artifact_id, producer_agent_id, scorer_agent_id, dimensions)
VALUES
  ('lab-proof-score', 'lab-proof-artifact', 'lab.producer', 'lab.scorer',
   '{"synthetic":1}'::jsonb);

INSERT INTO agentic_runtime.kb_lessons
  (lesson_id, lesson_version, lifecycle, title, statement, provenance,
   valid_from, created_by)
VALUES
  ('lab-proof-lesson', 1, 'CANDIDATE', 'synthetic', 'synthetic only',
   '{"source":"lab"}'::jsonb, now(), 'lab.producer');

INSERT INTO agentic_runtime.kb_cases
  (case_id, case_type, source_refs, facts)
VALUES
  ('lab-proof-case', 'LAB_PROOF', '["synthetic"]'::jsonb,
   '{"synthetic":true}'::jsonb);

INSERT INTO agentic_runtime.kb_chunks
  (chunk_id, source_type, source_ref, source_hash, content, valid_from)
VALUES
  ('lab-proof-chunk', 'LAB_PROOF', 'synthetic', repeat('f',64),
   'synthetic only', now());
SQL

echo "ALLOW|writer_insert_agentic_runtime|PASS"
writer_psql -c "update agentic_runtime.agent_runs set status='RETRIEVING', updated_at=now() where run_id='lab-proof-run';" >/dev/null
echo "ALLOW|writer_update_run_control|PASS"

expect_denied_writer writer_public_create \
  "create table public.writer_should_fail(id integer);"
expect_denied_writer writer_database_schema_create \
  "create schema writer_should_fail;"
for schema in "${PROTECTED_SCHEMAS[@]}"; do
  expect_denied_writer "writer_${schema}_write" \
    "insert into $schema.denial_target(note) values ('writer denied');"
done
expect_denied_writer producer_self_review \
  "insert into agentic_runtime.agent_reviews
   (review_id, artifact_id, producer_agent_id, reviewer_agent_id, verdict, findings, artifact_hash)
   values ('lab-self-review','lab-proof-artifact','lab.producer','lab.producer','PASS','[]',repeat('c',64));"
expect_denied_writer producer_self_score \
  "insert into agentic_runtime.agent_scores
   (score_id, artifact_id, producer_agent_id, scorer_agent_id, dimensions)
   values ('lab-self-score','lab-proof-artifact','lab.producer','lab.producer','{}');"

append_only_tables=(agent_artifacts agent_tool_calls agent_reviews agent_scores kb_lessons kb_cases kb_chunks)
for table in "${append_only_tables[@]}"; do
  case "$table" in
    agent_artifacts) where="artifact_id='lab-proof-artifact'" ;;
    agent_tool_calls) where="tool_call_id='lab-proof-tool'" ;;
    agent_reviews) where="review_id='lab-proof-review'" ;;
    agent_scores) where="score_id='lab-proof-score'" ;;
    kb_lessons) where="lesson_id='lab-proof-lesson' and lesson_version=1" ;;
    kb_cases) where="case_id='lab-proof-case'" ;;
    kb_chunks) where="chunk_id='lab-proof-chunk'" ;;
  esac
  expect_denied_migrator "append_only_update_$table" \
    "update agentic_runtime.$table set created_at=created_at where $where;"
  expect_denied_migrator "append_only_delete_$table" \
    "delete from agentic_runtime.$table where $where;"
done

printf '\n=== OWNERSHIP AND GRANT MATRIX ===\n'
$PSQL "${ADMIN_ARGS[@]}" -d "$LAB_DATABASE" -AtF '|' <<SQL
select 'role', rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole
  from pg_roles
 where rolname in ('$MIGRATOR_ROLE','$READER_ROLE','$WRITER_ROLE')
 order by rolname;
select 'owner', n.nspname || '.' || c.relname, pg_get_userbyid(c.relowner), c.relkind
  from pg_class c join pg_namespace n on n.oid=c.relnamespace
 where n.nspname in ('agentic_runtime','approved_canonical')
 order by 2;
select 'table_grant', grantee, table_schema || '.' || table_name, privilege_type
  from information_schema.role_table_grants
 where grantee in ('$MIGRATOR_ROLE','$READER_ROLE','$WRITER_ROLE')
   and table_schema in ('agentic_runtime','approved_canonical')
 order by grantee, table_schema, table_name, privilege_type;
select 'schema_privilege', role_name, schema_name,
       has_schema_privilege(role_name, schema_name, 'USAGE') as can_usage,
       has_schema_privilege(role_name, schema_name, 'CREATE') as can_create
  from (values
    ('$READER_ROLE','approved_canonical'),
    ('$READER_ROLE','agentic_runtime'),
    ('$WRITER_ROLE','agentic_runtime'),
    ('$WRITER_ROLE','public'),
    ('$WRITER_ROLE','trade'),
    ('$WRITER_ROLE','broker'),
    ('$WRITER_ROLE','account'),
    ('$WRITER_ROLE','position'),
    ('$WRITER_ROLE','approval'),
    ('$WRITER_ROLE','configuration')) as x(role_name,schema_name)
 order by role_name, schema_name;
SQL

if grep -R --include='*.py' --include='*.json' --fixed-string "$MIGRATOR_ROLE" \
    "$REPO/scripts/agent_runtime" "$REPO/config/agent_runtime_mvl.json" >/dev/null 2>&1; then
  echo "BLOCKED_DB_PROOF: migration executor appears in runtime Python or runtime config" >&2
  exit 6
fi
echo "runtime_excludes_migration_executor|PASS"

manifest >"$BEFORE_MANIFEST"
readonly BEFORE_HASH="$(sha256sum "$BEFORE_MANIFEST" | awk '{print $1}')"
echo "schema_manifest_before_sha256|$BEFORE_HASH"

printf '\n=== STAGE 7: DOWN ROLLBACK ===\n'
apply_migration_as_migrator "$DOWN_SQL"
remaining="$($PSQL "${ADMIN_ARGS[@]}" -d "$LAB_DATABASE" -Atc \
  "select count(*) from pg_namespace where nspname='agentic_runtime';")"
if [[ "$remaining" != 0 ]]; then
  echo "BLOCKED_DB_PROOF: down migration left agentic_runtime objects" >&2
  exit 7
fi
echo "migration_down_cleanup|PASS"

printf '\n=== STAGE 8: UP REPLAY AND HASH COMPARISON ===\n'
apply_migration_as_migrator "$UP_SQL"
apply_runtime_grants
manifest >"$AFTER_MANIFEST"
readonly AFTER_HASH="$(sha256sum "$AFTER_MANIFEST" | awk '{print $1}')"
echo "schema_manifest_after_sha256|$AFTER_HASH"
if [[ "$BEFORE_HASH" != "$AFTER_HASH" ]]; then
  echo "BLOCKED_DB_PROOF: migration replay manifest hash differs" >&2
  exit 8
fi

replay_count="$($PSQL "${ADMIN_ARGS[@]}" -d "$LAB_DATABASE" -Atc \
  "select count(*) from information_schema.tables where table_schema='agentic_runtime' and table_type='BASE TABLE';")"
if [[ "$replay_count" != 8 ]]; then
  echo "BLOCKED_DB_PROOF: replay did not restore exactly eight tables" >&2
  exit 8
fi

echo "migration_replay_hash_match|PASS"
echo "replay_table_count|$replay_count"
echo "persistence_slice_authorization|LAB_SCHEMA_PROOF_ONLY"
echo "activation_authority|DENIED"
echo "production_database_write|NONE"
echo "final_status|PASS_DB_PROOF"
echo "sanitized_evidence|$EVIDENCE_FILE"
echo "rollback_location|$ROLLBACK_FILE"

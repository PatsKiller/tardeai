#!/usr/bin/env bash
# 00_preflight.sh — packet n8n-app-role-20261027, step 00. READ-ONLY against n8n and its database.
#
#   bash 00_preflight.sh
#
# Confirms the container, volume and compose names; records which role n8n connects as and that role's rolsuper;
# snapshots the active workflow ids (04_verify.sh and 09_rollback.sh compare against it); reports backup and restore
# drill freshness, the relay's latest `op: due` line, the pg_hba rules and the current DB sessions. No SQL here
# writes (every query runs in a read-only transaction). It writes only its own evidence folder:
#   $EVIDENCE_DIR/<UTC>-preflight/ and the pointer $EVIDENCE_DIR/LATEST_PREFLIGHT.
# Exit 0 = ready for step 01; 1 = a precondition is not met (each is printed as NOT READY); 2 = cannot run.
set -euo pipefail
# shellcheck source=docs/ops/packets/n8n-app-role-20261027/_lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"
[[ $# -eq 0 ]] || fail "usage: $0   (no arguments; read-only)"

problems=0
not_ready() {
  say "NOT READY: $*"
  problems=$((problems + 1))
}
OUT="$EVIDENCE_DIR/$STAMP-preflight"
mkdir -p "$OUT"
say "== n8n-app-role preflight $NOW_ISO (evidence $OUT)"

say "== 1. containers, compose project, volumes"
for c in "$N8N_CONTAINER" "$DB_CONTAINER"; do
  running="$(docker inspect "$c" --format '{{.State.Running}}' 2>/dev/null || echo absent)"
  project="$(docker inspect "$c" --format '{{index .Config.Labels "com.docker.compose.project"}}' 2>/dev/null || true)"
  say "  $c running=$running compose_project=${project:-?}"
  [[ "$running" == true ]] || not_ready "container $c is not running"
  [[ "$project" == "$COMPOSE_PROJECT" ]] || not_ready "container $c is not in compose project $COMPOSE_PROJECT"
done
for v in "${VOLUMES[@]}"; do
  if docker volume inspect "$v" --format '{{.Name}}' >/dev/null 2>&1; then say "  volume $v present"; else not_ready "volume $v absent"; fi
done
image_id="$(docker inspect "$N8N_CONTAINER" --format '{{.Image}}' 2>/dev/null || true)"
image_cfg="$(docker inspect "$N8N_CONTAINER" --format '{{.Config.Image}}' 2>/dev/null || true)"
say "  n8n image $image_cfg ($image_id)"

say "== 2. compose file (operator-owned, outside the repo)"
if [[ -f "$LIVE_COMPOSE" ]]; then
  compose_sha="$(sha256_of "$LIVE_COMPOSE")"
  say "  $LIVE_COMPOSE sha256 $compose_sha"
  if grep -q 'DB_POSTGRESDB_USER: n8n_app' "$LIVE_COMPOSE"; then say "  compose already names n8n_app (step 03 applied?)"; fi
else
  compose_sha=""
  not_ready "compose file $LIVE_COMPOSE not found"
fi

say "== 3. the role n8n connects as, and rolsuper"
connect_role="$(container_env_value DB_POSTGRESDB_USER)"
say "  DB_POSTGRESDB_USER=$connect_role  DB_POSTGRESDB_PASSWORD=$(container_env_is_set DB_POSTGRESDB_PASSWORD)  DB_POSTGRESDB_PASSWORD_FILE=$(container_env_is_set DB_POSTGRESDB_PASSWORD_FILE)"
valid_role_name "$connect_role" || not_ready "DB_POSTGRESDB_USER is not a plain role name"
q role_rows "select rolname, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls, rolcanlogin from pg_roles where rolname in ('$BOOTSTRAP_ROLE', '$APP_ROLE') order by rolname;" >"$OUT/roles.txt"
say "  pg_roles (rolname|super|createrole|createdb|replication|bypassrls|canlogin):"
sed 's/^/    /' "$OUT/roles.txt"
connect_super="$(awk -F'|' -v r="$connect_role" '$1 == r {print $2}' "$OUT/roles.txt")"
say "  n8n connects as $connect_role, rolsuper=${connect_super:-?}"
[[ "$connect_super" == t ]] && say "  finding (P13): the role n8n connects as is a superuser; this packet fixes it"

say "== 4. ownership in schema public, migrations, extensions"
q owners "select pg_get_userbyid(relowner) || ':' || relkind::text, count(*) from pg_class where relnamespace = 'public'::regnamespace group by 1 order by 1;" | tee "$OUT/owners.txt" | sed 's/^/  /'
q migrations "select count(*), coalesce(max(timestamp)::text, '') from migrations;" >"$OUT/migrations.txt" 2>/dev/null ||
  echo "unreadable" >"$OUT/migrations.txt"
say "  migrations (count|max timestamp): $(cat "$OUT/migrations.txt")"
say "  extensions: $(q extensions "select string_agg(extname, ',' order by extname) from pg_extension;")"

say "== 5. active workflows snapshot (04 and 09 compare against this)"
active_workflows >"$OUT/active_workflows.txt"
say "  $(grep -c . "$OUT/active_workflows.txt" || true) active: $(paste -sd' ' "$OUT/active_workflows.txt")"
[[ -s "$OUT/active_workflows.txt" ]] || not_ready "no active workflow; the relay op:due check in 04 cannot prove n8n resumed"

say "== 6. backup and restore-drill freshness ($BACKUP_DIR)"
last_dump="$(newest "$BACKUP_DIR" 'n8n-lab-*.dump')"
if [[ -n "$last_dump" ]]; then
  age_h=$((($(date +%s) - $(stat -c %Y "$last_dump")) / 3600))
  say "  newest nightly dump $last_dump (${age_h} h old)"
  ((age_h <= 26)) || warn "nightly dump is older than 26 h; step 01 takes a fresh one regardless"
else
  warn "no nightly dump in $BACKUP_DIR; step 01 takes one"
fi
say "  backup receipt ok=$(receipt_value "$BACKUP_DIR/n8n_lab_backup_last.json" ok) as_of=$(receipt_value "$BACKUP_DIR/n8n_lab_backup_last.json" as_of)"
say "  restore drill state=$(receipt_value "$BACKUP_DIR/n8n_lab_restore_drill_last.json" state) as_of=$(receipt_value "$BACKUP_DIR/n8n_lab_restore_drill_last.json" as_of)"
[[ -d "$BACKUP_DIR" && -w "$BACKUP_DIR" ]] || not_ready "backup dir $BACKUP_DIR missing or not writable"

say "== 7. liveness: healthz and the relay's latest op:due"
if healthz_ok; then say "  healthz ok"; else not_ready "n8n healthz is not ok"; fi
last_due="$(relay_due_after "$(date -u -d '-15 min' +%Y-%m-%dT%H:%M:%SZ)" || true)"
if [[ -n "$last_due" ]]; then say "  relay op:due at $last_due"; else not_ready "no relay op:due line in the last 15 min ($RELAY_LOG)"; fi

say "== 8. pg_hba rules and current sessions (who connects, from where)"
q hba "select line_number, type, array_to_string(database, ','), array_to_string(user_name, ','), coalesce(address, ''), auth_method from pg_hba_file_rules order by line_number;" | tee "$OUT/hba.txt" | sed 's/^/  hba /'
q sessions "select usename, coalesce(host(client_addr), 'local'), count(*) from pg_stat_activity where datname = '$DB_NAME' and backend_type = 'client backend' group by 1, 2 order by 1, 2;" | tee "$OUT/sessions.txt" | sed 's/^/  session /'
say "  bootstrap role network login (inside $DB_CONTAINER, its own POSTGRES_PASSWORD): $(bootstrap_network_login)"

say "== 9. tools the later steps need"
for t in patch curl sha256sum "$PY"; do command -v "$t" >/dev/null 2>&1 || not_ready "tool $t not found"; done
[[ -f "$ROLE_SCRIPT" ]] || not_ready "role script $ROLE_SCRIPT not found (is REPO_ROOT a release that carries it?)"
[[ -f "$COMPOSE_DIFF" ]] || not_ready "compose diff $COMPOSE_DIFF not found"
say "  market session: $(market_state); quiet minute now: $(quiet_minute_now && echo yes || echo no)"

write_receipt "$OUT/preflight.json" step=00_preflight at="$NOW_ISO" connect_role="$connect_role" \
  connect_rolsuper="${connect_super:-}" compose_sha256="$compose_sha" n8n_image_id="$image_id" \
  active_workflows="$(grep -c . "$OUT/active_workflows.txt" || true)" problems="$problems"
basename "$OUT" >"$EVIDENCE_DIR/LATEST_PREFLIGHT"
if ((problems > 0)); then
  say "PREFLIGHT: $problems NOT READY item(s); fix them before step 01"
  exit 1
fi
say "PREFLIGHT OK — next: bash 01_backup.sh (dry run), then --apply"

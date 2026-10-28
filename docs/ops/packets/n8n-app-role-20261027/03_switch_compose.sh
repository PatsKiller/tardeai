#!/usr/bin/env bash
# 03_switch_compose.sh — packet n8n-app-role-20261027, step 03: point the n8n container at n8n_app.
#
#   bash 03_switch_compose.sh                                   # DRY RUN (default): candidate + diff + config check
#   N8N_APP_ROLE_GRANT=<ids> bash 03_switch_compose.sh --apply [--ignore-window]
#
# The change is the reviewed FW-P2 compose diff (docs/ops/packets/n8n-platform-hardening-20261022/compose/
# fw-p2-n8n-app-role.compose.diff.proposed): in the n8n service DB_POSTGRESDB_USER becomes n8n_app,
# DB_POSTGRESDB_PASSWORD (the superuser's password, by ${N8N_PG_PASSWORD}) is REMOVED, and
# DB_POSTGRESDB_PASSWORD_FILE=/run/secrets/n8n_app_pg_password is added with a compose `secrets:` entry whose file is
# the step-02 password file. The password is supplied by name only (a file path and a compose secret name); n8n 2.43
# reads <VAR>_FILE only when <VAR> is unset. The db service is not changed and not recreated.
#
# Dry run: copies the live compose file into the evidence folder, applies the diff to that copy with `patch`, validates
# the copy with `docker compose ... config --quiet` (never without --quiet: that prints interpolated secrets), prints
# `diff -u live candidate`. The live file is not touched.
# --apply (grant, quiet minute, market not PRE/RTH, step 02 done): timestamped backup of the live compose file
# (docker-compose.n8n.yml.bak-<UTC>-pre-n8n-app-role, never overwritten), candidate installed, config --quiet on
# the live file, `docker compose up -d --no-deps n8n` (never `down`, never `-v`), wait for /healthz.
# Then run 04_verify.sh. Rollback: 09_rollback.sh.
set -euo pipefail
# shellcheck source=docs/ops/packets/n8n-app-role-20261027/_lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"
APPLY=0
IGNORE_WINDOW=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --ignore-window) IGNORE_WINDOW=1 ;;
    *) fail "usage: $0 [--apply] [--ignore-window]" ;;
  esac
done
[[ -f "$LIVE_COMPOSE" ]] || fail "compose file $LIVE_COMPOSE not found"
[[ -f "$COMPOSE_DIFF" ]] || fail "compose diff $COMPOSE_DIFF not found"
command -v patch >/dev/null 2>&1 || fail "patch is not installed"
if grep -q 'DB_POSTGRESDB_USER: n8n_app' "$LIVE_COMPOSE"; then
  say "the live compose file already names n8n_app; nothing to switch (run 04_verify.sh)"
  exit 0
fi

OUT="$EVIDENCE_DIR/$STAMP-switch-compose"
mkdir -p "$OUT/candidate"
CANDIDATE="$OUT/candidate/$COMPOSE_FILE"
cp -p -- "$LIVE_COMPOSE" "$OUT/live-before.yml"
cp -p -- "$LIVE_COMPOSE" "$CANDIDATE"
live_sha="$(sha256_of "$LIVE_COMPOSE")"

say "== 1. apply the FW-P2 diff to a copy (the live file is not touched)"
set +e
patch_out="$(patch --forward --batch --no-backup-if-mismatch -r - -p1 -d "$OUT/candidate" <"$COMPOSE_DIFF" 2>&1)"
patch_rc=$?
set -e
printf '%s\n' "$patch_out" | sed 's/^/  /'
[[ $patch_rc -eq 0 ]] || fail "the FW-P2 diff does not apply to the live file (it drifted from the 2026-10-22 base); stop and report"
fuzz=0
grep -qi 'fuzz' <<<"$patch_out" && fuzz=1
grep -q 'DB_POSTGRESDB_USER: n8n_app' "$CANDIDATE" || fail "candidate does not name n8n_app"
grep -q 'DB_POSTGRESDB_PASSWORD_FILE: /run/secrets/n8n_app_pg_password' "$CANDIDATE" || fail "candidate lacks DB_POSTGRESDB_PASSWORD_FILE"
if grep -Eq '^[[:space:]]+DB_POSTGRESDB_PASSWORD:' "$CANDIDATE"; then fail "candidate still sets DB_POSTGRESDB_PASSWORD"; fi
secret_ok=1
grep -qF "file: $PASSWORD_FILE" "$CANDIDATE" || {
  secret_ok=0
  warn "the diff's secret file is not $PASSWORD_FILE (N8N_APP_PASSWORD_FILE); --apply refuses"
}

say "== 2. validate the candidate (config --quiet; prints nothing on success)"
config_ok=1
compose_config_quiet "$CANDIDATE" || config_ok=0
say "  config --quiet: $([[ $config_ok == 1 ]] && echo ok || echo FAILED)"

say "== 3. the compose diff that --apply installs (variable names only; the file holds no values)"
diff -u --label "live $COMPOSE_FILE" --label "candidate" -- "$LIVE_COMPOSE" "$CANDIDATE" | tee "$OUT/compose.diff" | sed 's/^/  /' || true

say "== 4. readiness for --apply"
app_row="$(q app_role "select rolsuper, rolcanlogin from pg_roles where rolname = '$APP_ROLE';")"
say "  $APP_ROLE (rolsuper|rolcanlogin): ${app_row:-absent}"
pw_state="absent"
if [[ -f "$PASSWORD_FILE" ]]; then
  pw_state="mode $(stat -c %a "$PASSWORD_FILE") uid $(stat -c %u "$PASSWORD_FILE") bytes $(stat -c %s "$PASSWORD_FILE")"
fi
say "  password file $PASSWORD_FILE: $pw_state (content never read here)"
say "  n8n connects as $(container_env_value DB_POSTGRESDB_USER) now; healthz $(healthz_ok && echo ok || echo DOWN)"

if [[ $APPLY == 0 ]]; then
  write_receipt "$OUT/switch_compose_dryrun.json" step=03_switch_compose mode=dry_run at="$NOW_ISO" \
    live_sha256="$live_sha" candidate_sha256="$(sha256_of "$CANDIDATE")" config_ok="$config_ok" fuzz="$fuzz"
  say "DRY RUN — the live file and the container are unchanged. --apply would back up $LIVE_COMPOSE to"
  say "  $LIVE_COMPOSE.bak-<UTC>-$BACKUP_TAG, install the candidate, and run: docker compose -p $COMPOSE_PROJECT -f $COMPOSE_FILE up -d --no-deps $N8N_SERVICE"
  exit 0
fi

require_grant "config-write (compose edit) + service (n8n container recreate)"
[[ $config_ok == 1 ]] || fail "candidate failed config --quiet"
[[ $fuzz == 0 ]] || fail "patch applied with fuzz; review $OUT/compose.diff and regenerate the diff"
[[ $secret_ok == 1 ]] || fail "secret file path mismatch (see WARN above)"
[[ "$app_row" == "f|t" ]] || fail "$APP_ROLE is not rolsuper=f, rolcanlogin=t; run 02_create_app_role.sh --apply first"
[[ -f "$PASSWORD_FILE" && "$(stat -c %a "$PASSWORD_FILE")" == 600 && "$(stat -c %u "$PASSWORD_FILE")" == "$(id -u)" ]] ||
  fail "password file must exist, mode 600, owned by $(id -un)"
[[ -n "$(latest_preflight_snapshot)" ]] || fail "no preflight snapshot; run 00_preflight.sh"
healthz_ok || fail "n8n healthz is not ok before the change; investigate first"
require_restart_window "$IGNORE_WINDOW"
[[ "$(sha256_of "$LIVE_COMPOSE")" == "$live_sha" ]] || fail "the live compose file changed during this run"

BAK="$LIVE_COMPOSE.bak-$STAMP-$BACKUP_TAG"
[[ ! -e "$BAK" ]] || fail "$BAK exists; never overwritten"
cp -p -- "$LIVE_COMPOSE" "$BAK"
cmp -s -- "$LIVE_COMPOSE" "$BAK" || fail "backup copy does not match"
say "  backup $BAK"
cat -- "$CANDIDATE" >"$LIVE_COMPOSE" # keeps the live file's inode, owner and mode
compose_config_quiet "$LIVE_COMPOSE" || {
  cat -- "$BAK" >"$LIVE_COMPOSE"
  fail "live file failed config --quiet after install; restored from $BAK; nothing recreated"
}
up_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
compose up -d --no-deps "$N8N_SERVICE"
health="ok"
wait_healthz 180 || health="DOWN"
write_receipt "$OUT/switch_compose.json" step=03_switch_compose mode=apply at="$NOW_ISO" up_at="$up_at" \
  grant="$N8N_APP_ROLE_GRANT" live_sha256_before="$live_sha" live_sha256_after="$(sha256_of "$LIVE_COMPOSE")" \
  compose_backup="$BAK" healthz="$health" connects_as="$(container_env_value DB_POSTGRESDB_USER)"
printf '%s\n' "$STAMP-switch-compose" >"$EVIDENCE_DIR/LATEST_SWITCH"
if [[ "$health" != ok ]]; then
  say "n8n healthz DOWN 180 s after the recreate. Read: docker logs --since 5m $N8N_CONTAINER | tail -50"
  say "Roll back now: N8N_APP_ROLE_GRANT=... bash 09_rollback.sh --apply"
  exit 1
fi
say "STEP 03 APPLIED (up at $up_at) — next: bash 04_verify.sh"

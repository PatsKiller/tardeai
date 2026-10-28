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
# --apply (grant, quiet minute, market not PRE/RTH, step 02 done, password file readable by the container's uid):
# timestamped backup of the live compose file (docker-compose.n8n.yml.bak-<UTC>-pre-n8n-app-role, never
# overwritten), candidate installed, config --quiet on the live file, `docker compose up -d --no-deps n8n` (never
# `down`, never `-v`), wait for /healthz.
# AUTOMATIC REVERT: if anything fails after the candidate is installed — config, `compose up`, or /healthz not ok
# within N8N_HEALTHZ_WAIT s — an EXIT trap saves the container log tail to the evidence folder, puts the backup
# back, runs `up -d --no-deps n8n` again (no DB change is needed: n8n connects as n8n, which still has every
# privilege), writes switch_compose_failed.json and prints the 09 command. Then run 04_verify.sh. Rollback: 09.
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
ROLLBACK_HINT="N8N_APP_ROLE_GRANT=\"<config-write id> <service id>\" bash $PACKET_DIR/09_rollback.sh --apply"
[[ -f "$LIVE_COMPOSE" ]] || fail "compose file $LIVE_COMPOSE not found"
[[ -f "$COMPOSE_DIFF" ]] || fail "compose diff $COMPOSE_DIFF not found"
[[ "$COMPOSE_DIFF" == "$REVIEWED_COMPOSE_DIFF" ]] || warn "N8N_APP_ROLE_COMPOSE_DIFF overrides the reviewed diff: $COMPOSE_DIFF"
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
cuid="$(container_uid)"
pw_ok=1
pw_verdict="$(password_file_container_readable "$cuid")" || pw_ok=0
say "  password file $PASSWORD_FILE: $pw_verdict (content never read here)"
say "  n8n connects as $(container_env_value DB_POSTGRESDB_USER) now; healthz $(healthz_ok && echo ok || echo DOWN)"

if [[ $APPLY == 0 ]]; then
  write_receipt "$OUT/switch_compose_dryrun.json" step=03_switch_compose mode=dry_run at="$NOW_ISO" \
    live_sha256="$live_sha" candidate_sha256="$(sha256_of "$CANDIDATE")" config_ok="$config_ok" fuzz="$fuzz" \
    password_file_readable="$pw_ok" container_uid="$cuid"
  say "DRY RUN — the live file and the container are unchanged. --apply would back up $LIVE_COMPOSE to"
  say "  $LIVE_COMPOSE.bak-<UTC>-$BACKUP_TAG, install the candidate, and run: docker compose -p $COMPOSE_PROJECT -f $COMPOSE_FILE up -d --no-deps $N8N_SERVICE"
  say "  (on any failure after the install it puts the backup back and recreates n8n as before)"
  exit 0
fi

require_grant "config-write (compose edit) + service (n8n container recreate)"
[[ $config_ok == 1 ]] || fail "candidate failed config --quiet"
[[ $fuzz == 0 ]] || fail "patch applied with fuzz; review $OUT/compose.diff and regenerate the diff"
[[ $secret_ok == 1 ]] || fail "secret file path mismatch (see WARN above)"
[[ "$app_row" == "f|t" ]] || fail "$APP_ROLE is not rolsuper=f, rolcanlogin=t; run 02_create_app_role.sh --apply first"
[[ $pw_ok == 1 ]] || fail "password file: $pw_verdict"
[[ -n "$(latest_preflight_snapshot)" ]] || fail "no preflight snapshot; run 00_preflight.sh"
healthz_ok || fail "n8n healthz is not ok before the change; investigate first"
require_restart_window "$IGNORE_WINDOW"
[[ "$(sha256_of "$LIVE_COMPOSE")" == "$live_sha" ]] || fail "the live compose file changed during this run"

BAK="$LIVE_COMPOSE.bak-$STAMP-$BACKUP_TAG"
[[ ! -e "$BAK" ]] || fail "$BAK exists; never overwritten"
cp -p -- "$LIVE_COMPOSE" "$BAK"
cmp -s -- "$LIVE_COMPOSE" "$BAK" || fail "backup copy does not match"
say "  backup $BAK"

INSTALLED=0
UP_STARTED=0
FINISHED=0
STAGE="install"
up_at=""
# EXIT trap: after the candidate is installed, any failure puts the backup back and recreates n8n as it was.
# shellcheck disable=SC2329  # invoked by `trap revert_on_failure EXIT`
revert_on_failure() {
  local rc=$?
  [[ $INSTALLED == 1 && $FINISHED == 0 ]] || return 0
  trap - EXIT
  set +e
  say "== step 03 FAILED at stage '$STAGE' (exit $rc); reverting to $BAK"
  if [[ $UP_STARTED == 1 ]]; then
    (umask 077 && docker logs --since 15m "$N8N_CONTAINER" >"$OUT/n8n-container-log-tail.txt" 2>&1)
    say "  container log tail saved to $OUT/n8n-container-log-tail.txt (not printed)"
  fi
  cat -- "$BAK" >"$LIVE_COMPOSE"
  local r_cfg=ok r_up=skipped r_health=skipped
  compose_config_quiet "$LIVE_COMPOSE" || r_cfg=FAILED
  if [[ $UP_STARTED == 1 ]]; then
    r_up=ok
    compose up -d --no-deps "$N8N_SERVICE" || r_up=FAILED
    r_health=DOWN
    wait_healthz "$HEALTHZ_WAIT" && r_health=ok
  fi
  local who
  who="$(container_env_value DB_POSTGRESDB_USER)"
  write_receipt "$OUT/switch_compose_failed.json" step=03_switch_compose mode=apply_failed at="$NOW_ISO" \
    grant="$N8N_APP_ROLE_GRANT" failed_stage="$STAGE" exit_code="$rc" up_at="$up_at" compose_backup="$BAK" \
    live_sha256_after_revert="$(sha256_of "$LIVE_COMPOSE")" revert_config="$r_cfg" revert_up="$r_up" \
    revert_healthz="$r_health" connects_as="$who" candidate="$CANDIDATE"
  if [[ $r_cfg == ok && $r_up != FAILED && $r_health != DOWN ]]; then
    say "REVERTED: the compose file is the backup again; n8n connects as ${who:-?}; healthz $r_health."
  else
    say "REVERT INCOMPLETE: config=$r_cfg up=$r_up healthz=$r_health. Finish it by hand now:"
  fi
  say "Rollback / re-check command: $ROLLBACK_HINT"
  say "(no DB change is needed before step 05; n8n_app and its password file stay for a later retry)"
  exit 1
}
trap revert_on_failure EXIT

cat -- "$CANDIDATE" >"$LIVE_COMPOSE" # keeps the live file's inode, owner and mode
INSTALLED=1
STAGE="config"
compose_config_quiet "$LIVE_COMPOSE"
STAGE="compose_up"
up_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
UP_STARTED=1
compose up -d --no-deps "$N8N_SERVICE"
STAGE="healthz"
wait_healthz "$HEALTHZ_WAIT" || {
  say "  n8n healthz not ok ${HEALTHZ_WAIT}s after the recreate"
  exit 1
}
FINISHED=1
trap - EXIT
write_receipt "$OUT/switch_compose.json" step=03_switch_compose mode=apply at="$NOW_ISO" up_at="$up_at" \
  grant="$N8N_APP_ROLE_GRANT" live_sha256_before="$live_sha" live_sha256_after="$(sha256_of "$LIVE_COMPOSE")" \
  compose_backup="$BAK" healthz=ok connects_as="$(container_env_value DB_POSTGRESDB_USER)"
printf '%s\n' "$STAMP-switch-compose" >"$EVIDENCE_DIR/LATEST_SWITCH"
say "STEP 03 APPLIED (up at $up_at) — next: bash 04_verify.sh"
say "Rollback, if 04 fails or you decide to: $ROLLBACK_HINT"

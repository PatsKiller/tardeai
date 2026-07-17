#!/usr/bin/env bash
# backup_all.sh — run EVERY backup family NOW so offsite is at its latest.
# (2026-07-17 audit follow-up: the "refresh everything" button — use before risky
# maintenance, migrations, or whenever the operator wants a known-current offsite set.)
#
# Runs: pg dump (local) → env → memory → ops → data → db-offsite → apps.
# Weekly-gated families run UNCONDITIONALLY here and their cadence stamps are
# touched on success, so tonight's 02:30 run gate-skips instead of duplicating.
#
# Usage: bash scripts/backup_all.sh [--skip-db]   (--skip-db: omit the 1.5GB offsite upload)
set -uo pipefail
PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_DB=0
[ "${1:-}" = "--skip-db" ] && SKIP_DB=1

declare -A RESULT
overall=0

step() {
  local name="$1"; shift
  echo "==== [$name] START $(date -Is) ===="
  if "$@"; then
    RESULT[$name]="ok"
    echo "==== [$name] OK ===="
  else
    RESULT[$name]="FAILED($?)"
    overall=1
    echo "==== [$name] FAILED ====" >&2
  fi
}

stamp() { mkdir -p "$PROJ/data/runtime"; touch "$PROJ/data/runtime/$1"; }

step pg_dump          bash "$PROJ/linux_launchers/run_pg_backup.sh"
step env_offsite      bash "$PROJ/scripts/backup_secrets_state.sh" env
step memory_offsite   bash "$PROJ/scripts/backup_secrets_state.sh" memory
step ops_offsite      bash "$PROJ/scripts/backup_secrets_state.sh" ops
step data_offsite     bash "$PROJ/scripts/backup_secrets_state.sh" data \
  && [ "${RESULT[data_offsite]}" = "ok" ] && stamp last_secrets_data_backup.stamp
if [ "$SKIP_DB" = "0" ]; then
  step db_offsite     bash "$PROJ/scripts/backup_secrets_state.sh" db \
    && [ "${RESULT[db_offsite]}" = "ok" ] && stamp last_db_offsite_backup.stamp
else
  RESULT[db_offsite]="skipped(--skip-db)"
fi
step apps_offsite     bash "$PROJ/scripts/backup_secrets_state.sh" apps \
  && [ "${RESULT[apps_offsite]}" = "ok" ] && stamp last_apps_backup.stamp

echo ""
echo "======== backup_all summary $(date -Is) ========"
for k in pg_dump env_offsite memory_offsite ops_offsite data_offsite db_offsite apps_offsite; do
  printf "  %-16s %s\n" "$k" "${RESULT[$k]:-not-run}"
done
exit $overall

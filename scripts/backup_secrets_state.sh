#!/usr/bin/env bash
# backup_secrets_state.sh — encrypted offsite backup of .env secrets and/or data/ state to Google Drive.
#
# Bundles the requested target into a dated tar.gz, encrypts it with gpg AES-256
# (symmetric, passphrase from a local 0600 file), uploads the .gpg to a dedicated
# Drive folder, and prunes to a rolling retention window. Plaintext never leaves
# the machine; only the encrypted blob is uploaded.
#
# Usage:
#   scripts/backup_secrets_state.sh env     # .env + .env.* variants (small, daily)
#   scripts/backup_secrets_state.sh data    # data/ state (large, weekly)
#   scripts/backup_secrets_state.sh memory  # Claude persistent memory dir (small, daily)
#
# Restore:
#   gpg --batch --passphrase-file <pass> -d <file>.tar.gz.gpg > out.tar.gz && tar xzf out.tar.gz
set -euo pipefail

TARGET="${1:-}"
PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS_FILE="$HOME/.openclaw/credentials/env_data_backup.pass"
DRIVE_FOLDER="1GYbZyM8nTfwuh-h2EsWTxbMpXlEUA6Qi"   # Trade_AI_Backups
ACCT="john@jwwhiting.com"
GOG="$HOME/.local/bin/gog"
GOG_KEYRING_PW_FILE="$HOME/.openclaw/credentials/gog_keyring_password"
STAMP="$(date +%Y%m%d_%H%M%S)"

TAR_BASE="$PROJ"
case "$TARGET" in
  env)  PREFIX="env_backup";  KEEP=7;  SOURCES=(".env"); GLOB=".env.*" ;;
  data) PREFIX="data_backup"; KEEP=4;  SOURCES=("data");  GLOB="" ;;
  # Claude persistent memory (financial profile, project state) lives OUTSIDE the project
  # tree — tar from $HOME. Small (<1MB), daily, same encryption; also mirrored to the
  # private GitHub repo trade-ai-memory (this is the second, key-independent copy).
  memory) PREFIX="memory_backup"; KEEP=7; TAR_BASE="$HOME"
          SOURCES=(".claude/projects/-home-johnclaw/memory"); GLOB="" ;;
  # 2026-07-17 backup-scope audit additions:
  # db   — newest local pg dump goes OFFSITE weekly (dumps were local-only: a disk loss
  #        took the DB history with it). Already gzipped; gpg adds the encryption layer.
  # ops  — crontab + systemd user units, regenerated at run time (tiny, daily).
  # apps — the other applications on this box: OpenClaw config/credentials/agents/memory/
  #        state (NOT the 2.2G workspace) + nyc-dof-auction (which has NO git remote),
  #        minus venvs/caches. Weekly.
  db)   PREFIX="db_backup"; KEEP=2; SOURCES=(); GLOB="" ;;
  ops)  PREFIX="ops_backup"; KEEP=7; SOURCES=(); GLOB="" ;;
  apps) PREFIX="apps_backup"; KEEP=2; TAR_BASE="$HOME"
        SOURCES=(".openclaw/credentials" ".openclaw/agents" ".openclaw/memory"
                 ".openclaw/state" ".openclaw/openclaw.json" ".openclaw/exec-approvals.json"
                 "nyc-dof-auction"); GLOB="" ;;
  *) echo "usage: $0 {env|data|memory|db|ops|apps}" >&2; exit 2 ;;
esac

[ -f "$PASS_FILE" ] || { echo "FATAL: passphrase file missing: $PASS_FILE" >&2; exit 1; }
[ -x "$GOG" ] || { echo "FATAL: gog not found: $GOG" >&2; exit 1; }
export GOG_KEYRING_PASSWORD="$(cat "$GOG_KEYRING_PW_FILE")"

cd "$PROJ"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

TAR="$TMP/${PREFIX}_${STAMP}.tar.gz"
ENC="$TAR.gpg"

if [ "$TARGET" = "db" ]; then
  # newest local pg dump (written by run_pg_backup.sh, integrity-tested at creation);
  # no re-tar — gpg the .sql.gz directly.
  NEWEST_DUMP="$(ls -t "$HOME"/db_backups/trade_ai_*.sql.gz 2>/dev/null | head -1)"
  [ -n "$NEWEST_DUMP" ] || { echo "FATAL: no local db dump found" >&2; exit 1; }
  echo "[backup:db] offsiting $(basename "$NEWEST_DUMP") ($(du -h "$NEWEST_DUMP" | cut -f1))"
  TAR="$TMP/${PREFIX}_${STAMP}.sql.gz"
  cp "$NEWEST_DUMP" "$TAR"
  ENC="$TAR.gpg"
elif [ "$TARGET" = "ops" ]; then
  # regenerate the operational state that lives nowhere else: crontab + systemd user units
  OPS_DIR="$TMP/ops_state"
  mkdir -p "$OPS_DIR/systemd_user"
  crontab -l > "$OPS_DIR/crontab.txt" 2>/dev/null || true
  cp "$HOME"/.config/systemd/user/*.service "$HOME"/.config/systemd/user/*.timer "$OPS_DIR/systemd_user/" 2>/dev/null || true
  systemctl --user list-timers --all --no-pager > "$OPS_DIR/timers_state.txt" 2>/dev/null || true
  echo "[backup:ops] bundling crontab + $(ls "$OPS_DIR/systemd_user" | wc -l) systemd unit file(s)"
  tar czf "$TAR" -C "$TMP" ops_state
elif [ "$TARGET" = "apps" ]; then
  LIST=()
  for s in "${SOURCES[@]}"; do [ -e "$TAR_BASE/$s" ] && LIST+=("$s"); done
  [ ${#LIST[@]} -gt 0 ] || { echo "FATAL: nothing to back up for target 'apps'" >&2; exit 1; }
  echo "[backup:apps] bundling ${#LIST[@]} path(s) (excl. venv/caches): ${LIST[*]}"
  tar czf "$TAR" -C "$TAR_BASE" \
      --exclude='.venv' --exclude='node_modules' --exclude='__pycache__' \
      --exclude='*.pyc' --exclude='.git/objects/pack/*.pack.tmp' \
      "${LIST[@]}"
else
  # Build the file list (exclude the safe template; include rotated .env.* variants for env mode).
  LIST=()
  for s in "${SOURCES[@]}"; do [ -e "$TAR_BASE/$s" ] && LIST+=("$s"); done
  if [ -n "$GLOB" ]; then
    while IFS= read -r f; do
      bn="$(basename "$f")"
      [ "$bn" = ".env.example" ] && continue
      LIST+=("$bn")
    done < <(find "$PROJ" -maxdepth 1 -name "$GLOB" -type f 2>/dev/null)
  fi
  [ ${#LIST[@]} -gt 0 ] || { echo "FATAL: nothing to back up for target '$TARGET'" >&2; exit 1; }

  echo "[backup:$TARGET] bundling ${#LIST[@]} path(s): ${LIST[*]}"
  tar czf "$TAR" -C "$TAR_BASE" "${LIST[@]}"
fi

# Encrypt (AES-256, symmetric). Plaintext tar is deleted with $TMP on exit.
gpg --batch --yes --pinentry-mode loopback --passphrase-file "$PASS_FILE" \
    --cipher-algo AES256 -c -o "$ENC" "$TAR"
SIZE="$(du -h "$ENC" | cut -f1)"
echo "[backup:$TARGET] encrypted -> $(basename "$ENC") ($SIZE)"

# Upload to Drive.
"$GOG" drive upload "$ENC" -a "$ACCT" --parent "$DRIVE_FOLDER" -p 2>&1 | grep -E "^id|^name" || true
echo "[backup:$TARGET] uploaded to Drive folder $DRIVE_FOLDER"

# Retention: keep newest $KEEP for this prefix, delete the rest.
mapfile -t OLD < <(
  "$GOG" drive ls -a "$ACCT" --parent "$DRIVE_FOLDER" -p 2>/dev/null \
    | awk -F'\t' -v p="$PREFIX" '$2 ~ ("^"p"_") {print $5"\t"$1"\t"$2}' \
    | sort -r | awk -v k="$KEEP" 'NR>k {print $2}'
)
for id in "${OLD[@]:-}"; do
  [ -z "$id" ] && continue
  "$GOG" drive rm "$id" -a "$ACCT" -y --permanent >/dev/null 2>&1 && echo "[backup:$TARGET] pruned old backup $id"
done

echo "[backup:$TARGET] done ($STAMP)"

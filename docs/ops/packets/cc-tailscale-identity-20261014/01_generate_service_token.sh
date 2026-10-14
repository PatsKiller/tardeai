#!/usr/bin/env bash
# 01 — generate the per-host Command Center service token (0600, outside the repo).
# Dry run by default; pass --apply. Never prints the token. Refuses to overwrite an existing token
# (rotation: move the old file aside yourself, then re-run; the server re-reads on mtime change and
# clients read it per call — no restart needed).
set -euo pipefail
DIR="$HOME/.config/tradeai"
FILE="$DIR/cc_service_token"
if [[ "${1:-}" != "--apply" ]]; then
  echo "[dry-run] would: install -d -m 700 $DIR"
  echo "[dry-run] would: (umask 077; openssl rand -hex 32 > $FILE.new); chmod 600; mv -n $FILE.new $FILE"
  if [[ -e "$FILE" ]]; then echo "[dry-run] NOTE: $FILE already exists ($(stat -c '%a %U' "$FILE")) — apply would refuse"; fi
  exit 0
fi
if [[ -e "$FILE" ]]; then echo "refusing: $FILE exists ($(stat -c '%a %U' "$FILE"))"; exit 1; fi
install -d -m 700 "$DIR"
( umask 077; openssl rand -hex 32 > "$FILE.new" )
chmod 600 "$FILE.new"
mv -n "$FILE.new" "$FILE"
stat -c '%a %U %s bytes %n' "$FILE"
echo "token written (value not shown)."
echo "check: python3 ~/trade-ai-releases/portfolio-server/CURRENT/scripts/lib/cc_auth.py --describe | grep token_status"

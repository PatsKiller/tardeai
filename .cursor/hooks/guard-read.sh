#!/usr/bin/env bash
set -uo pipefail
input=$(cat)
path=$(printf '%s' "$input" | jq -r '.file_path // empty')
case "$path" in
  *.env|*.env.*|*/.env|*/.env.*|*.pem|*.key|*id_ed25519*|*id_rsa*|*/.ssh/*|*credentials*|*.pgpass)
    jq -nc --arg u "BLOCKED: $path is a secret file and was not sent to the model. Secrets live in Bitwarden." '{permission:"deny", user_message:$u}'
    exit 0 ;;
esac
printf '{"permission":"allow"}\n'

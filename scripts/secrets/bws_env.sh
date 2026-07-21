#!/usr/bin/env bash
# bws_env.sh — run a command with BWS_ACCESS_TOKEN from a token file (env dict only).
# Usage:
#   scripts/secrets/bws_env.sh read  -- bws project list
#   scripts/secrets/bws_env.sh write -- bws secret list
# Never echoes the token. Token never appears on argv of the child (env only).
set -euo pipefail

ROLE="${1:-}"
if [[ -z "$ROLE" || "$ROLE" == "-h" || "$ROLE" == "--help" ]]; then
  echo "usage: $0 {read|write} -- <command> [args...]" >&2
  exit 2
fi
shift
if [[ "${1:-}" == "--" ]]; then shift; fi
if [[ $# -lt 1 ]]; then
  echo "usage: $0 {read|write} -- <command> [args...]" >&2
  exit 2
fi

case "$ROLE" in
  read|ms01-render)  TOKEN_FILE="${BWS_READ_TOKEN_FILE:-$HOME/.openclaw/credentials/bws_read_token}" ;;
  write|ms01-writer) TOKEN_FILE="${BWS_WRITE_TOKEN_FILE:-$HOME/.openclaw/credentials/bws_write_token}" ;;
  *)
    echo "unknown role: $ROLE (use read|write)" >&2
    exit 2
    ;;
esac

if [[ ! -r "$TOKEN_FILE" ]]; then
  echo "token file missing/unreadable: $TOKEN_FILE" >&2
  exit 1
fi

# Load token into env only — never print, never pass as CLI flag.
export BWS_ACCESS_TOKEN
BWS_ACCESS_TOKEN="$(tr -d '\n\r' < "$TOKEN_FILE")"
if [[ -z "$BWS_ACCESS_TOKEN" || "${#BWS_ACCESS_TOKEN}" -le 40 ]]; then
  echo "token file empty or too short: $TOKEN_FILE" >&2
  exit 1
fi

export PATH="${HOME}/.local/bin:${PATH}"
exec "$@"

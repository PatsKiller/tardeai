#!/usr/bin/env bash
# Read guard. failClosed: jq/policy/ledger failure must NEVER yield allow.
set -uo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

deny() {
  jq -nc --arg u "$1" '{permission:"deny", user_message:$u}' \
    || printf '{"permission":"deny","user_message":"GUARD READ FAIL-CLOSED — could not encode deny."}\n'
  exit 0
}

command -v jq >/dev/null 2>&1 || deny "GUARD DEGRADED — jq is not on PATH. Read refused."
# shellcheck source=/dev/null
source "$HERE/guard-lib.sh" || deny "GUARD DEGRADED — guard-lib.sh could not be loaded. Read refused."

if ledger_is_corrupt; then
  deny "BLOCKED — APPROVAL_LEDGER_CORRUPT ($(ledger_state)). Guarded read refused."
fi

input=$(timeout 5 cat) || true
[[ -n "${input:-}" ]] || deny "GUARD DEGRADED — no read payload within 5s. Read refused."

# Forced-jq-failure test: GUARD_READ_FORCE_JQ_FAIL=1 must NOT allow.
if [[ "${GUARD_READ_FORCE_JQ_FAIL:-}" == "1" ]]; then
  deny "GUARD DEGRADED — forced jq failure. Read refused."
fi

path=$(printf '%s' "$input" | jq -r '.file_path // empty') || deny "GUARD DEGRADED — jq failed parsing the read payload. Read refused."

case "$path" in
  *.env|*.env.*|*/.env|*/.env.*|*.pem|*.key|*id_ed25519*|*id_rsa*|*/.ssh/*|*credentials*|*.pgpass)
    deny "BLOCKED: $path is a secret file and was not sent to the model. Secrets live in Bitwarden."
    ;;
esac
printf '{"permission":"allow"}\n'
exit 0

#!/usr/bin/env bash
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/guard-lib.sh"
input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.command // empty')
tier=$(classify_cmd "$cmd")
emit() { jq -nc --arg p "$1" --arg u "$2" --arg a "$3" '{continue:true, permission:$p, user_message:$u, agent_message:$a}'; exit 0; }

case "$tier" in
  secret) emit deny "BLOCKED — secret access. All secrets live in Bitwarden; nothing credential-shaped is read from or written to this machine by an agent." \
                    "Read configuration shape from .env.example. Never print, copy, or transmit credential values, and never create credential files." ;;
  gate)   emit deny "BLOCKED — gate/interlock modification. These are audit records of the paper-trading history, not fixtures." \
                    "The four live-trading gates and the Schwab interlock are never edited by an agent. If data disagrees with code, report it; do not reconcile it." ;;
  none)   printf '{"permission":"allow"}\n'; exit 0 ;;
esac

if grant_active "$tier"; then
  grant_consume "$tier"
  left=$(grant_left "$tier"); reason=$(grant_reason "$tier")
  audit_line "$(jq -nc --arg ts "$(date -Is)" --arg t "$tier" --arg c "$cmd" --arg r "$reason" '{ts:$ts, event:"auto-accepted", tier:$t, command:$c, grant_reason:$r}')"
  emit allow "AUTO-ACCEPTED [$tier] under approved plan: $reason  (uses left: $left)" "This ran under a scope you already approved. Stay inside it."
fi

emit ask "APPROVAL NEEDED — scope: $tier

COMMAND:
  $cmd

WHAT THIS SCOPE COVERS IF YOU APPROVE IT BROADLY:
  $(tier_scope "$tier")

  [Approve in Cursor] = this one command only.
  [Whole scope]       = in a terminal on ms01:
                          bin/guard grant $tier --for 30m --uses 10 --reason \"...\"
                        then retry. Auto-expires; revoke: bin/guard revoke $tier" \
"Wait for approval. State exactly what you intend to change and how to reverse it. Do not rephrase the command to avoid this prompt."

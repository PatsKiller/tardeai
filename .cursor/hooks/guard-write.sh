#!/usr/bin/env bash
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/guard-lib.sh"
input=$(cat)
tool=$(printf '%s' "$input" | jq -r '.tool_name // empty')
path=$(printf '%s' "$input" | jq -r '.tool_input.path // .tool_input.file_path // .tool_input.target_file // empty')
tier=$(classify_path "$path" "$tool")
emit() { jq -nc --arg p "$1" --arg u "$2" --arg a "$3" '{permission:$p, user_message:$u, agent_message:$a}'; exit 0; }

case "$tier" in
  secret) emit deny "BLOCKED — writing to a secret file ($path). Secrets live in Bitwarden only." \
                    "Add new keys to .env.example with empty values. Never create credential files." ;;
  gate)   emit deny "BLOCKED — gate/interlock file write ($path)." \
                    "These are audit records. Report discrepancies; never edit them." ;;
  none)   printf '{"permission":"allow"}\n'; exit 0 ;;
esac

if grant_active "$tier"; then
  grant_consume "$tier"
  audit_line "$(jq -nc --arg ts "$(date -Is)" --arg t "$tier" --arg p "$path" --arg r "$(grant_reason "$tier")" '{ts:$ts, event:"auto-accepted", tier:$t, path:$p, grant_reason:$r}')"
  emit allow "AUTO-ACCEPTED [$tier] write: $path  (uses left: $(grant_left "$tier"))" "Inside an approved scope."
fi

emit ask "APPROVAL NEEDED — scope: $tier

$tool: $path

WHAT THIS SCOPE COVERS IF YOU APPROVE IT BROADLY:
  $(tier_scope "$tier")

  [Whole scope] = bin/guard grant $tier --for 30m --uses 10 --reason \"...\"" \
"Wait for approval. Explain the change and how to reverse it."

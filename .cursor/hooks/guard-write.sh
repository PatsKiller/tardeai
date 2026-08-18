#!/usr/bin/env bash
# File-mutation guard. Runs failClosed, so every exit path must print exactly
# one verdict. Guarded paths deny unless the ledger holds a matching grant: an
# "ask" verdict does not gate an agent session.
set -uo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIAG="${CURSOR_PROJECT_DIR:-$HOME}/logs/cursor-guard-diag.jsonl"
EMITTED=0
STAGE=start

diag() {
  mkdir -p "$(dirname "$DIAG")" 2>/dev/null
  printf '{"ts":"%s","hook":"guard-write","stage":"%s","detail":"%s"}\n' \
    "$(date -Is 2>/dev/null)" "$STAGE" "${1//\"/\'}" >> "$DIAG" 2>/dev/null || true
}

on_exit() {
  local rc=$?
  [[ "$EMITTED" -eq 1 ]] && return 0
  printf '{"permission":"deny","user_message":"GUARD HOOK FAULT — guard-write.sh exited rc=%s at stage %s without reaching a verdict. The write was refused rather than allowed. Diagnostics: logs/cursor-guard-diag.jsonl","agent_message":"The write guard failed internally and refused the mutation. Report this fault."}\n' \
    "${rc//[^0-9]/}" "${STAGE//[^a-z]/}"
  diag "fault-fallback rc=$rc"
}
trap on_exit EXIT
trap 'exit 143' TERM INT

emit() {
  EMITTED=1
  jq -nc --arg p "$1" --arg u "$2" --arg a "$3" '{permission:$p, user_message:$u, agent_message:$a}' \
    || printf '{"permission":"deny","user_message":"GUARD HOOK FAULT — verdict could not be encoded (jq unavailable). Write refused.","agent_message":"jq is missing or failed inside the write guard."}\n'
  exit 0
}

allow() { EMITTED=1; printf '{"permission":"allow"}\n'; exit 0; }

STAGE=deps
command -v jq >/dev/null 2>&1 || { diag "jq not on PATH"; emit deny \
  "GUARD DEGRADED — jq is not on PATH inside the hook, so the target path cannot be classified. Write refused." \
  "The guard cannot classify this path. Do not retry; report the fault."; }

STAGE=lib
# shellcheck source=/dev/null
source "$HERE/guard-lib.sh" || { diag "guard-lib.sh failed to source"; emit deny \
  "GUARD DEGRADED — guard-lib.sh could not be loaded, so the target path cannot be classified. Write refused." \
  "The guard classifier is unavailable. Do not retry; report the fault."; }

STAGE=stdin
input=$(timeout 5 cat) || true
[[ -n "$input" ]] || { diag "empty or timed-out stdin"; emit deny \
  "GUARD DEGRADED — the hook received no payload within 5s. Write refused." \
  "The guard could not read the mutation request. Do not assume it was allowed."; }

STAGE=classify
tool=$(printf '%s' "$input" | jq -r '.tool_name // empty')
path=$(printf '%s' "$input" | jq -r '.tool_input.path // .tool_input.file_path // .tool_input.target_file // empty')
# Record which mutation tools reach this guard, so a primitive that is added to
# the environment later shows up here instead of slipping past the matcher.
diag "tool=${tool:-UNKNOWN} path=${path:-NONE}"
if [[ -z "$path" ]]; then
  # No path means nothing classifiable; a mutation tool that carries its target
  # under a different key must not be waved through.
  case "$tool" in
    Write|Delete|StrReplace|Edit|MultiEdit|EditNotebook)
      diag "known mutation tool with no resolvable path"
      emit deny "GUARD DEGRADED — $tool supplied no recognisable target path, so it cannot be classified. Write refused." \
                "The guard could not determine what this tool would modify. Report the payload shape." ;;
    *) allow ;;
  esac
fi
tier=$(classify_path "$path" "$tool")

STAGE=verdict
case "$tier" in
  secret) emit deny "BLOCKED — writing to a secret file ($path). Secrets live in Bitwarden only." \
                    "Add new keys to .env.example with empty values. Never create credential files." ;;
  gate)   emit deny "BLOCKED — gate/interlock file write ($path)." \
                    "These are audit records. Report discrepancies; never edit them." ;;
  none)   allow ;;
esac

STAGE=grant
if ledger_is_corrupt; then
  emit deny "BLOCKED — APPROVAL_LEDGER_CORRUPT ($(ledger_state)). Write refused." \
            "The approval ledger is corrupt. The operator must recover it."
fi
grant_consume "$tier"
_gc=$?
if [[ "$_gc" -eq 2 ]]; then
  emit deny "BLOCKED — APPROVAL_LEDGER_CORRUPT. Write refused." \
            "The approval ledger is corrupt. The operator must recover it."
fi
if [[ "$_gc" -eq 0 ]]; then
  left=$(printf '%s' "${GRANT_CONSUME_JSON:-{}}" | jq -r '.uses_left // 0')
  reason=$(printf '%s' "${GRANT_CONSUME_JSON:-{}}" | jq -r '.reason // "—"')
  audit_line "$(jq -nc --arg ts "$(date -Is)" --arg t "$tier" --arg p "$path" --arg o "$tool" --arg r "$reason" \
    '{ts:$ts, event:"auto-accepted", tier:$t, tool:$o, path:$p, grant_reason:$r}')"
  emit allow "AUTO-ACCEPTED [$tier] $tool: $path  (uses left: $left)" "Inside an approved scope."
fi

STAGE=denied
emit deny "BLOCKED — scope: $tier  (no active grant)

$tool: $path

WHAT THIS SCOPE COVERS:
  $(tier_scope "$tier")

TO ALLOW IT, in a terminal on ms01:
  bin/guard grant $tier --for 30m --uses 10 --reason \"...\"
then ask the agent to retry. Revoke: bin/guard revoke $tier" \
"Blocked for want of a grant in scope '$tier'. Explain the change and how to reverse it, then wait. Do not reach the same file through a different tool."

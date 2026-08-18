#!/usr/bin/env bash
# Shell guard. Runs failClosed, so an empty verdict locks the agent out of the
# terminal completely — every exit path below must print exactly one verdict.
set -uo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIAG="${CURSOR_PROJECT_DIR:-$HOME}/logs/cursor-guard-diag.jsonl"
EMITTED=0
STAGE=start

diag() {
  mkdir -p "$(dirname "$DIAG")" 2>/dev/null
  printf '{"ts":"%s","hook":"guard-shell","stage":"%s","detail":"%s","pwd":"%s","project_dir":"%s"}\n' \
    "$(date -Is 2>/dev/null)" "$STAGE" "${1//\"/\'}" "$PWD" "${CURSOR_PROJECT_DIR:-UNSET}" >> "$DIAG" 2>/dev/null || true
}

# Last-resort verdict. Anything unexpected degrades to a prompt, never to silence
# and never to a silent allow.
on_exit() {
  local rc=$?
  [[ "$EMITTED" -eq 1 ]] && return 0
  # Hand-built JSON: jq may be the thing that failed. Interpolated values are
  # bare words by construction, so no escaping is required.
  printf '{"permission":"ask","user_message":"GUARD HOOK FAULT — guard-shell.sh exited rc=%s at stage %s without reaching a verdict. Approve manually only if you recognise the command. Diagnostics: logs/cursor-guard-diag.jsonl","agent_message":"The shell guard failed internally and fell back to manual approval. Report this fault; do not rephrase the command to work around it."}\n' "${rc//[^0-9]/}" "${STAGE//[^a-z]/}"
  diag "fault-fallback rc=$rc"
}
trap on_exit EXIT
trap 'exit 143' TERM INT

emit() {
  EMITTED=1
  jq -nc --arg p "$1" --arg u "$2" --arg a "$3" \
    '{continue:true, permission:$p, user_message:$u, agent_message:$a}' \
    || printf '{"permission":"ask","user_message":"GUARD HOOK FAULT — verdict %s could not be encoded (jq unavailable). Approve manually.","agent_message":"jq is missing or failed inside the shell guard."}\n' "$1"
  exit 0
}

allow() { EMITTED=1; printf '{"permission":"allow"}\n'; exit 0; }

STAGE=deps
command -v jq >/dev/null 2>&1 || { diag "jq not on PATH"; emit ask \
  "GUARD DEGRADED — jq is not on PATH inside the hook, so commands cannot be classified. Approve manually." \
  "The guard cannot classify this command. Treat every scope as unapproved."; }

STAGE=lib
# shellcheck source=/dev/null
source "$HERE/guard-lib.sh" || { diag "guard-lib.sh failed to source"; emit ask \
  "GUARD DEGRADED — guard-lib.sh could not be loaded, so commands cannot be classified. Approve manually." \
  "The guard classifier is unavailable. Treat every scope as unapproved."; }

# Bounded read: Cursor holding stdin open must not stall the hook into its
# configured timeout, which is what produces a silent lockout.
STAGE=stdin
input=$(timeout 5 cat) || true
if [[ -z "$input" ]]; then
  diag "empty or timed-out stdin"
  emit ask "GUARD DEGRADED — the hook received no command payload within 5s. Approve manually." \
           "The guard could not read the command. Do not assume it was allowed."
fi

STAGE=classify
cmd=$(printf '%s' "$input" | jq -r '.command // empty')
if [[ -z "$cmd" ]]; then
  diag "payload carried no .command field"
  emit ask "GUARD DEGRADED — the hook payload contained no command to classify. Approve manually." \
           "The guard could not read the command. Do not assume it was allowed."
fi
tier=$(classify_cmd "$cmd")

STAGE=verdict
case "$tier" in
  secret) emit deny "BLOCKED — secret access. All secrets live in Bitwarden; nothing credential-shaped is read from or written to this machine by an agent." \
                    "Read configuration shape from .env.example. Never print, copy, or transmit credential values, and never create credential files." ;;
  gate)   emit deny "BLOCKED — gate/interlock modification. These are audit records of the paper-trading history, not fixtures." \
                    "The four live-trading gates and the Schwab interlock are never edited by an agent. If data disagrees with code, report it; do not reconcile it." ;;
  none)   allow ;;
esac

STAGE=grant
if ledger_is_corrupt; then
  emit deny "BLOCKED — APPROVAL_LEDGER_CORRUPT ($(ledger_state)). Guarded command refused." \
            "The approval ledger is corrupt. The operator must recover it; do not treat this as authorized."
fi
grant_consume "$tier"
_gc=$?
if [[ "$_gc" -eq 2 ]]; then
  emit deny "BLOCKED — APPROVAL_LEDGER_CORRUPT. Guarded command refused." \
            "The approval ledger is corrupt. The operator must recover it."
fi
if [[ "$_gc" -eq 0 ]]; then
  left=$(printf '%s' "${GRANT_CONSUME_JSON:-{}}" | jq -r '.uses_left // 0')
  reason=$(printf '%s' "${GRANT_CONSUME_JSON:-{}}" | jq -r '.reason // "—"')
  audit_line "$(jq -nc --arg ts "$(date -Is)" --arg t "$tier" --arg c "$cmd" --arg r "$reason" '{ts:$ts, event:"auto-accepted", tier:$t, command:$c, grant_reason:$r}')"
  emit allow "AUTO-ACCEPTED [$tier] under approved plan: $reason  (uses left: $left)" "This ran under a scope you already approved. Stay inside it."
fi

# Deny rather than ask: an "ask" verdict does not gate an agent session, so a
# guarded scope is only genuinely controlled when the ledger is the gate.
STAGE=denied
emit deny "BLOCKED — scope: $tier  (no active grant)

COMMAND:
  $cmd

WHAT THIS SCOPE COVERS:
  $(tier_scope "$tier")

TO ALLOW IT, in a terminal on ms01:
  bin/guard grant $tier --for 30m --uses 10 --reason \"...\"
then ask the agent to retry. Auto-expires; revoke: bin/guard revoke $tier" \
"Blocked for want of a grant in scope '$tier'. Tell the operator exactly what you intend to change, why, and how to reverse it, then wait. Do not rephrase the command to fall into a different scope."

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
# AGENTS.md 21.0.0 §28.15 item 8 (a): the ONLY grant-free push is "bin/agent-push <branch>" — one strict argument,
# the invoked wrapper byte-identical to this guard tree's bin/agent-push, and this tree's guard_push_free.py check
# passing (policy, canonical remote, fast-forward, approved plan, budget, broker paths). A raw git push, or any other
# agent-push form, falls through to the grant path below, unchanged. The wrapper re-checks and pushes itself.
GRANT_FREE_REASON=""
_ap_re='^[[:space:]]*(([A-Za-z0-9._/-]*/)?bin/agent-push)[[:space:]]+([a-z][a-z0-9-]{1,19}/[A-Za-z0-9][A-Za-z0-9._-]{2,120})[[:space:]]*$'
if [[ "$tier" == "git-push" && "$cmd" =~ $_ap_re ]]; then
  STAGE=grantfree
  _w="${BASH_REMATCH[1]}"; _b="${BASH_REMATCH[3]}"
  _cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)
  [[ "$_w" == /* ]] || _w="${_cwd:+$_cwd/}$_w"
  _trusted="$(cd "$HERE/../.." 2>/dev/null && pwd)/bin/agent-push"
  if [[ "$_w" != /* ]]; then
    GRANT_FREE_REASON="the hook payload carried no cwd to resolve $_w"
  elif ! cmp -s -- "$_w" "$_trusted"; then
    GRANT_FREE_REASON="$_w is not byte-identical to the guard tree's bin/agent-push"
  elif ! _top=$(env -i PATH=/usr/bin:/bin /usr/bin/git -C "$(dirname "$_w")" rev-parse --show-toplevel 2>/dev/null); then
    GRANT_FREE_REASON="$_w is not inside a git work tree"
  else
    _home=$(getent passwd "$(id -u)" | cut -d: -f6)
    _gf=$(timeout "${GUARD_PUSH_FREE_TIMEOUT:-8}" env -i PATH=/usr/bin:/bin HOME="$_home" LANG=C.UTF-8 \
          /usr/bin/python3 -I "$HERE/guard_push_free.py" check --repo "$_top" --branch "$_b" 2>/dev/null | tail -1)
    if [[ "$(printf '%s' "$_gf" | jq -r '.allow // false' 2>/dev/null)" == "true" ]]; then
      _r=$(printf '%s' "$_gf" | jq -r '.approval_ref')
      emit allow "GRANT-FREE PUSH admitted: $_b under $_r (AGENTS.md §28.15 item 8). bin/agent-push re-checks, pushes and records it." \
        "Grant-free fast-forward push of your approved feature branch. Never force, never main/release/train; raw git push still needs a grant."
    fi
    GRANT_FREE_REASON=$(printf '%s' "$_gf" | jq -r '.reason // empty' 2>/dev/null)
    [[ -n "$GRANT_FREE_REASON" ]] || GRANT_FREE_REASON="checker failed or timed out"
  fi
  STAGE=grant
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
"Blocked for want of a grant in scope '$tier'.${GRANT_FREE_REASON:+ Grant-free push (AGENTS.md §28.15 item 8) refused: $GRANT_FREE_REASON.} Tell the operator exactly what you intend to change, why, and how to reverse it, then wait. Do not rephrase the command to fall into a different scope."

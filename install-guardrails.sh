#!/usr/bin/env bash
# install-guardrails.sh — writes the Cursor guardrail bundle into the CURRENT
# git worktree, then self-tests it. Safe to re-run; overwrites its own files only.
#
#   scp install-guardrails.sh ms01:/home/johnclaw/tradeai-wt-cursor-guardrails/
#   ssh ms01
#   cd /home/johnclaw/tradeai-wt-cursor-guardrails && bash install-guardrails.sh
set -uo pipefail

PRIMARY="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "✗ not a git repo — cd into your worktree first"; exit 1; }

if [[ "$ROOT" == "$PRIMARY" ]]; then
  echo "✗ REFUSING TO RUN IN THE PRIMARY TREE."
  echo "  $PRIMARY is live (api_v2.py + reports_portal.py hot-reload from it) and shared."
  echo "  Create a worktree first:  $PRIMARY/scripts/new-worktree.sh cursor-guardrails"
  exit 1
fi

echo "→ installing into: $ROOT"
cd "$ROOT" || exit 1
mkdir -p .cursor/hooks .cursor/approvals bin logs

command -v jq >/dev/null || { echo "→ installing jq"; sudo apt-get install -y jq || { echo "✗ jq required"; exit 1; }; }

# ─────────────────────────────────────────────────────── canonical bundle
# 2026-10-21 (operator): guard-lib.sh is installed ONLY from the repository's canonical file. This
# script used to write its own embedded guard-lib.sh -- an old, non-transactional snapshot (wrong
# GUARD_DIR, jq-redirect grant writes) -- and, when run inside a checkout, it overwrote the tracked
# canonical hooks with its heredocs before the overlay below could copy them back. The canonical
# files are now snapshotted BEFORE anything is written, and the overlay installs the snapshot. With
# no canonical guard-lib.sh (installer copied somewhere on its own) it refuses rather than install
# an embedded one.
_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_canon() { local c; for c in "$_SRC/$1" "$ROOT/$1"; do [[ -f "$c" ]] && { printf '%s\n' "$c"; return 0; }; done; return 1; }
if ! _CANON_LIB="$(_canon .cursor/hooks/guard-lib.sh)"; then
  echo "✗ REFUSING: no canonical .cursor/hooks/guard-lib.sh next to this installer ($_SRC) or in $ROOT."
  echo "  Run it from a checkout of the repository; it never installs an embedded guard-lib.sh."
  exit 1
fi
_CANON_DIR="$(mktemp -d "${TMPDIR:-/tmp}/guardrails-canon.XXXXXX")"
for _f in .cursor/hooks/guard-lib.sh .cursor/hooks/guard_ledger.py .cursor/hooks/guard-read.sh \
          .cursor/hooks/guard-write.sh .cursor/hooks/guard-shell.sh .cursor/hooks/audit.sh \
          .cursor/hooks.json bin/guard; do
  if _c="$(_canon "$_f")"; then
    mkdir -p "$_CANON_DIR/$(dirname "$_f")" && cp -a "$_c" "$_CANON_DIR/$_f"
  fi
done
echo "→ canonical guard-lib.sh: $_CANON_LIB (sha256 $(sha256sum "$_CANON_DIR/.cursor/hooks/guard-lib.sh" | cut -c1-12))"

# ─────────────────────────────────────────────────────── guard-shell.sh
cat > .cursor/hooks/guard-shell.sh <<'SHEOF'
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
SHEOF

# ─────────────────────────────────────────────────────── guard-read.sh
cat > .cursor/hooks/guard-read.sh <<'RDEOF'
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
RDEOF

# ─────────────────────────────────────────────────────── guard-write.sh
cat > .cursor/hooks/guard-write.sh <<'WREOF'
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
WREOF

# ─────────────────────────────────────────────────────── audit.sh
cat > .cursor/hooks/audit.sh <<'AUEOF'
#!/usr/bin/env bash
set -uo pipefail
LOG="${CURSOR_PROJECT_DIR:-.}/logs/cursor-agent-audit.jsonl"
mkdir -p "$(dirname "$LOG")" 2>/dev/null
jq -nc --argjson ev "$(cat)" --arg ts "$(date -Is)" '{ts:$ts} + $ev' >> "$LOG" 2>/dev/null
exit 0
AUEOF

# ─────────────────────────────────────────────────────── hooks.json
cat > .cursor/hooks.json <<'HKEOF'
{
  "version": 1,
  "hooks": {
    "beforeShellExecution": [
      { "command": ".cursor/hooks/guard-shell.sh", "failClosed": true, "timeout": 10 },
      { "command": ".cursor/hooks/audit.sh" }
    ],
    "beforeReadFile": [
      { "command": ".cursor/hooks/guard-read.sh", "failClosed": true }
    ],
    "preToolUse": [
      { "command": ".cursor/hooks/guard-write.sh", "matcher": "Write|Delete|StrReplace|Edit|MultiEdit|EditNotebook", "failClosed": true }
    ],
    "afterShellExecution": [ { "command": ".cursor/hooks/audit.sh" } ],
    "afterFileEdit":       [ { "command": ".cursor/hooks/audit.sh" } ]
  }
}
HKEOF

# ─────────────────────────────────────────────────────── .cursorignore
cat > .cursorignore <<'CIEOF'
.env
.env.*
!.env.example
*.pem
*.key
*.pgpass
data/portfolios/state/
logs/*.log
worktrees/
wt-*/
apps/command-center-v3/dist.old-*/
.cursor/approvals/
CIEOF

# Overlay the canonical bundle snapshotted at the top. The heredocs above are the last
# non-transactional snapshot and only stand in for a file the repository does not have; they
# never win over a canonical file, and guard-lib.sh has no heredoc at all.
( cd "$_CANON_DIR" && find . -type f ) | while read -r _f; do
  _f="${_f#./}"
  mkdir -p "$ROOT/$(dirname "$_f")"
  cp -a "$_CANON_DIR/$_f" "$ROOT/$_f"
done
cmp -s "$_CANON_DIR/.cursor/hooks/guard-lib.sh" "$ROOT/.cursor/hooks/guard-lib.sh" \
  || { echo "✗ installed guard-lib.sh differs from the canonical snapshot — refusing to continue"; exit 1; }

# Never truncate grants.json with shell redirection. Prefer the transactional
# writer; fall back to leaving a missing ledger for first `guard` init.
if [[ -f .cursor/hooks/guard_ledger.py ]]; then
  GUARD_APPROVALS_DIR="$(pwd)/.cursor/approvals" python3 .cursor/hooks/guard_ledger.py init >/dev/null || true
fi
grep -q '^\.cursor/approvals/' .gitignore 2>/dev/null || echo '.cursor/approvals/' >> .gitignore
grep -q '^logs/cursor-agent-audit' .gitignore 2>/dev/null || echo 'logs/cursor-agent-audit.jsonl' >> .gitignore
# bin/guard is written separately — see install-guard-cli.sh, or copy from the bundle.
chmod +x .cursor/hooks/*.sh .cursor/hooks/guard_ledger.py bin/guard 2>/dev/null
sed -i 's/\r$//' .cursor/hooks/*.sh 2>/dev/null

# ─────────────────────────────────────────────────────── SELF-TEST
echo
echo "══ SELF-TEST ══"
export CURSOR_PROJECT_DIR="$ROOT"
pass=0; fail=0
chk() { # $1 hook  $2 json  $3 expected
  local got; got=$(printf '%s' "$2" | ".cursor/hooks/$1" | jq -r '.permission')
  if [[ "$got" == "$3" ]]; then printf '  ✅ %-6s %s\n' "$got" "${4:-}"; pass=$((pass+1));
  else printf '  ❌ got %-6s want %-6s  %s\n' "$got" "$3" "${4:-}"; fail=$((fail+1)); fi
}
chk guard-shell.sh '{"command":"cat .env"}'                                        deny  "read .env"
chk guard-shell.sh '{"command":"psql -c \"UPDATE gate_status SET win_rate=0.6\""}' deny  "gate edit"
chk guard-shell.sh '{"command":"crontab -r"}'                                      ask   "crontab"
chk guard-shell.sh '{"command":"git push -u origin wt/x"}'                         ask   "git push"
chk guard-shell.sh '{"command":"ALLOW_MAINTREE_GIT=1 git checkout -b y"}'          ask   "maintree bypass"
chk guard-shell.sh '{"command":"psql -c \"UPDATE holdings SET shares=1\""}'        ask   "db write"
chk guard-shell.sh '{"command":"openclaw skill install foo"}'                      ask   "openclaw"
chk guard-shell.sh '{"command":"curl https://api.telegram.org/bot1/send"}'          ask   "telegram"
chk guard-shell.sh '{"command":"git status"}'                                      allow "git status"
chk guard-shell.sh '{"command":"psql -c \"SELECT 1\""}'                            allow "select"
chk guard-read.sh  '{"file_path":"'"$ROOT"'/.env"}'                                deny  "read .env file"
chk guard-read.sh  '{"file_path":"scripts/api_v2.py"}'                             allow "read source"
chk guard-write.sh '{"tool_name":"Write","tool_input":{"path":"/home/johnclaw/trade-ai-releases/x/scripts/a.py"}}' ask   "release write"
chk guard-write.sh '{"tool_name":"Write","tool_input":{"path":"data/portfolios/state/holdings.json"}}'             ask   "state write"
chk guard-write.sh '{"tool_name":"Write","tool_input":{"path":".env"}}'                                           deny  "write .env"
chk guard-write.sh '{"tool_name":"Write","tool_input":{"path":"scripts/api_v2.py"}}'                              allow "write source"
echo
echo "  PASS: $pass   FAIL: $fail"
[[ $fail -eq 0 ]] && echo "  ✅ guardrails installed and verified in $ROOT" || echo "  ❌ fix failures before using"
echo
echo "Next:"
echo "  1. copy bin/guard into $ROOT/bin/ and chmod +x"
echo "  2. bin/guard scopes            # see every grantable scope"
echo "  3. git add -A && git commit -m 'ops: cursor guardrails'"
echo "  4. open $ROOT in Cursor Remote-SSH, reload window, check Settings → Hooks"

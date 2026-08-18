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

# ─────────────────────────────────────────────────────── guard-lib.sh
cat > .cursor/hooks/guard-lib.sh <<'LIBEOF'
#!/usr/bin/env bash
# Shared classifier + approval ledger.
GUARD_DIR="${CURSOR_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}/.cursor/approvals"
GRANTS="$GUARD_DIR/grants.json"
AUDIT="${CURSOR_PROJECT_DIR:-.}/logs/cursor-agent-audit.jsonl"

tier_scope() {
  case "$1" in
    db-write)      echo "Any INSERT / UPDATE / DELETE / ALTER / CREATE / TRUNCATE against the trade_ai database (669 tables). Gate and interlock tables remain blocked regardless." ;;
    cron)          echo "Any crontab read/replace/remove. ~190 entries, no version history, no undo." ;;
    git-push)      echo "git push, force-push, reset --hard, rebase, filter-branch — operations touching the remote or rewriting history." ;;
    maintree)      echo "ALLOW_MAINTREE_GIT bypass: git operations in the PRIMARY tree, which is LIVE (api_v2.py + reports_portal.py hot-reload) and shared with Claude/Codex sessions." ;;
    service)       echo "systemctl/service start, stop, restart, reload on tradeai-continuous, tradeai-portfolio-server, Hermes, or OpenClaw." ;;
    deps)          echo "pip/npm/apt install, remove, upgrade — changes the runtime environment." ;;
    sudo)          echo "Any command run as root." ;;
    state-write)   echo "Writes to data/portfolios/state/ — live holdings, risk_management, personal_situation." ;;
    release-write) echo "Writes to ~/trade-ai-releases/ or ~/trade-ai-deployments/ — immutable artifacts that are CURRENTLY RUNNING." ;;
    openclaw)      echo "OpenClaw gateway and ClawHub skill operations. Skills inherit full disk/terminal/network permissions." ;;
    telegram)      echo "Real Telegram sends — these reach your phone." ;;
    llm)           echo "Paid LLM API calls — counts against the \$2/day budget gate." ;;
    destructive)   echo "Recursive deletes (rm -r / rm -rf)." ;;
    config-write)  echo "Edits to config/*.yaml or assets/*.yaml — drives runtime behaviour and syncs to the DB." ;;
    frozen-v2)     echo "Edits under command-center-v2 / v2 paths. v2 is frozen; v3 is canonical." ;;
    guard-config)  echo "Edits to .cursor/hooks/* or .cursor/*.json — the guardrails themselves." ;;
    file-delete)   echo "Deleting files." ;;
    *)             echo "Unknown tier: $1" ;;
  esac
}

classify_cmd() {
  local cmd="$1" U; U="${cmd^^}"
  [[ "$cmd" =~ (cat|less|more|head|tail|strings|grep|awk|sed|cp|scp|rsync|base64|xxd|env|printenv|source|\.)[[:space:]].*\.env ]] && { echo secret; return; }
  [[ "$cmd" =~ (id_ed25519|id_rsa|authorized_keys|\.ssh/|\.pgpass|credentials) ]] && { echo secret; return; }
  [[ "$cmd" =~ (\>|\>\>|tee)[^|]*(\.env|\.pem|\.key|credentials|\.pgpass) ]] && { echo secret; return; }
  [[ "$cmd" =~ (API_KEY|SECRET|TOKEN|PASSWORD|COOKIE)= ]] && [[ "$cmd" =~ (\>|\>\>|tee) ]] && { echo secret; return; }
  [[ "$cmd" =~ (win_rate|profit_factor|closed_trades|interlock|gate_status) ]] && \
    { [[ "$U" =~ (UPDATE|DELETE|INSERT) ]] || [[ "$cmd" =~ (sed[[:space:]]+-i|tee|\>) ]]; } && { echo gate; return; }
  [[ "$cmd" =~ ALLOW_MAINTREE_GIT ]] && { echo maintree; return; }
  [[ "$cmd" =~ (^|[[:space:];&|])crontab([[:space:]]|$) ]] && { echo cron; return; }
  [[ "$cmd" =~ git[[:space:]]+(push|reset[[:space:]]+--hard|rebase|filter-branch) ]] && { echo git-push; return; }
  [[ "$cmd" =~ (psql|psycopg2|sqlalchemy|pg_restore) ]] && [[ "$U" =~ (INSERT|UPDATE|DELETE|ALTER|CREATE|TRUNCATE|GRANT|REVOKE) ]] && { echo db-write; return; }
  [[ "$cmd" =~ (openclaw|clawhub) ]] && { echo openclaw; return; }
  [[ "$cmd" =~ api\.telegram\.org ]] && { echo telegram; return; }
  [[ "$cmd" =~ (api\.anthropic\.com|api\.openai\.com|api\.x\.ai) ]] && { echo llm; return; }
  [[ "$cmd" =~ ^sudo ]] && { echo sudo; return; }
  [[ "$cmd" =~ (systemctl|service)[[:space:]]+(restart|stop|start|reload) ]] && { echo service; return; }
  [[ "$cmd" =~ (pip|pip3|npm|apt|apt-get)[[:space:]]+(install|uninstall|remove|upgrade) ]] && { echo deps; return; }
  [[ "$cmd" =~ (trade-ai-releases|trade-ai-deployments) ]] && [[ "$cmd" =~ (\>|\>\>|tee|mv|cp|rm|sed[[:space:]]+-i) ]] && { echo release-write; return; }
  [[ "$cmd" =~ (\>|\>\>|tee|mv|cp|rm|sed[[:space:]]+-i).*data/portfolios/state ]] && { echo state-write; return; }
  [[ "$cmd" =~ rm[[:space:]]+-[a-zA-Z]*[rf] ]] && { echo destructive; return; }
  echo none
}

classify_path() {
  local p="$1" tool="${2:-Write}"
  p="${p#./}"                       # strip leading ./
  [[ "$p" == /* ]] || p="/$p"       # normalise relative paths so */x/* globs match
  case "$p" in
    *.env|*/.env|*.env.*|*.pem|*.key|*credentials*|*.pgpass|*id_ed25519*|*id_rsa*) echo secret; return ;;
    *gate_status*|*interlock*) echo gate; return ;;
    */trade-ai-releases/*|*/trade-ai-deployments/*) echo release-write; return ;;
    */data/portfolios/state/*) echo state-write; return ;;
    */ops/cron/*) echo cron; return ;;
    */config/*.yaml|*/assets/*.yaml) echo config-write; return ;;
    */v2/*|*command-center-v2*) echo frozen-v2; return ;;
    */.openclaw/*) echo openclaw; return ;;
    */.cursor/hooks/*|*/.cursor/*.json) echo guard-config; return ;;
  esac
  [[ "$tool" == "Delete" ]] && { echo file-delete; return; }
  echo none
}

now() { date +%s; }
grant_active() {
  [[ -f "$GRANTS" ]] || return 1
  local exp uses
  exp=$(jq -r --arg t "$1" '.[$t].expires // 0' "$GRANTS" 2>/dev/null) || return 1
  uses=$(jq -r --arg t "$1" '.[$t].uses // 0' "$GRANTS" 2>/dev/null)
  [[ "$exp" -gt "$(now)" ]] || return 1
  [[ "$uses" -lt 0 || "$uses" -gt 0 ]] || return 1
  return 0
}
grant_consume() {
  [[ -f "$GRANTS" ]] || return 0
  local tmp; tmp=$(mktemp)
  jq --arg t "$1" 'if (.[$t].uses // 0) > 0 then .[$t].uses -= 1 else . end' "$GRANTS" > "$tmp" 2>/dev/null && mv "$tmp" "$GRANTS" || rm -f "$tmp"
}
grant_reason() { jq -r --arg t "$1" '.[$t].reason // "—"' "$GRANTS" 2>/dev/null; }
grant_left()   { jq -r --arg t "$1" '.[$t].uses // 0'      "$GRANTS" 2>/dev/null; }
grant_expires(){ jq -r --arg t "$1" '.[$t].expires // 0'   "$GRANTS" 2>/dev/null; }
audit_line()   { mkdir -p "$(dirname "$AUDIT")" 2>/dev/null; printf '%s\n' "$1" >> "$AUDIT" 2>/dev/null || true; }
LIBEOF

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

# Never truncate grants.json with shell redirection. Prefer the transactional
# writer; fall back to leaving a missing ledger for first `guard` init.
if [[ -f .cursor/hooks/guard_ledger.py ]]; then
  GUARD_APPROVALS_DIR="$(pwd)/.cursor/approvals" python3 .cursor/hooks/guard_ledger.py init >/dev/null || true
fi
grep -q '^\.cursor/approvals/' .gitignore 2>/dev/null || echo '.cursor/approvals/' >> .gitignore
grep -q '^logs/cursor-agent-audit' .gitignore 2>/dev/null || echo 'logs/cursor-agent-audit.jsonl' >> .gitignore

# Overlay the transactional ledger bundle if this installer lives next to it.
# Heredocs above are the last non-transactional snapshot; they must not win.
_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$_SRC/.cursor/hooks/guard_ledger.py" ]]; then
  cp -a "$_SRC/.cursor/hooks/guard_ledger.py" "$ROOT/.cursor/hooks/"
  cp -a "$_SRC/.cursor/hooks/guard-lib.sh" "$_SRC/.cursor/hooks/guard-read.sh" \
        "$_SRC/.cursor/hooks/guard-write.sh" "$_SRC/.cursor/hooks/guard-shell.sh" \
        "$_SRC/.cursor/hooks/audit.sh" "$ROOT/.cursor/hooks/"
  [[ -f "$_SRC/bin/guard" ]] && cp -a "$_SRC/bin/guard" "$ROOT/bin/guard"
  [[ -f "$_SRC/.cursor/hooks.json" ]] && cp -a "$_SRC/.cursor/hooks.json" "$ROOT/.cursor/hooks.json"
fi
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

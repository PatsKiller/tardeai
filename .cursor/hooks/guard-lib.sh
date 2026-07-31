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

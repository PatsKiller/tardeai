#!/usr/bin/env bash
# Shared classifier + approval ledger.
# One ledger per host, at a fixed absolute path. Deliberately not derived from
# CWD, the git toplevel, or CURSOR_PROJECT_DIR: the hooks run from the workspace
# root while bin/guard runs from inside the guardrails worktree, and a grant
# issued by one must be visible to the other.
GUARD_DIR="${GUARD_APPROVALS_DIR:-$HOME/.cursor/approvals}"
GRANTS="$GUARD_DIR/grants.json"
AUDIT="${GUARD_AUDIT_LOG:-$HOME/logs/cursor-agent-audit.jsonl}"

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
    execution-ops) echo "Per-incident operation of a broker-execution user unit (tradeai-active-trader-*), naming the unit in the reason: status/journal, code-root drop-in to portfolio-server/CURRENT, daemon-reload, restart; markets CLOSED, preflight, rollback by restoring the archived drop-in; max 6h. Never code, credentials, live/paper flags, orders or stops (AGENTS.md 5.0.0 §24.10)." ;;
    execution-engineering) echo "Per-task A1/A2 work on broker-adjacent code (scripts/active_trader/**, scripts/brokers/**, trading_session_grant.py): mocks, fixtures, simulated broker, replay. Never live credentials, endpoints, 2FA, live flags or orders (AGENTS.md 1.3.0 §22)." ;;
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
  # The ledger is now the only thing standing between the agent and every
  # guarded scope, so the agent must not be able to issue itself a grant.
  # Operator grants come from a real terminal, which never passes through this
  # hook. Reading the ledger (show/scopes/log) and tightening it (revoke) stay
  # unguarded; only widening it is blocked.
  [[ "$cmd" =~ (^|[[:space:];&|/])guard[[:space:]]+(grant|plan)([[:space:]]|$) ]] && { echo approvals; return; }
  [[ "$cmd" =~ (\>|\>\>|tee|sed[[:space:]]+-i|mv|cp|rm|truncate|install|dd)[^|]*\.cursor/approvals ]] && { echo approvals; return; }
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
  # AGENTS.md 5.0.0 §24.10: restart / daemon-reload of a broker-execution unit, and writes or renames under its
  # drop-in directory, need a per-incident execution-ops grant, never a plain service grant. After sudo, so root
  # stays sudo. A command that also uses another mutating verb, or names another production unit, is not
  # execution-ops (it falls through to service). rm of a drop-in is destructive (§0 rule 6: archive by mv).
  if [[ "$cmd" =~ (^|[[:space:];&|])systemctl[[:space:]] ]] && [[ "$cmd" =~ tradeai-active-trader- ]] && \
     [[ "$cmd" =~ [[:space:]](restart|try-restart|daemon-reload)([[:space:]]|$) ]]; then
    local _eo_rest="${cmd//tradeai-active-trader-/}"
    if ! [[ "$cmd" =~ [[:space:]](start|stop|kill|mask|unmask|enable|disable|reenable|edit|revert|set-property|reload|isolate)([[:space:]]|$) ]] && \
       ! [[ "$_eo_rest" =~ (tradeai-|trade-ai-|portfolio-|hermes-|openclaw-|aegis-|cio-|heartbeat-|n8n|m8m|postgresql|docker|\*) ]]; then
      echo execution-ops; return
    fi
  fi
  [[ "$cmd" =~ (^|[[:space:];&|])rm[[:space:]].*\.config/systemd/user/tradeai-active-trader- ]] && { echo destructive; return; }
  [[ "$cmd" =~ \.config/systemd/user/tradeai-active-trader- ]] && \
    [[ "$cmd" =~ (\>|\>\>|tee|mv|cp|install|ln|touch|sed[[:space:]]+-i) ]] && { echo execution-ops; return; }
  # Verb may be separated from systemctl by any number of flags (--user, -M host,
  # --now). 45 of 48 tradeai units are user units, so the --user form is the one
  # that actually matters here. Over-classifying a read-only subcommand is safe;
  # under-classifying a restart is not.
  [[ "$cmd" =~ (^|[[:space:];&|])systemctl[[:space:]] ]] && \
    [[ "$cmd" =~ [[:space:]](start|stop|restart|reload|kill|mask|unmask|enable|disable|daemon-reload)([[:space:]]|$) ]] && \
    { echo service; return; }
  [[ "$cmd" =~ (^|[[:space:];&|])service[[:space:]]+[^[:space:]]+[[:space:]]+(start|stop|restart|reload) ]] && { echo service; return; }
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
    */.config/systemd/user/tradeai-active-trader-*) [[ "$tool" == "Delete" ]] && { echo file-delete; return; }; echo execution-ops; return ;;
    */.cursor/hooks/*|*/.cursor/*.json) echo guard-config; return ;;
  esac
  [[ "$tool" == "Delete" ]] && { echo file-delete; return; }
  echo none
}

_GUARD_HOOKS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_LEDGER_PY="$_GUARD_HOOKS/guard_ledger.py"
_ledger() { python3 "$_LEDGER_PY" "$@"; }

now() { date +%s; }

ledger_state() {
  _ledger state 2>/dev/null | jq -r '.state // "UNREADABLE"'
}

ledger_is_corrupt() {
  case "$(ledger_state)" in
    ZERO_BYTE|MALFORMED|UNREADABLE) return 0 ;;
    *) return 1 ;;
  esac
}

# Single consume transaction: check+decrement under exclusive lock.
# rc 0 consumed, 2 APPROVAL_LEDGER_CORRUPT, 3 no grant, 1 other.
grant_consume() {
  local out rc
  out=$(_ledger consume --tier "$1" 2>/dev/null) || rc=$?
  rc=${rc:-0}
  # Last JSON object only — ignore any stray lines.
  GRANT_CONSUME_JSON=$(printf '%s\n' "$out" | awk 'BEGIN{s="{}"} /^[[:space:]]*\{/{s=$0} END{print s}')
  return "$rc"
}

grant_active() {
  local out
  out=$(_ledger list 2>/dev/null) || return 1
  echo "$out" | jq -e --arg t "$1" '.active[$t] != null' >/dev/null 2>&1
}

grant_reason() {
  _ledger list 2>/dev/null | jq -r --arg t "$1" '.grants[$t].reason // "—"'
}
grant_left() {
  _ledger list 2>/dev/null | jq -r --arg t "$1" '.grants[$t].uses // 0'
}
grant_expires() {
  _ledger list 2>/dev/null | jq -r --arg t "$1" '.grants[$t].expires // 0'
}

audit_line() {
  # Serialized append via the canonical writer. $1 is a JSON object string.
  _ledger audit --payload "$1" >/dev/null 2>&1 || true
}

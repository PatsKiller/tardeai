#!/usr/bin/env bash
# Wire agent-runtime operator dispatch env into the portfolio-server user unit.
#
# DRY-RUN BY DEFAULT — pass --execute after reviewing output.
# Secrets come from Bitwarden tmpfs only; DSN values are never printed or logged.
#
# Prerequisites (operator, on ms01):
#   * Bitwarden tmpfs: /run/user/$(id -u)/tradeai/env (render_env.py --now)
#   * SHADOW_READER_DSN and SHADOW_DSN present in that file
#   * Kill switch: /etc/tradeai/agent_runtime_enabled
#   * Backend operator routes synced into the live release tree (see DEPLOY_OPERATOR_UX.md)
#
# Usage:
#   ./scripts/agent_runtime/deploy_operator_wiring.sh [--execute]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE="${1:---dry-run}"
[[ "$MODE" == "--execute" || "$MODE" == "--dry-run" ]] || { echo "usage: deploy_operator_wiring.sh [--execute]" >&2; exit 1; }
EXECUTE=0; [[ "$MODE" == "--execute" ]] && EXECUTE=1

RESTART_SERVICE="${RESTART_SERVICE:-portfolio-server.service}"
OPERATOR_ENV_FILE="${OPERATOR_ENV_FILE:-$HOME/.config/tradeai/agent-operator.env}"
DROPIN_DIR="${USER_SYSTEMD_DIR:-$HOME/.config/systemd/user}/${RESTART_SERVICE}.d"
DROPIN_FILE="$DROPIN_DIR/10-agent-read-api.conf"
ENV_TMPFS="/run/user/$(id -u)/tradeai/env"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_ROOT="${A2_BACKUP_ROOT:-$HOME/.local/state/tradeai/operator-wiring}"
BACKUP_DIR="$BACKUP_ROOT/$TS"

die() { echo "[operator-wiring][FATAL] $*" >&2; exit 1; }
note() { echo "[operator-wiring] $*"; }

note "mode=$MODE restart=$RESTART_SERVICE env_file=$OPERATOR_ENV_FILE"

if [[ ! -f "$ENV_TMPFS" ]]; then
  note "tmpfs env missing — run: .venv/bin/python scripts/secrets/render_env.py --now"
  [[ "$EXECUTE" == "1" ]] && die "refusing --execute without $ENV_TMPFS"
fi

if [[ "$EXECUTE" == "1" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_TMPFS"
  set +a
  : "${SHADOW_READER_DSN:?SHADOW_READER_DSN missing from Bitwarden tmpfs}"
  : "${SHADOW_DSN:?SHADOW_DSN missing from Bitwarden tmpfs}"
fi

if [[ ! -f /etc/tradeai/agent_runtime_enabled ]]; then
  note "kill switch missing — run: sudo install -m0644 /dev/null /etc/tradeai/agent_runtime_enabled"
  [[ "$EXECUTE" == "1" ]] && die "refusing --execute without kill switch"
fi

# Pre-flight: readiness route must exist (404 = backend not synced).
if command -v curl >/dev/null 2>&1; then
  code="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:7777/api/v3/agent-runtime/readiness 2>/dev/null || echo 000)"
  if [[ "$code" == "404" ]]; then
    die "readiness HTTP 404 — sync operator backend into live release tree first"
  fi
  note "readiness preflight HTTP $code"
fi

if [[ "$EXECUTE" != "1" ]]; then
  note "DRY-RUN: would write mode-0600 $OPERATOR_ENV_FILE with:"
  note "  AGENT_RUNTIME_READ_API=1"
  note "  AGENT_RUNTIME_READ_DSN=<from SHADOW_READER_DSN>"
  note "  AGENT_RUNTIME_OPERATOR_AUTH=1"
  note "  AGENT_RUNTIME_DISPATCH_DSN=<from SHADOW_DSN>"
  note "  AGENT_RUNTIME_QUEUE_MODULE=agent_runtime_dispatch_boot"
  note "  AGENT_RUNTIME_PROVIDER_MODULE=agent_runtime.providers.shadow_fleet_provider"
  note "  AGENT_RUNTIME_SOURCE_DSN=<from SHADOW_READER_DSN>"
  note "DRY-RUN: would install drop-in $DROPIN_FILE -> EnvironmentFile=$OPERATOR_ENV_FILE"
  note "DRY-RUN: would systemctl --user daemon-reload && restart $RESTART_SERVICE"
  note "DRY-RUN: would smoke readiness dispatch.state=WIRED and POST /dispatch"
  exit 0
fi

mkdir -p "$BACKUP_DIR" "$(dirname "$OPERATOR_ENV_FILE")" "$DROPIN_DIR"
[[ -f "$OPERATOR_ENV_FILE" ]] && cp -a "$OPERATOR_ENV_FILE" "$BACKUP_DIR/agent-operator.env.bak"
[[ -f "$DROPIN_FILE" ]] && cp -a "$DROPIN_FILE" "$BACKUP_DIR/10-agent-read-api.conf.bak"

umask 077
cat > "$OPERATOR_ENV_FILE" <<EOF
AGENT_RUNTIME_READ_API=1
AGENT_RUNTIME_READ_DSN=${SHADOW_READER_DSN}
AGENT_RUNTIME_OPERATOR_AUTH=1
AGENT_RUNTIME_DISPATCH_DSN=${SHADOW_DSN}
AGENT_RUNTIME_QUEUE_MODULE=agent_runtime_dispatch_boot
AGENT_RUNTIME_PROVIDER_MODULE=agent_runtime.providers.shadow_fleet_provider
AGENT_RUNTIME_SOURCE_DSN=${SHADOW_READER_DSN}
EOF
chmod 600 "$OPERATOR_ENV_FILE"
note "wrote $OPERATOR_ENV_FILE (mode 0600, DSN redacted)"

printf '[Service]\nEnvironmentFile=%s\n' "$OPERATOR_ENV_FILE" > "$DROPIN_FILE"
note "installed drop-in $DROPIN_FILE"

systemctl --user daemon-reload
systemctl --user restart "$RESTART_SERVICE"
note "restarted $RESTART_SERVICE"

_wait() {
  local url="$1" want="$2" tries="${3:-30}" i code
  for i in $(seq 1 "$tries"); do
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 "$url" 2>/dev/null || echo 000)"
    [[ "$code" == "$want" ]] && { echo "$code"; return 0; }
    sleep 1
  done
  echo "$code"
  return 1
}

code="$(_wait http://127.0.0.1:7777/api/v3/agent-runtime/readiness 200 45 || true)"
[[ "$code" == "200" ]] || die "readiness smoke failed HTTP $code"

dispatch_state="$(curl -sS http://127.0.0.1:7777/api/v3/agent-runtime/readiness | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('wiring',{}).get('dispatch',{}).get('state',''))" 2>/dev/null || true)"
[[ "$dispatch_state" == "WIRED" ]] || die "dispatch not WIRED after restart (state=$dispatch_state)"

note "dispatch state WIRED — operator wiring complete"
note "verify: curl -s -X POST http://127.0.0.1:7777/api/v3/agent-runtime/dispatch -H 'Content-Type: application/json' -d '{\"agent_id\":\"sentinel\",\"max_batch\":1}'"

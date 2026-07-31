#!/usr/bin/env bash
# Sync real governed trigger wiring into the live portfolio-server release tree.
#
# DRY-RUN by default. Pass --execute to copy files, apply migration 0003, and
# refresh operator env for shadow_fleet_provider.
#
# Usage (from repo root):
#   ./scripts/agent_runtime/deploy_real_triggers.sh [--execute]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE="${1:---dry-run}"
[[ "$MODE" == "--execute" || "$MODE" == "--dry-run" ]] || { echo "usage: deploy_real_triggers.sh [--execute]" >&2; exit 1; }
EXECUTE=0; [[ "$MODE" == "--execute" ]] && EXECUTE=1

LIVE_ROOT="${LIVE_RELEASE_ROOT:-}"
if [[ -z "$LIVE_ROOT" ]]; then
  LIVE_ROOT="$(readlink -f /proc/$(pgrep -f 'portfolio_server.py' | head -1)/cwd 2>/dev/null || true)"
fi
if [[ -z "$LIVE_ROOT" || ! -d "$LIVE_ROOT" ]]; then
  LIVE_ROOT="${HOME}/trade-ai-releases/portfolio-server/f31eb17959719074f9dd52cf23f2cfa4b9f414a5-argus-catalog-sync-20260730-161805"
fi

ENV_TMPFS="/run/user/$(id -u)/tradeai/env"
OPERATOR_ENV="${OPERATOR_ENV_FILE:-$HOME/.config/tradeai/agent-operator.env}"

die() { echo "[deploy-triggers][FATAL] $*" >&2; exit 1; }
note() { echo "[deploy-triggers] $*"; }

note "mode=$MODE repo=$REPO_ROOT live=$LIVE_ROOT"

COPY_PATHS=(
  "migrations/agentic_runtime/0003_trigger_intake.up.sql"
  "migrations/agentic_runtime/0003_trigger_intake.down.sql"
  "migrations/agentic_runtime/apply.sh"
  "scripts/agent_runtime/trigger_intake.py"
  "scripts/agent_runtime/trigger_sources.py"
  "scripts/agent_runtime/trigger_producer.py"
  "scripts/agent_runtime/providers/shadow_fleet_provider.py"
  "scripts/agent_runtime/operations.py"
  "scripts/agent_runtime/health_monitor.py"
  "scripts/agent_runtime/install_agent_runtime_schedules.sh"
  "scripts/agent_runtime_dispatch_boot.py"
  "scripts/agent_runtime/agents/dispatcher.py"
  "config/agent_runtime_schedules.json"
  "config/systemd/agent_runtime/tradeai-agent-runtime-producer.service"
  "config/systemd/agent_runtime/tradeai-agent-runtime-producer.timer"
)

if [[ "$EXECUTE" != "1" ]]; then
  note "DRY-RUN: would copy ${#COPY_PATHS[@]} paths + dist/ into $LIVE_ROOT"
  for rel in "${COPY_PATHS[@]}"; do
    note "  cp $REPO_ROOT/$rel -> $LIVE_ROOT/$rel"
  done
  note "DRY-RUN: would rsync $REPO_ROOT/apps/command-center-v3/dist/ -> $LIVE_ROOT/apps/command-center-v3/dist/"
  note "DRY-RUN: would run migrations/agentic_runtime/apply.sh --apply up (needs TRADE_AI_LAB_DSN or SHADOW_DSN)"
  note "DRY-RUN: would patch $OPERATOR_ENV AGENT_RUNTIME_PROVIDER_MODULE=shadow_fleet_provider"
  note "DRY-RUN: run install_agent_runtime_schedules.sh --execute separately after reviewing"
  exit 0
fi

[[ -d "$LIVE_ROOT" ]] || die "live release root not found: $LIVE_ROOT"

for rel in "${COPY_PATHS[@]}"; do
  src="$REPO_ROOT/$rel"
  dst="$LIVE_ROOT/$rel"
  [[ -f "$src" ]] || die "missing source file: $src"
  mkdir -p "$(dirname "$dst")"
  cp -a "$src" "$dst"
  note "copied $rel"
done

mkdir -p "$LIVE_ROOT/apps/command-center-v3/dist"
rsync -a --delete "$REPO_ROOT/apps/command-center-v3/dist/" "$LIVE_ROOT/apps/command-center-v3/dist/"
note "synced Command Center dist/"

chmod +x "$LIVE_ROOT/scripts/agent_runtime/install_agent_runtime_schedules.sh"

if [[ -f "$ENV_TMPFS" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_TMPFS"
  set +a
fi

DSN="${TRADE_AI_LAB_DSN:-${AGENTIC_RUNTIME_MIGRATOR_DSN:-}}"
if [[ -z "$DSN" && -f "$ENV_TMPFS" ]]; then
  set -a; source "$ENV_TMPFS"; set +a
  DSN="${TRADE_AI_LAB_DSN:-${AGENTIC_RUNTIME_MIGRATOR_DSN:-}}"
fi
if [[ -n "$DSN" ]]; then
  note "applying migration 0003_trigger_intake (incremental, requires migrator role)..."
  if psql "$DSN" -Atqc "SELECT to_regclass('agentic_runtime.trigger_intake')" 2>/dev/null | grep -q trigger_intake; then
    note "trigger_intake already exists — skipping 0003"
  elif psql "$DSN" -v ON_ERROR_STOP=1 -f "$LIVE_ROOT/migrations/agentic_runtime/0003_trigger_intake.up.sql"; then
    note "applied 0003_trigger_intake.up.sql"
  else
    note "WARN: 0003 apply failed — run manually with migrator DSN:"
    note "  TRADE_AI_LAB_DSN=<migrator> psql \"\$TRADE_AI_LAB_DSN\" -f $LIVE_ROOT/migrations/agentic_runtime/0003_trigger_intake.up.sql"
  fi
else
  note "WARN: no migrator DSN — skip 0003 (shadow_rw cannot CREATE TABLE)"
fi

if [[ -f "$OPERATOR_ENV" ]]; then
  if grep -q 'AGENT_RUNTIME_PROVIDER_MODULE=' "$OPERATOR_ENV"; then
    sed -i 's|AGENT_RUNTIME_PROVIDER_MODULE=.*|AGENT_RUNTIME_PROVIDER_MODULE=agent_runtime.providers.shadow_fleet_provider|' "$OPERATOR_ENV"
  else
    echo 'AGENT_RUNTIME_PROVIDER_MODULE=agent_runtime.providers.shadow_fleet_provider' >> "$OPERATOR_ENV"
  fi
  if [[ -n "${SHADOW_READER_DSN:-}" ]] && ! grep -q 'AGENT_RUNTIME_SOURCE_DSN=' "$OPERATOR_ENV"; then
    echo "AGENT_RUNTIME_SOURCE_DSN=${SHADOW_READER_DSN}" >> "$OPERATOR_ENV"
  fi
  chmod 600 "$OPERATOR_ENV"
  note "updated $OPERATOR_ENV for shadow_fleet_provider"
fi

systemctl --user restart portfolio-server.service 2>/dev/null && note "restarted portfolio-server.service" || note "restart portfolio-server manually if needed"

note "done. Next: $LIVE_ROOT/scripts/agent_runtime/install_agent_runtime_schedules.sh --execute"

#!/usr/bin/env bash
# install_agent_runtime_schedules.sh — preflight + install differentiated timers.
#
# Loads DSNs from Bitwarden-managed env files only. Backs up existing units and
# supports rollback via --rollback. Does not create /etc/tradeai/agent_runtime_enabled.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="${ROOT}/config/agent_runtime_schedules.json"
SYSTEMD_SRC="${ROOT}/config/systemd/agent_runtime"
BACKUP_ROOT="${HOME}/.local/state/tradeai/agent-runtime-systemd-backup"
USER_SYSTEMD="${HOME}/.config/systemd/user"
DRY_RUN=0
ROLLBACK=0
EXECUTE=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [--execute] [--rollback] [--dry-run]

  --dry-run   Print planned installs only
  --execute   Install producer + per-agent drain timers after preflight
  --rollback  Restore the most recent backup and disable timers
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) EXECUTE=1 ;;
    --rollback) ROLLBACK=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

load_env() {
  local file="$1"
  if [[ -f "$file" ]]; then
    # shellcheck disable=SC1090
    source "$file"
  fi
}

preflight() {
  local failures=0
  if [[ -z "${AGENT_RUNTIME_DISPATCH_DSN:-}" ]]; then
    echo "BLOCKED: AGENT_RUNTIME_DISPATCH_DSN missing" >&2
    failures=$((failures + 1))
  fi
  if [[ -z "${AGENT_RUNTIME_SOURCE_DSN:-}" ]]; then
    echo "WARN: AGENT_RUNTIME_SOURCE_DSN missing — event adapters remain blocked" >&2
  fi
  if [[ ! -f "$MANIFEST" ]]; then
    echo "BLOCKED: schedule manifest missing at $MANIFEST" >&2
    failures=$((failures + 1))
  fi
  return "$failures"
}

install_units() {
  mkdir -p "$USER_SYSTEMD" "$BACKUP_ROOT/$(date -u +%Y%m%dT%H%M%SZ)"
  local stamp
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local backup="${BACKUP_ROOT}/${stamp}"
  mkdir -p "$backup"

  for unit in tradeai-agent-runtime-producer.service tradeai-agent-runtime-producer.timer tradeai-agent-runtime@.service; do
    if [[ -f "${USER_SYSTEMD}/${unit}" ]]; then
      cp "${USER_SYSTEMD}/${unit}" "${backup}/"
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "would install ${SYSTEMD_SRC}/${unit}"
    else
      cp "${SYSTEMD_SRC}/${unit}" "${USER_SYSTEMD}/"
    fi
  done

  python3 - <<'PY' "$MANIFEST" "$SYSTEMD_SRC" "$USER_SYSTEMD" "$DRY_RUN"
import json, sys
from pathlib import Path
manifest = json.loads(Path(sys.argv[1]).read_text())
src = Path(sys.argv[2])
dest = Path(sys.argv[3])
dry = int(sys.argv[4])
base_timer = (src / "tradeai-agent-runtime@.timer").read_text()
for agent_id, cfg in manifest.get("agents", {}).items():
    cal = cfg.get("on_calendar")
    if cal:
        on_calendar = f"OnCalendar={cal}"
    else:
        mins = int(cfg.get("drain_minutes") or 15)
        on_calendar = f"OnCalendar=*:0/{mins}"
    timer = base_timer.replace("OnCalendar=*:0/15", on_calendar)
    path = dest / f"tradeai-agent-runtime@{agent_id}.timer"
    if dry:
        print(f"would write {path} ({on_calendar})")
    else:
        path.write_text(timer)
PY

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "dry-run complete"
    return 0
  fi

  systemctl --user daemon-reload
  systemctl --user enable --now tradeai-agent-runtime-producer.timer
  python3 - <<'PY' "$MANIFEST"
import json, subprocess, sys
manifest = json.loads(open(sys.argv[1]).read_text())
for agent_id in manifest.get("agents", {}):
    subprocess.run(["systemctl", "--user", "enable", "--now", f"tradeai-agent-runtime@{agent_id}.timer"], check=False)
PY
  echo "installed producer + per-agent drain timers"
}

rollback() {
  local latest
  latest="$(ls -1dt "${BACKUP_ROOT}/"* 2>/dev/null | head -1 || true)"
  if [[ -z "$latest" ]]; then
    echo "no backup to restore" >&2
    exit 1
  fi
  cp -a "${latest}/." "${USER_SYSTEMD}/"
  systemctl --user daemon-reload
  systemctl --user disable --now tradeai-agent-runtime-producer.timer || true
  echo "restored backup from ${latest}"
}

load_env "${HOME}/.config/tradeai/agent_runtime.env"
load_env "/run/tradeai/agent_runtime.env"

if [[ "$ROLLBACK" -eq 1 ]]; then
  rollback
  exit 0
fi

if ! preflight; then
  exit 1
fi

if [[ "$EXECUTE" -eq 1 ]]; then
  install_units
else
  echo "prepare-only: pass --execute to install timers (optional --dry-run)"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    install_units
  fi
fi

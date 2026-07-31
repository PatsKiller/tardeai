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
OPERATOR_ENV_FILE="${OPERATOR_ENV_FILE:-$HOME/.config/tradeai/agent-operator.env}"
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

DOW_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def dow_to_systemd(dow: str) -> str | None:
    if dow in ("*", ""):
        return None
    if "-" in dow:
        a, b = dow.split("-", 1)
        return f"{DOW_NAMES[int(a) % 7]}-{DOW_NAMES[int(b) % 7]}"
    if "," in dow:
        return ",".join(DOW_NAMES[int(p) % 7] for p in dow.split(","))
    return DOW_NAMES[int(dow) % 7]


def cron_to_oncalendar(cron: str) -> str:
    # Cron is "minute hour dom month dow"; only "*" dom/month are supported
    # (the only shape this fleet's manifest uses). systemd calendar events
    # need their own day/time grammar, not raw cron syntax.
    minute, hour, _dom, _month, dow = cron.split()
    dow_s = dow_to_systemd(dow)
    time_s = f"{int(hour):02d}:{int(minute):02d}:00"
    return f"{dow_s} *-*-* {time_s}" if dow_s else f"*-*-* {time_s}"


def minutes_to_oncalendar(mins: int) -> str:
    # systemd's "hh:mm/step" grammar requires 0 <= base+step <= 59, so a
    # 60-minute drain cannot be expressed as "*:0/60" (invalid unit setting).
    if mins >= 60 and mins % 60 == 0:
        hours = mins // 60
        return "hourly" if hours == 1 else f"0/{hours}:00:00"
    return f"*:0/{mins}"


for agent_id, cfg in manifest.get("agents", {}).items():
    cal = cfg.get("on_calendar")
    if cal:
        on_calendar = f"OnCalendar={cron_to_oncalendar(cal)}"
    else:
        mins = int(cfg.get("drain_minutes") or 15)
        on_calendar = f"OnCalendar={minutes_to_oncalendar(mins)}"
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

  # The base units ship with AGENT_RUNTIME_OPERATOR_AUTH=0 hardcoded
  # (fail-closed by design — see the unit file header). Actually authorizing
  # dispatch from these timers is a separate, explicit operator step: point
  # them at the same Bitwarden-rendered operator env file the HTTP dispatch
  # path already uses (never a new/duplicated secret).
  if [[ -f "$OPERATOR_ENV_FILE" ]]; then
    for dropin_target in "tradeai-agent-runtime@.service" "tradeai-agent-runtime-producer.service"; do
      dropin_dir="${USER_SYSTEMD}/${dropin_target}.d"
      mkdir -p "$dropin_dir"
      [[ -f "${dropin_dir}/10-agent-runtime-env.conf" ]] && cp "${dropin_dir}/10-agent-runtime-env.conf" "${backup}/${dropin_target}.d.10-agent-runtime-env.conf.bak" 2>/dev/null || true
      printf '[Service]\nEnvironmentFile=%s\n' "$OPERATOR_ENV_FILE" > "${dropin_dir}/10-agent-runtime-env.conf"
      echo "wired operator env into ${dropin_target} (EnvironmentFile=$OPERATOR_ENV_FILE)"
    done
  else
    echo "WARN: $OPERATOR_ENV_FILE missing — timers stay fail-closed (AGENT_RUNTIME_OPERATOR_AUTH=0)" >&2
  fi

  systemctl --user daemon-reload
  systemctl --user enable --now tradeai-agent-runtime-producer.timer
  python3 - <<'PY' "$MANIFEST"
import json, subprocess, sys
from pathlib import Path
manifest = json.loads(Path(sys.argv[1]).read_text())
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
  rm -f "${USER_SYSTEMD}/tradeai-agent-runtime@.service.d/10-agent-runtime-env.conf"
  rm -f "${USER_SYSTEMD}/tradeai-agent-runtime-producer.service.d/10-agent-runtime-env.conf"
  systemctl --user daemon-reload
  systemctl --user disable --now tradeai-agent-runtime-producer.timer || true
  echo "restored backup from ${latest} and removed operator-auth drop-ins (timers fail-closed again)"
}

load_env "/run/user/$(id -u)/tradeai/env"
load_env "${HOME}/.config/tradeai/agent-operator.env"
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

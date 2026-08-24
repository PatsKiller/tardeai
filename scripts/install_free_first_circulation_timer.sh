#!/usr/bin/env bash
# Install source-controlled FREE_FIRST_ONLY timer into the user systemd.
# Does NOT start the oneshot service. --now enables the TIMER only.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_SRC="${ROOT}/config/systemd/user"
UNIT_DST="${HOME}/.config/systemd/user"
SERVICE="tradeai-free-first-circulation.service"
TIMER="tradeai-free-first-circulation.timer"
NOW=0
for arg in "$@"; do
  case "$arg" in
    --now) NOW=1 ;;
    *) echo "usage: $0 [--now]" >&2; exit 2 ;;
  esac
done
[[ -f "${UNIT_SRC}/${SERVICE}" && -f "${UNIT_SRC}/${TIMER}" ]] || {
  echo "missing units in $UNIT_SRC" >&2
  exit 1
}
mkdir -p "$UNIT_DST"
cp -a "${UNIT_SRC}/${SERVICE}" "${UNIT_DST}/${SERVICE}"
cp -a "${UNIT_SRC}/${TIMER}" "${UNIT_DST}/${TIMER}"
systemctl --user daemon-reload
if [[ "$NOW" -eq 1 ]]; then
  # enable --now <timer> starts the TIMER unit, not the oneshot service.
  systemctl --user enable --now "$TIMER"
else
  systemctl --user enable "$TIMER"
fi
systemctl --user is-enabled "$TIMER"
systemctl --user show "$TIMER" -p UnitFileState -p ActiveState -p NextElapseUSecRealtime
echo "installed $TIMER from $ROOT (oneshot NOT started)"

#!/usr/bin/env bash
# Install CIO operator systemd units from the exact CURRENT release.
# Does not flip INTERDICT by itself. Use cio_telegram_mode.sh live|interdict.
set -euo pipefail
SRC="${1:-/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/config/systemd/user}"
if [[ ! -d "$SRC" ]]; then
  SRC="$(cd "$(dirname "$0")/.." && pwd)/config/systemd/user"
fi
DEST="${HOME}/.config/systemd/user"
mkdir -p "$DEST"
units=(
  tradeai-cio-delivery.service
  tradeai-cio-delivery-shadow.service
  tradeai-cio-delivery.timer
  tradeai-cio-material-scan.service
  tradeai-cio-material-scan-dry.service
  tradeai-cio-material-scan.timer
  tradeai-cio-defer-revisit.service
  tradeai-cio-defer-revisit.timer
  tradeai-cio-telegram.service
)
for u in "${units[@]}"; do
  if [[ -f "$SRC/$u" ]]; then
    install -m 0644 "$SRC/$u" "$DEST/$u"
    echo "installed $u"
  else
    echo "missing $SRC/$u" >&2
  fi
done
systemctl --user daemon-reload
systemctl --user enable --now tradeai-cio-delivery.timer tradeai-cio-material-scan.timer tradeai-cio-defer-revisit.timer
systemctl --user enable tradeai-cio-telegram.service
echo "units installed. converse restart is explicit: systemctl --user restart tradeai-cio-telegram.service"
echo "rollback workers: switch ExecStart to *-shadow / *-dry or cio_telegram_mode.sh interdict"

#!/usr/bin/env bash
# Flip dedicated CIO advisory Telegram between INTERDICTED and CIO_ONLY_LIVE.
# Does NOT touch general-bot credentials. Does NOT authorize broker/order/stop.
set -euo pipefail
DROPIN="${HOME}/.config/systemd/user/portfolio-server.service.d/25-cio-only-live.conf"
MODE="${1:-status}"

status() {
  echo "dropin=${DROPIN}"
  if [[ -f "$DROPIN" ]]; then
    grep -E 'CIO_TELEGRAM_INTERDICT|AUTHORIZE_P2|ENABLE_TELEGRAM' "$DROPIN" || true
  else
    echo "dropin_absent (portfolio-server 20-exact-sha INTERDICT remains authoritative)"
  fi
  systemctl --user show portfolio-server -p Environment --no-pager | tr ' ' '\n' | grep -E 'CIO_TELEGRAM_INTERDICT|AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY|ENABLE_TELEGRAM' || true
}

live() {
  mkdir -p "$(dirname "$DROPIN")"
  cat >"$DROPIN" <<EOF
[Service]
Environment=ENABLE_TELEGRAM=1
Environment=AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1
Environment=CIO_TELEGRAM_INTERDICT=0
EOF
  systemctl --user daemon-reload
  systemctl --user restart portfolio-server.service
  echo "CIO_ONLY_LIVE drop-in written. Rollback: $0 interdict"
}

interdict() {
  rm -f "$DROPIN"
  # restore explicit interdict on the SHA drop-in if present
  SHA="${HOME}/.config/systemd/user/portfolio-server.service.d/20-exact-sha-release.conf"
  if [[ -f "$SHA" ]] && ! grep -q 'CIO_TELEGRAM_INTERDICT=1' "$SHA"; then
    echo "Environment=CIO_TELEGRAM_INTERDICT=1" >>"$SHA"
  fi
  systemctl --user daemon-reload
  systemctl --user restart portfolio-server.service
  echo "INTERDICT restored (drop-in 25 removed)"
}

case "$MODE" in
  status) status ;;
  live) live ;;
  interdict|rollback) interdict ;;
  *) echo "Usage: $0 {status|live|interdict}"; exit 2 ;;
esac

#!/usr/bin/env bash
# Flip dedicated CIO advisory Telegram between INTERDICTED and CIO_ONLY_LIVE.
# Does NOT touch general-bot credentials. Does NOT authorize broker/order/stop.
# Live also writes ~/.config/tradeai/cio-operator-live.env so oneshot workers
# inherit the same gates (delivery/scan/defer are not the portfolio-server process).
set -euo pipefail
DROPIN="${HOME}/.config/systemd/user/portfolio-server.service.d/25-cio-only-live.conf"
LIVEENV="${HOME}/.config/tradeai/cio-operator-live.env"
MODE="${1:-status}"

write_liveenv() {
  local interdict="$1"
  mkdir -p "$(dirname "$LIVEENV")"
  cat >"$LIVEENV" <<EOF
ENABLE_TELEGRAM=1
AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1
CIO_TELEGRAM_INTERDICT=${interdict}
EOF
  chmod 600 "$LIVEENV"
}

status() {
  echo "dropin=${DROPIN}"
  if [[ -f "$DROPIN" ]]; then
    grep -E 'CIO_TELEGRAM_INTERDICT|AUTHORIZE_P2|ENABLE_TELEGRAM' "$DROPIN" || true
  else
    echo "dropin_absent (portfolio-server 20-exact-sha INTERDICT remains authoritative)"
  fi
  echo "liveenv=${LIVEENV}"
  if [[ -f "$LIVEENV" ]]; then
    grep -E 'CIO_TELEGRAM_INTERDICT|AUTHORIZE_P2|ENABLE_TELEGRAM' "$LIVEENV" || true
  else
    echo "liveenv_absent"
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
  write_liveenv 0
  systemctl --user daemon-reload
  systemctl --user restart portfolio-server.service
  echo "CIO_ONLY_LIVE drop-in + worker env written. Rollback: $0 interdict"
}

interdict() {
  rm -f "$DROPIN"
  write_liveenv 1
  # restore explicit interdict on the SHA drop-in if present
  SHA="${HOME}/.config/systemd/user/portfolio-server.service.d/20-exact-sha-release.conf"
  if [[ -f "$SHA" ]] && ! grep -q 'CIO_TELEGRAM_INTERDICT=1' "$SHA"; then
    echo "Environment=CIO_TELEGRAM_INTERDICT=1" >>"$SHA"
  fi
  systemctl --user daemon-reload
  systemctl --user restart portfolio-server.service
  echo "INTERDICT restored (drop-in 25 removed; worker env INTERDICT=1)"
}

case "$MODE" in
  status) status ;;
  live) live ;;
  interdict|rollback) interdict ;;
  *) echo "Usage: $0 {status|live|interdict}"; exit 2 ;;
esac

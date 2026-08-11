#!/usr/bin/env bash
# Provision TELEGRAM_CIO_BOT_TOKEN into ~/.config/tradeai/cio-telegram.env
# Usage:
#   printf '%s' '<bot_token>' | bash scripts/ops/provision_cio_telegram_token.sh
#   bash scripts/ops/provision_cio_telegram_token.sh   # prompts (hidden)
#
# Does NOT create the BotFather bot — create with @BotFather first:
#   /newbot → e.g. TradeAI_CIO_bot → copy token → pipe here
# Then message the bot once from an allowlisted chat.

set -euo pipefail
ENVF="${CIO_TELEGRAM_ENV_FILE:-$HOME/.config/tradeai/cio-telegram.env}"
mkdir -p "$(dirname "$ENVF")"
umask 077

if [[ ! -f "$ENVF" ]]; then
  cat >"$ENVF" <<'EOF'
# CIO dedicated Telegram converse
TELEGRAM_CIO_CHAT_IDS=
CIO_TELEGRAM_CONVERSE=1
CIO_TELEGRAM_WAKES_PER_HOUR=20
CIO_SITUATION_NOTIFY=0
CIO_LLM_ENRICH=1
EOF
fi

if [[ -t 0 ]]; then
  echo -n "Paste TELEGRAM_CIO_BOT_TOKEN (input hidden): " >&2
  # shellcheck disable=SC2162
  read -s TOKEN
  echo >&2
else
  TOKEN=$(cat)
fi
TOKEN=$(echo -n "$TOKEN" | tr -d '\r\n \t')
if [[ ${#TOKEN} -lt 20 ]]; then
  echo "ERROR: token looks empty/too short" >&2
  exit 2
fi
if [[ "$TOKEN" != *":"* ]]; then
  echo "ERROR: Telegram bot tokens usually look like 123456:ABC-DEF..." >&2
  exit 2
fi

# rewrite file preserving other keys
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
if grep -q '^TELEGRAM_CIO_BOT_TOKEN=' "$ENVF" 2>/dev/null; then
  sed "s|^TELEGRAM_CIO_BOT_TOKEN=.*|TELEGRAM_CIO_BOT_TOKEN=${TOKEN}|" "$ENVF" >"$tmp"
else
  printf 'TELEGRAM_CIO_BOT_TOKEN=%s\n' "$TOKEN" | cat - "$ENVF" >"$tmp"
fi
mv "$tmp" "$ENVF"
chmod 600 "$ENVF"
echo "OK: wrote token to $ENVF (mode 600)"
echo "Next:"
echo "  1) Message the new bot once from allowlisted chat"
echo "  2) systemctl --user daemon-reload"
echo "  3) systemctl --user enable --now tradeai-cio-telegram.service"
echo "  4) .venv/bin/python scripts/cio_telegram_bot.py --once --json"

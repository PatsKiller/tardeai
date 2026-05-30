#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
export HERMES_HOME="$ROOT/hermes_sidecar/.hermes"
export OLLAMA_HOST="http://127.0.0.1:11434"

# Load Hermes .env
set -a
source "$HERMES_HOME/.env"
set +a

# Strip Trade AI secrets
unset DB_PASSWORD ALPACA_API_KEY ALPACA_SECRET_KEY ALPACA_BASE_URL
unset FINVIZ_COOKIE FINVIZ_USER_AGENT FMP_API_KEY FINNHUB_API_KEY POLYGON_API_KEY NEWSAPI_KEY
unset OPENAI_API_KEY ANTHROPIC_API_KEY XAI_API_KEY TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID

cd "$ROOT"
exec "$ROOT/hermes_sidecar/install/.venv/bin/hermes" gateway run --accept-hooks "$@"

#!/usr/bin/env bash
# check_secret_exposure.sh — which current .env secret VALUES appear anywhere in git
# history? Runs LOCALLY, prints key NAMES + verdicts only — never a value.
# Usage: bash scripts/check_secret_exposure.sh   (~minutes; pickaxe over full history)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

SECRET_KEYS=(
  ADMIN_WRITE_TOKEN ALPACA_API_KEY ALPACA_SECRET_KEY ALPHA_VANTAGE_API_KEY
  ANTHROPIC_API_KEY BRAVE_SEARCH_API_KEY DB_PASSWORD FINNHUB_API_KEY
  FINVIZ_API_TOKEN FINVIZ_COOKIE FMP_API_KEY FRED_API_KEY GEMINI_API_KEY
  NEWSAPI_KEY OPENAI_API_KEY POLYGON_API_KEY SCHWAB_APP_KEY SCHWAB_APP_SECRET
  SLACK_WEBHOOK_URL SMTP_PASSWORD SNAPTRADE_CONSUMER_KEY SNAPTRADE_USER_SECRET
  TELEGRAM_BOT_TOKEN TWILIO_AUTH_TOKEN TWOCAPTCHA_API_KEY XAI_API_KEY YOUTUBE_API_KEY
)

exposed=0; clean=0; empty=0
for k in "${SECRET_KEYS[@]}"; do
  v=$(grep -m1 "^${k}=" .env 2>/dev/null | cut -d= -f2- | tr -d '"'"'" || true)
  if [[ -z "$v" || ${#v} -lt 8 ]]; then
    echo "SKIP     $k (unset or <8 chars)"; empty=$((empty+1)); continue
  fi
  # pickaxe: any commit that ever ADDED or REMOVED this exact value
  if git log --all -S"$v" --oneline -1 2>/dev/null | grep -q .; then
    first=$( (git log --all -S"$v" --oneline --reverse 2>/dev/null || true) | head -1 | cut -d' ' -f1 || true)
    echo "EXPOSED  $k (first appears in commit $first — value reachable in public history)"
    exposed=$((exposed+1))
  else
    echo "clean    $k"
    clean=$((clean+1))
  fi
done
echo
echo "== $exposed EXPOSED · $clean clean · $empty skipped — rotate every EXPOSED key; see docs/runbooks/KEY_ROTATION.md"
[[ $exposed -gt 0 ]] && exit 2 || exit 0

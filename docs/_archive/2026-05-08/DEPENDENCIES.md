# Trade AI v12 — Dependency Manifest
Generated: 2026-05-03

## Python (venv at .venv/)
See requirements.txt for exact pinned versions.
Key packages:
- anthropic — Anthropic Claude API
- psycopg2-binary — PostgreSQL adapter
- python-docx — DOCX generation
- requests — HTTP client
- beautifulsoup4 — HTML parsing
- yfinance — Yahoo Finance data
- finnhub-python — Finnhub market data
- exchange_calendars — Market calendar
- pandas, numpy — Data analysis
- matplotlib — Chart generation (server-side)
- feedparser — RSS/Atom feed parsing
- praw — Reddit API
- tweepy — Twitter/X API
- chromadb — Vector DB for RAG
- ollama — Local LLM interface
- schedule — Task scheduling
- python-dotenv — Environment variable loading
- Jinja2 — Template engine

Install: `.venv/bin/pip install -r requirements.txt`

## Node.js (apps/command-center-v2/)
See apps/command-center-v2/package.json for versions.
Runtime deps:
- react, react-dom — UI framework
- react-router-dom — Client routing
- react-chartjs-2, chart.js — Charts
- vite — Build tool
- typescript — Type checking

Install: `cd apps/command-center-v2 && npm install && npm run build`

## System-Level Dependencies
- PostgreSQL 16+ (apt: postgresql)
- Node.js 18+ (apt: nodejs or nvm)
- Python 3.11+ (apt: python3)
- Ollama (qwen3:1.7b model) — curl -fsSL https://ollama.ai/install.sh | sh
- OpenClaw (npm: openclaw@2026.4.x) — npm install -g openclaw
- gog CLI v0.12+ — Google Workspace CLI at ~/.local/bin/gog
- systemd user services (systemctl --user)

## External APIs (keys in .env)
- Anthropic (ANTHROPIC_API_KEY)
- OpenAI (OPENAI_API_KEY)
- Grok/xAI (XAI_API_KEY)
- Finnhub (FINNHUB_API_KEY)
- Telegram Bot (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)
- Google OAuth (credentials at ~/.config/gogcli/)
- Schwab/TDAmeritrade (import via CSV)

# SearXNG — Internal Search Layer

Internal-only self-hosted metasearch engine for Trade AI.

## Quick Start

```bash
cd infra/searxng
cp .env.example .env
# Edit .env: set SEARXNG_SECRET to a random 64-char hex string
sg docker -c "docker compose up -d"
```

## Access

- URL: http://127.0.0.1:18888/
- JSON API: http://127.0.0.1:18888/search?q=test&format=json

## Commands

```bash
# Status
sg docker -c "docker compose ps"

# Logs
sg docker -c "docker compose logs -f --tail 20"

# Restart
sg docker -c "docker compose restart"

# Stop
sg docker -c "docker compose down"

# Full cleanup (removes volumes)
sg docker -c "docker compose down -v"
```

## Safety

- Bound to 127.0.0.1 ONLY
- No public exposure
- No Hermes integration (requires separate approval)
- No database access
- No broker access

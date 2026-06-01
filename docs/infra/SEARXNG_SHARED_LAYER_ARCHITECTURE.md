# SearXNG Shared Search Layer — Architecture

**Date:** 2026-05-31
**Status:** APPROVED — internal-only standup
**Phase:** 16A

---

## Purpose

SearXNG is a self-hosted, privacy-respecting metasearch engine deployed as a shared infrastructure layer for Trade AI. It aggregates results from multiple search engines without tracking queries or leaking user data.

It is NOT a Hermes-specific tool. It is a shared service available to any future consumer after gated approval.

---

## Consumers (Current)

| Consumer | Access | Notes |
|----------|--------|-------|
| Operator (manual) | Direct browser at http://127.0.0.1:18888/ | Internal only |

## Consumers (Future — requires separate approval)

| Consumer | Gate Required | Notes |
|----------|--------------|-------|
| Hermes source discovery dry-run | Phase 17+ approval | Read-only, no ingestion |
| Hermes autonomous research | Phase 18+ approval | Write path, embeddings |
| Trade AI research enrichment | Phase 19+ approval | Pipeline integration |
| hermes_browse_proxy.py | Phase 17+ approval | Replace DuckDuckGo with SearXNG |

## Non-Consumers (PROHIBITED without approval)

- Broker adapter
- Proposal pipeline
- Paper trade execution
- Journal writer
- Automated trading manager
- Stop/exit manager
- Any production decision path

---

## Network Binding

| Setting | Value |
|---------|-------|
| Host binding | `127.0.0.1` only |
| Host port | 18888 |
| Container port | 8080 |
| Public exposure | NONE |
| Tailscale/FQDN | NOT CONFIGURED |
| Reverse proxy | NONE |

---

## Port Plan

| Port | Service | Status |
|------|---------|--------|
| 5432 | PostgreSQL | 127.0.0.1 (existing) |
| 7776 | DOF Auction | 0.0.0.0 (existing) |
| 7777 | Portfolio Server | 0.0.0.0 (existing) |
| 11434 | Ollama | 0.0.0.0 (existing) |
| 18789 | OpenClaw Gateway | 0.0.0.0 (existing) |
| 18790 | Hermes Gateway | 0.0.0.0 (existing) |
| **18888** | **SearXNG** | **127.0.0.1 (NEW)** |

No port conflicts.

---

## Local Directory Plan

```
infra/searxng/
├── docker-compose.yml        # Compose config
├── .env                      # Real secrets (gitignored)
├── .env.example              # Redacted example (committed)
├── core-config/
│   └── settings.yml          # SearXNG settings
└── README.md                 # Quick reference
```

---

## Docker Compose Plan

- Image: `searxng/searxng:latest`
- Container name: `searxng`
- Restart: `unless-stopped`
- Port: `127.0.0.1:18888:8080`
- Volumes: `./core-config:/etc/searxng:rw`
- Environment: secret key via `.env`
- No database connection
- No broker credentials
- No Trade AI .env references

---

## Secret/Config Policy

| Item | Git | Drive |
|------|-----|-------|
| `.env` (real secrets) | IGNORED | NOT SYNCED |
| `.env.example` (redacted) | COMMITTED | SYNCED |
| `settings.yml` | COMMITTED | SYNCED |
| `docker-compose.yml` | COMMITTED | SYNCED |
| Generated secret key | IGNORED | NOT SYNCED |
| Container volumes | IGNORED | NOT SYNCED |
| Query logs | NOT COMMITTED | NOT SYNCED |
| Favicons/cache | NOT COMMITTED | NOT SYNCED |

---

## Drive Sync Policy

Synced:
- `docs/infra/SEARXNG_*.md` (architecture, install, safety, runbook)
- `docs/project/PHASE16_*.md` (closeout)
- Redacted config examples

NOT synced:
- Real `.env` with secrets
- Container runtime data
- Query history/logs
- Cache databases
- Favicon storage

---

## Logging / Query Privacy Policy

- SearXNG logs stay inside the container
- No query logging to Trade AI database
- No query forwarding to any external analytics
- Container logs viewable via `docker compose logs` only
- No Drive sync of logs

---

## Allowed Current Use

1. Operator opens browser to http://127.0.0.1:18888/
2. Manual search queries for research
3. Service health monitoring from System Applications page
4. Container management (start/stop/restart)

## Forbidden Current Use

1. Hermes autonomous queries
2. Automated ingestion from search results
3. Embedding generation from search results
4. Promotion of search-sourced data
5. Integration with proposal/trade/journal pipelines
6. Public or Tailscale exposure
7. Paid API configuration (Google, Bing, etc.)

---

## Rollback Plan

```bash
# Stop and remove
cd infra/searxng
sg docker -c "docker compose down -v"

# Verify no port binding
ss -ltnp | grep 18888

# Remove local files (optional)
rm -rf infra/searxng/

# No database changes to revert
# No service changes to revert
# No .env changes to revert
```

---

## Future Gates

| Gate | Prerequisite | Enables |
|------|-------------|---------|
| 17A | Operator approval | SearXNG manual query wrapper dry-run |
| 17B | 17A PASS | hermes_browse_proxy.py SearXNG backend |
| 18A | 17B PASS + approval | Hermes source discovery dry-run (no ingestion) |
| 19A | 18A PASS + approval | Automated research with ingestion |
| 20A | 19A PASS + approval | Tailscale/FQDN exposure |

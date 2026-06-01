# SearXNG Operator Runbook

**Updated:** 2026-05-31

---

## Status Check

```bash
sg docker -c "docker compose -f infra/searxng/docker-compose.yml ps"
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18888/
```

## Local URL

- Browser: http://127.0.0.1:18888/
- JSON API: http://127.0.0.1:18888/search?q=QUERY&format=json

## Logs

```bash
sg docker -c "docker compose -f infra/searxng/docker-compose.yml logs --tail 50"
# Follow:
sg docker -c "docker compose -f infra/searxng/docker-compose.yml logs -f --tail 20"
```

## Restart

```bash
sg docker -c "docker compose -f infra/searxng/docker-compose.yml restart"
```

## Stop

```bash
sg docker -c "docker compose -f infra/searxng/docker-compose.yml down"
```

## Start

```bash
cd infra/searxng
sg docker -c "docker compose up -d"
```

## Rollback (Full Removal)

```bash
cd infra/searxng
sg docker -c "docker compose down -v"
sg docker -c "docker image rm searxng/searxng:latest"
# Optional: rm -rf infra/searxng/
# No DB changes to revert
# No service changes to revert
```

## Update Image

```bash
cd infra/searxng
sg docker -c "docker compose pull"
sg docker -c "docker compose up -d"
```

## Drive Sync Policy

Synced:
- `docs/infra/SEARXNG_*.md`
- `infra/searxng/.env.example`
- `infra/searxng/docker-compose.yml`
- `infra/searxng/core-config/settings.yml`

NOT synced:
- `infra/searxng/.env` (real secrets)
- Container runtime data
- Query history / logs
- Cache databases

## Query Privacy Warning

SearXNG is a metasearch engine — queries are forwarded to upstream search engines (Google, DuckDuckGo, Bing, etc.) from this server's IP. No queries are logged to Trade AI's database or synced to Drive, but upstream engines see the queries.

Do NOT search for sensitive financial data (account numbers, passwords, etc.) through SearXNG.

## Future Integration Gates

| Gate | What It Enables | Status |
|------|----------------|--------|
| 17A | Manual query wrapper dry-run | NOT APPROVED |
| 17B | hermes_browse_proxy SearXNG backend | NOT APPROVED |
| 18A | Hermes source discovery dry-run | NOT APPROVED |
| 19A | Automated research with ingestion | NOT APPROVED |
| 20A | Tailscale/FQDN public exposure | NOT APPROVED |

No future integration may proceed without explicit operator approval.

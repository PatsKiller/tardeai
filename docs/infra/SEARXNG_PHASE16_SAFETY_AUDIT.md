# SearXNG Phase 16C — Safety, Privacy, and Rollback Audit

**Date:** 2026-05-31
**Status:** PASS

---

## Network Binding

| Check | Result |
|-------|--------|
| Listening address | `127.0.0.1:18888` |
| Public (0.0.0.0) binding | NO |
| Tailscale/FQDN exposure | NOT CONFIGURED |
| Reverse proxy | NONE |

## Container Status

| Check | Result |
|-------|--------|
| Container name | searxng |
| Image | searxng/searxng:latest (2026.5.31) |
| Status | Up |
| Restart policy | unless-stopped |
| Capabilities dropped | ALL |
| Capabilities added | CHOWN, SETGID, SETUID only |

## Config/Secret Review

| Check | Result |
|-------|--------|
| `.env` in `.gitignore` | YES |
| `.env` tracked by git | NO (0 files) |
| `.env.example` committed | YES (redacted) |
| Secret key in compose file | NO (env var reference only) |
| DB credentials in container | NONE |
| Broker credentials in container | NONE |
| Trade AI `.env` modified | NO |
| Container env scan | SEARXNG_SECRET only (expected) |

## Volume Mounts

| Mount | Source | Destination | Contains |
|-------|--------|-------------|----------|
| Config | `infra/searxng/core-config` | `/etc/searxng` | settings.yml |
| Cache | Docker volume (auto) | `/var/cache/searxng` | Search cache |

No Trade AI data directories mounted.

## Drive Sync Review

| Item | Synced | Risk |
|------|--------|------|
| Architecture doc | YES | None |
| Install report | YES | None |
| Safety audit (this) | YES | None |
| `.env` (real) | NO | N/A |
| Query logs | NO | N/A |
| Cache database | NO | N/A |
| Docker volumes | NO | N/A |

## Rollback Review

```bash
cd infra/searxng
sg docker -c "docker compose down -v"
# No DB changes to revert
# No service changes to revert
# No .env changes to revert
# Optional: rm -rf infra/searxng/
```

Rollback is clean — SearXNG is fully isolated from Trade AI state.

## Log/Query Privacy Review

- Container logs stored inside Docker only (`json-file` driver, 10MB × 3)
- No query forwarding to external analytics
- No query logging to Trade AI database
- No Drive sync of logs or query history
- `HISTFILE=/dev/null` set inside container

## Hermes Integration

- Hermes gateway: UNCHANGED (active on 18790)
- Hermes autonomous timer: UNCHANGED (daily 01:00 UTC)
- Hermes browse proxy: NOT CONNECTED to SearXNG
- No autonomous research using SearXNG

## Production Service Impact

| Service | Changed | Status |
|---------|---------|--------|
| Portfolio Server (7777) | NO | Running |
| DOF Auction (7776) | NO | Running |
| Hermes Gateway (18790) | NO | Running |
| Hermes Timer | NO | Active |
| OpenClaw (18789) | NO | Running |
| Ollama (11434) | NO | Running |
| PostgreSQL (5432) | NO | Running |

## Future Integration Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Unintentional Hermes connection | MEDIUM | Requires code change + approval |
| Public exposure via misconfiguration | LOW | 127.0.0.1 in compose, audit check |
| Query privacy leaks to Drive | LOW | Sync script excludes logs/cache |
| Resource exhaustion from heavy use | LOW | Rate limiting available in settings |

## Recommendation

**PASS** — SearXNG is safely deployed as internal-only shared infrastructure. No production impact, no Hermes integration, no public exposure, clean rollback path.

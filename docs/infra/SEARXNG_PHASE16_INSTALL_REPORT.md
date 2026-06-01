# SearXNG Phase 16B — Install Report

**Date:** 2026-05-31
**Status:** COMPLETE

## Image

- `searxng/searxng:latest` (pulled fresh)

## Compose File

- `infra/searxng/docker-compose.yml`
- Container name: `searxng`
- Restart policy: `unless-stopped`
- Capabilities dropped: ALL (added CHOWN, SETGID, SETUID only)
- Log rotation: 10MB × 3 files

## Port Binding

- Host: `127.0.0.1:18888`
- Container: `8080`
- Public: **NO**
- Tailscale: **NOT CONFIGURED**

## Endpoint Checks

| Check | Result |
|-------|--------|
| `curl -I http://127.0.0.1:18888/` | HTTP 200 |
| `curl http://127.0.0.1:18888/search?q=test&format=json` | 27 results |
| `ss -ltnp \| grep 18888` | `127.0.0.1:18888` only |
| `docker ps` | searxng Up, 127.0.0.1:18888->8080/tcp |

## Running Containers

| Container | Status | Ports |
|-----------|--------|-------|
| searxng | Up | 127.0.0.1:18888->8080/tcp |

## Safety Confirmations

- [x] Bound to 127.0.0.1 only — no public exposure
- [x] `.env` in `.gitignore` — not committed
- [x] No DB credentials in container
- [x] No broker credentials in container
- [x] No Trade AI `.env` changes
- [x] No Hermes timer changes
- [x] No production service changes
- [x] No Hermes integration enabled
- [x] JSON API working for future dry-runs
- [x] Capabilities dropped (defense in depth)

## Rollback

```bash
cd infra/searxng
sg docker -c "docker compose down -v"
# Optionally: rm -rf infra/searxng/
```

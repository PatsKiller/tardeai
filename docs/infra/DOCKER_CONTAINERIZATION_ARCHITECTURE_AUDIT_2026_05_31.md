# Docker Containerization Architecture Audit

**Date:** 2026-05-31
**Status:** DESIGN ONLY — Docker not installed, no runtime changes

---

## Current Service Inventory

| Service | Port | Type | Process | Containerize? |
|---------|------|------|---------|---------------|
| Portfolio Server | 7777 | system service | python | NOT YET |
| DOF Auction | 7776 | background | python3 | CANDIDATE |
| OpenClaw Gateway | 18789 | user service | openclaw-gateway | NOT YET |
| Hermes Gateway | 18790 | user service | hermes | NOT YET |
| Ollama | 11434 | system service | ollama (GPU) | NOT YET |
| PostgreSQL | 5432 | system service | postgres | NEVER FIRST |
| Tailscale | 443/8443 | system | tailscaled | NEVER |

## Do NOT Containerize First

| Component | Reason |
|-----------|--------|
| PostgreSQL | Core data store, GPU-bound Ollama dependency |
| Ollama | Requires GPU passthrough (Intel Arc B50 Vulkan) |
| Portfolio Server | Serves Command Center, API, broker adapter |
| OpenClaw Gateway | Agent messaging, Telegram/WhatsApp |
| Hermes autonomous timer | Depends on Ollama, DB, stable scheduling |
| Alpaca/paper execution | Broker-facing, safety-critical |

## Safe First Pilot Candidates

| Candidate | Risk | Description |
|-----------|------|-------------|
| Static docs preview | LOW | Nginx serving docs/ as read-only HTML |
| Version check script | LOW | Weekly version check in isolated container |
| Backup job | LOW | pg_dump + Drive sync in container |

## Prerequisites Before Any Docker Work

1. Install Docker Engine
2. Verify GPU passthrough support for Ollama (if needed)
3. Define volume strategy for data/, logs/, hermes_sidecar/
4. Define secrets/env management (never bake .env into images)
5. Define port mapping (avoid conflicts with existing services)
6. Define backup strategy for container state
7. Define rollback to bare-metal procedure

## Risks

| Risk | Severity |
|------|----------|
| GPU passthrough complexity for Ollama | HIGH |
| Port conflicts during migration | MEDIUM |
| Data volume persistence | MEDIUM |
| Increased operational complexity | MEDIUM |
| .env/secrets exposure in image layers | HIGH if not managed |

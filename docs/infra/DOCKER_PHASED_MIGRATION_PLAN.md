# Docker Phased Migration Plan

**Status:** PLAN ONLY — not started

## Phase 1: Install Docker (requires approval)
- Install Docker Engine
- Verify docker compose works
- No containers yet

## Phase 2: Safe read-only pilot (requires approval)
- Static docs server or version check job
- No DB access
- No production impact
- Verify volume, port, log behavior

## Phase 3: Utility containers (requires approval)
- Backup job container
- Drive sync container
- Still no production services

## Phase 4: Non-critical service migration (requires approval)
- DOF Auction server (port 7776)
- Isolated, non-trading

## Phase 5+: Production services (far future, requires extensive approval)
- Portfolio Server
- OpenClaw Gateway
- Hermes Gateway
- Each requires separate approval, testing, rollback verification

## NEVER in containers without extreme justification:
- PostgreSQL (performance, GPU locality)
- Ollama (GPU passthrough complexity)
- Alpaca/broker adapter

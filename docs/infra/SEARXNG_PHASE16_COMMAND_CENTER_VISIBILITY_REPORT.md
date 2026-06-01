# SearXNG Phase 16D — Command Center Visibility Report

**Date:** 2026-05-31
**Status:** COMPLETE

## Changes

Added to System Applications API (`/api/v2/system/applications`):

1. **Docker Engine** — category: infrastructure, version detection via `docker version`
2. **SearXNG** — category: infrastructure, health check via HTTP to 127.0.0.1:18888

## Visibility

| Item | Visible | Type |
|------|---------|------|
| SearXNG service status | YES | Read-only |
| SearXNG internal URL | YES (127.0.0.1:18888) | Internal only |
| Docker Engine version | YES | Read-only |
| SearXNG start/stop controls | NO | Not implemented |
| SearXNG query UI in CC | NO | Not implemented |
| Public/Tailscale link | NO | Not configured |

## Safety

- [x] Page remains read-only — no service controls
- [x] No public links exposed
- [x] No Hermes integration
- [x] Note clearly states "Not integrated with Hermes or production"
- [x] No write endpoints added

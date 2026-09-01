# Phase 206G — Legacy Agent Visibility Validation — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T10:35:54-04:00
Measured at: efcc51365 / not measured

| Check | Result |
|-------|--------|
| `python3 scripts/hermes_legacy_agent_inventory.py` | OK — 24 items (`RETIRED_SOUL:2, RETIRED_AGENT:1, RETIRED_WRAPPER:4, UNSAFE_RUNTIME_ARTIFACT:13, ACTIVE_PROFILE:4`) |
| `GET /api/v2/hermes/legacy-agents` | HTTP 200, `ok=true`, total 24, `actions_available=[]`, `read_only=true` |
| `py_compile api_v2.py + hermes_legacy_agent_inventory.py` | OK |
| v3 build | OK (`npm run build`) |
| Gateway `is-active` / `is-enabled` | **failed / disabled** (unchanged) |
| Retired dir mtimes before vs after scan | **identical** — read-only proven (2140: 21:40:20, 2154: 21:54:01, install: 05-30 09:37) |
| No v2 UI changed | confirmed (no `apps/command-center-v2` diff) |
| Secrets in payload | none (only the script's own "Secrets are redacted" text matches the pattern) |

All read-only; no service started/enabled; no wrapper executed; retired dirs untouched.

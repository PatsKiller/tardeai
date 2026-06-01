# Phase 67A — Finviz & Agent Staleness Incident Inventory

**Date:** 2026-06-01
**Status:** COMPLETE — degraded ingestion confirmed

## Finviz Cookie Alert

- FINVIZ_COOKIE: present in .env (1 entry)
- FINVIZ_API_TOKEN: present in .env (1 entry)
- Today's screener runs: 19 FAILED, 1 HEALTHY
- Affected screener: prime_setups and others
- Suspected cause: expired/invalid cookie returning login page

## Agent Staleness

- mariaresearch: no agent_runs table rows found — agent may not use standard tracking
- Escalation loop: reports "fixed" but stale alerts repeat
- Root cause: LLM-based escalation marks "analyzed" as "fixed" without verifying fresh output

## Downstream Risks

| Risk | Impact |
|------|--------|
| Stale momentum scout candidates | HIGH — GO/WAIT/NO decisions based on old data |
| Missing catalysts | MEDIUM — catalyst_events not refreshed |
| Stale dashboard data | MEDIUM — screener health shows degraded |
| Stale Hermes research inputs | LOW — Hermes reads safe views, not raw screener |
| False Level 6 maturity confidence | HIGH — ingestion must be healthy for certification |

## Alert Evidence

- 11 strategic_alerts in last 24 hours
- Screener 19/20 runs failed today
- Only 1 healthy run (10:00 AM, 1107 symbols scanned)

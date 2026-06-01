# Phase 71A — Finviz Feed Resilience Design

**Date:** 2026-06-01
**Status:** COMPLETE — design only

## Current Fragility

Single FINVIZ_COOKIE controls all screener ingestion. When expired:
- All screener runs fail
- Momentum scout has no fresh candidates
- Catalyst quality data stales
- Incubator pipeline stalls

## Resilience Improvements

### 1. Cookie Age Tracking (No Raw Cookie Stored)

Track cookie-set timestamp in .env comment or state file:
```
# FINVIZ_COOKIE_SET_DATE=2026-06-01
```
Alert when age > 7 days.

### 2. Health Preflight Before Screeners

Before each screener cron/timer run:
- Check FINVIZ_COOKIE exists
- Make 1 lightweight test request
- If login page returned: skip run, alert once, suppress repeats

### 3. Auto-Skip Failing Screener

After 3 consecutive failures:
- Skip further runs for that screener
- Send single grouped alert
- Resume on next cookie update

### 4. FINVIZ_API_TOKEN Fallback

If FINVIZ_API_TOKEN is set and valid, use API path when cookie fails. Requires API support verification.

### 5. SearXNG Research Fallback

For research context only (NOT screener replacement):
- If Finviz is down, Hermes source discovery can fill research gaps
- Does not replace symbol scanning pipeline
- Manual/capped only

## Dashboard Visibility

- Feed health card on System Applications
- Cookie age indicator
- Last successful screener timestamp
- Failure streak count

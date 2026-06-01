# Phase 46B — Scheduled Job Health API Report

**Date:** 2026-06-01
**Status:** COMPLETE

## Endpoint

- `GET /api/v2/system/scheduled-jobs`
- Read-only, no POST/PUT/PATCH/DELETE
- Returns: timer list, cron counts, health timestamps

## Verified Response

- Systemd timers: detected from unit files
- Cron active: 176
- Cron migrated: 11
- Last observation: 2026-06-01T06:31 UTC
- Last backlog health: 2026-06-01T06:45 UTC

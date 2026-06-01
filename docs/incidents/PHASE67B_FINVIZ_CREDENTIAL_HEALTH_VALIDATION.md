# Phase 67B — Finviz Credential Health Validation

**Date:** 2026-06-01
**Status:** EXPIRED_COOKIE (most likely)

## Validation

| Check | Result |
|-------|--------|
| FINVIZ_COOKIE in .env | YES (present, not printed) |
| FINVIZ_API_TOKEN in .env | YES (present) |
| prime_setups CSV return | FAILED (19/20 today) |
| One successful run | 10:00 AM, 1107 symbols (may have used cached/API token path) |
| Login page returned | LIKELY (standard cookie-expired behavior) |

## Classification

**EXPIRED_COOKIE** — cookie present but invalid/expired. Most screener runs returning login page or empty results.

## Required Operator Action

Update FINVIZ_COOKIE via approved secret path. Do not paste in docs/logs/commits.

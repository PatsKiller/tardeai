# Phase 6D Test Results — Stale-Time Sweeper

**Date:** 2026-05-15

## Unit Tests: 18/18 PASSED

| # | Test | Result |
|---|------|--------|
| 01 | Fresh momentum under 60 min | OK |
| 02 | Stale momentum over 60 min | OK |
| 03 | Stale screener after 4 hours | OK |
| 04 | Fresh swing under 3 days | OK |
| 05 | Stale swing over 3 days | OK |
| 06 | Stale recovery watch over 5 days | OK |
| 07 | Stale unknown strategy after 24h | OK |
| 08 | Missing timestamp → requires_review | OK |
| 09 | Terminal statuses ignored | OK |
| 10 | Expired via expires_at | OK |
| 11 | Response structure complete | OK |
| 12 | Sweeper has no DELETE statement | OK |
| 13 | Stale blocks before session gate | OK |
| 14 | Fresh proposal proceeds | OK |
| 15 | Phase 6A regression (24/24) | OK |
| 16 | Phase 6B regression | OK |
| 17 | Income strategy long threshold | OK |
| 18 | String timestamp parsing | OK |

## Full Regression: 71/71 (24 + 12 + 17 + 18)

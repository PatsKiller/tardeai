# Phase 6A Test Results — Market Revalidation Unit Tests

**Date:** 2026-05-15
**Runner:** `.venv/bin/python tests/test_phase6_market_revalidation.py`
**Framework:** unittest (standalone, no pytest required)

## Results

**24/24 PASSED** in 0.001s

| # | Test | Result |
|---|------|--------|
| 01 | PASS: fresh quote, good conditions | OK |
| 02 | WARN/PASS: 2% drift, adjusted entry | OK |
| 03 | BLOCK: no live quote | OK |
| 04 | BLOCK: stale quote (>15 min) | OK |
| 05 | BLOCK: price drift >3% | OK |
| 06 | BLOCK: stop breached (long) | OK |
| 07 | BLOCK: stop breached (exact) | OK |
| 08 | BLOCK: wide spread >1.5% | OK |
| 09 | BLOCK: R:R degraded <1.2 | OK |
| 10 | BLOCK: missing bid/ask (empty quote) | OK |
| 11 | BLOCK: missing/invalid stop | OK |
| 12 | BLOCK: missing/invalid target | OK |
| 13 | BLOCK: calculation exception fails closed | OK |
| 14 | RESPONSE: structure has all required fields | OK |
| 15 | ORDERING: blocked result has no paper_trade_id | OK |
| 16 | STRING: ISO timestamp parsing | OK |
| 17 | UNIX: epoch float timestamp parsing | OK |
| 18 | NO_TS: missing timestamp trusts provider | OK |
| 19 | CONFIG: custom thresholds override defaults | OK |
| 20 | NONE: None quote blocks | OK |
| 21 | BLOCK: missing entry price | OK |
| 22 | BOUNDARY: R:R exactly at minimum passes | OK |
| 23 | BOUNDARY: spread exactly at limit passes | OK |
| 24 | BOUNDARY: drift exactly at block threshold passes | OK |

## Coverage

- All 6 block conditions tested
- Warning/adjustment path tested
- Boundary conditions tested (exact threshold values)
- Fail-closed behavior confirmed for exceptions
- Response structure validated
- Configurable thresholds tested
- Multiple timestamp formats tested (datetime, ISO string, unix epoch)
- None/empty inputs tested

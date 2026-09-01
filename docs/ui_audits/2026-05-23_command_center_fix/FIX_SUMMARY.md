# Command Center Data Integrity Fix Summary (2026-05-23)

Status:      HISTORICAL
as_of:       2026-05-23T20:17:18-04:00
Measured at: efcc51365 / not measured

## Before/After Consistency Check

| Check | Before | After |
|-------|--------|-------|
| Canonical holdings | PASS ($1,201,120 / 47) | PASS |
| Phantom accounts (API) | FAIL ("258" shown) | PASS (filtered) |
| Rebalance income | FAIL ($0/$0) | PASS ($14,408) |
| CIO duplicates | FAIL (14 duplicate symbols) | PASS (0 duplicates) |
| Retirement delta | WARN ($1.2M delta) | PASS (within tolerance) |
| AI Analyst freshness | WARN (no indicator) | PASS (is_stale=false) |
| Command snapshot_source | WARN (missing) | PASS (labeled) |
| Rebalance snapshot_source | WARN (missing) | PASS (labeled) |
| Retirement snapshot_source | WARN (missing) | PASS (labeled) |
| **Total** | **4 FAIL, 5 WARN** | **0 FAIL, 1 WARN** |

## Tier 1 Fixes (Data Integrity)

### B: Attribution phantom "258" — FIXED
- **File:** api_v2.py `_attribution_accounts()` line 5463
- **Change:** Skip accounts with total_value <= 0
- **Result:** "258" no longer appears in attribution API

### D: Rebalance income $0/$0 — FIXED
- **File:** api_v2.py `rebalance()` return dict
- **Change:** Added `computed_values` with income from dividend_calendar.json
- **Result:** income_current=$14,408, income_gap=$40,592

### F: CIO decisions duplicates — FIXED
- **File:** api_v2.py `_cio_decisions_enriched()` line 5109
- **Change:** Added `DISTINCT ON (symbol)` to query, re-sort by priority in Python
- **Result:** 50 decisions, 0 duplicate symbols

## Tier 2 Fixes (Misleading UI)

### A: Portfolio snapshot source labels — FIXED
- Added `snapshot_source` metadata to command, rebalance, and retirement endpoints
- Pages now declare their data source and filter methodology

### E: Retirement snapshot delta — FIXED
- Added `canonical_total`, `snapshot_delta`, `snapshot_source` to retirement endpoint
- Frontend can now show delta between planning snapshot and current holdings

### N: AI Analyst staleness — FIXED
- Added `is_stale` boolean computed from `generated_at` age (>48h = stale)
- Frontend can now show stale warning on cached analysis

## Tier 3 Deferred (Not Changed)

| Theme | Reason |
|-------|--------|
| C: TLH → AI Analyst | Enhancement, not a data bug |
| G: Incubator PROMOTED=0 | Correct behavior, zero promotions is real data |
| H: Strategy governance | YAML configs already have correct status fields |
| I: Duplicate pages | UX/IA decision, not a code bug |
| J: Topic Monitor dormant | Ops config (no crontab entry), not a code bug |
| K: Finviz images | No img tags in React code; only in generated HTML reports |
| L: WebSocket error | ScalpLiveFeed.tsx already has silent HTTP fallback |
| M: Technical page | Enhancement (analyst targets, catalysts) |
| O: Global freshness | Enhancement (extend FreshnessBadge to more pages) |

## Playwright Audit

| Metric | Before | After |
|--------|--------|-------|
| Routes | 67 | 67 |
| OK | 65 | 65 |
| Timeout | 0 | 0 |
| Error | 0 | 0 |
| Console errors | 2 (trade-ai, reports) | 2 (unchanged) |

## Files Changed
- `scripts/api_v2.py` — 6 targeted edits
- `scripts/check_command_center_data_consistency.py` — new verification script
- `docs/ui_audits/2026-05-23_command_center_fix/ROOT_CAUSE_MATRIX.md` — discovery doc
- `docs/ui_audits/2026-05-23_command_center_fix/FIX_SUMMARY.md` — this file

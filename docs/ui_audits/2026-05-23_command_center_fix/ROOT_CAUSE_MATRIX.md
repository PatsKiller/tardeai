# ROOT CAUSE MATRIX — Command Center v12 Visual Audit (2026-05-23)

Status:      HISTORICAL
as_of:       2026-05-23T20:17:18-04:00
Measured at: efcc51365 / not measured

## Snapshot Value Reconciliation

| Source | Value | Filter | File |
|--------|-------|--------|------|
| holdings.json portfolio_totals | $1,201,120.25 | All 47 positions | data/portfolios/state/holdings.json |
| risk_management.json | $1,199,229.88 | 43 positions >$100 | data/portfolios/state/risk_management.json |
| retirement_roadmap.json | $1,199,230 | Snapshot at generation time | data/portfolios/state/retirement_roadmap.json |
| Rebalance live (api_v2.py:5565) | ~$1,193,196 | Positions >$50 | scripts/api_v2.py |
| Tax lots aggregate | ~$1,227,057 | Lot-level sum | scripts/api_v2.py |

## Issue Matrix

| Theme | Page(s) | Root Cause | Tier | File:Line | Fix | Status |
|-------|---------|------------|------|-----------|-----|--------|
| A | Overview, Rebalance, Risk, Retirement | Different position-size filters per endpoint | 2 | api_v2.py multiple | Add snapshot_source labels | [ ] |
| B | Attribution | Phantom "258" account ($0) in account_summaries | 1 | api_v2.py:5463 | Filter zero-value accounts | [ ] |
| C | AI Analyst, Tax | TLH data not in AI analyst input context | 3 | — | Defer (enhancement) | [x] |
| D | Rebalance | Frontend reads computed_values not in API response | 1 | api_v2.py:5632 | Add computed_values with dividend income | [ ] |
| E | Retirement | Uses retirement_roadmap.json snapshot, unlabeled | 2 | api_v2.py:2689 | Add snapshot delta comparison | [ ] |
| F | CIO Dashboard | No DISTINCT ON in cio-decisions query | 1 | api_v2.py:5109 | Add DISTINCT ON (symbol) | [ ] |
| G | Incubator | promoted_to_proposal_at correctly used; zero promotions is real data | 3 | — | Not a bug | [x] |
| H | Strategy pages | Governance status in YAML configs already correct | 3 | — | No code change | [x] |
| I | Paper Review/Outcomes/Journal | Duplicate routes, same/similar backend data | 3 | — | UX decision, defer | [x] |
| J | Topic Monitor | topic_ingestion.py not in crontab (manual only) | 3 | — | Ops config, defer | [x] |
| K | Reports | Finviz images — no img tags in React (in generated HTML only) | 3 | — | Not applicable to SPA | [x] |
| L | Trade AI | WS error — ScalpLiveFeed.tsx already has silent fallback | 3 | — | Already handled | [x] |
| M | Technical | Limited data fields (no analyst targets/catalysts) | 3 | — | Enhancement, defer | [x] |
| N | AI Analyst | No staleness indicator on cached analysis | 2 | api_v2.py:2803 | Add is_stale field | [ ] |
| O | Global | FreshnessBadge only on Command page | 3 | — | Enhancement, defer | [x] |

## Tier 1 Fixes (Data Integrity)

### B: Attribution phantom "258"
- **Evidence:** attribution.png shows account "258" with $0 and 0 positions
- **Route:** /v2/attribution
- **Frontend:** Attribution.tsx
- **API:** /api/v2/attribution → _attribution_accounts()
- **Backend:** api_v2.py:5443-5470
- **Source:** holdings.json account_summaries["258"] = {total_value: 0, holdings_count: 1}
- **Fix:** Filter accounts where total_value <= 0 at line 5463

### D: Rebalance income $0/$0
- **Evidence:** rebalance.png shows Income Current: $0, Income Gap: $0
- **Route:** /v2/rebalance
- **Frontend:** Rebalance.tsx reads data.computed_values.income_current
- **API:** /api/v2/rebalance → rebalance()
- **Backend:** api_v2.py:5494-5633 — return dict has no computed_values key
- **Source:** dividend_calendar.json has total_annual: $14,407.90
- **Fix:** Add computed_values to rebalance return dict at line 5632

### F: CIO decisions duplicates
- **Evidence:** cio.png shows repeated Visa entries
- **Route:** /v2/cio
- **Frontend:** CIO page
- **API:** /api/v2/cio-decisions → _cio_decisions_enriched()
- **Backend:** api_v2.py:5109 — SELECT * without DISTINCT ON
- **Source:** cio_decisions table has multiple rows per symbol
- **Fix:** Add DISTINCT ON (symbol) to query at line 5109

## Tier 2 Fixes (Misleading UI)

### A: Portfolio snapshot labeling
- **Fix:** Add snapshot_source metadata string to overview, rebalance, retirement return dicts

### E: Retirement stale snapshot
- **Fix:** Add canonical_total comparison and snapshot_note to retirement return

### N: AI Analyst staleness
- **Fix:** Add is_stale boolean based on generated_at age >48h

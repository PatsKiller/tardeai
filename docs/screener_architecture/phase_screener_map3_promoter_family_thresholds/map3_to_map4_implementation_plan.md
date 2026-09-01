# MAP-3 → MAP-4 Implementation Plan

Status:      ACTIVE
as_of:       2026-05-21T10:27:57-04:00
Measured at: efcc51365 / not measured

## MAP-4 Goal
Enable family-specific promotion in production for approved families.

## Ready for MAP-4 (operator approval required)

| Family | Candidates | Action |
|--------|-----------|--------|
| DIVIDEND_INCOME | 155 | Relax spread gate from 3% to 8% for this family |
| TECHNICAL_PATTERN | 27 | Current gates sufficient — enable promotion |
| CORE_GROWTH | 27 | Relax score gate from 35 to 15 |
| SECTOR_ROTATION | 81 | Relax RVOL from 3.0 to 0.5 |
| RECOVERY_WATCH | 169 | Already producing — more with relaxed thresholds |

## Blocked — Needs Provider Work First

| Family | Issue | Required |
|--------|-------|----------|
| EARNINGS_PRE/POST | No earnings date data | Earnings calendar API |
| OPTIONS_INCOME | No options chain data | Options data provider |

## Implementation Steps

1. Import `promoter_family_threshold_policy` in `incubator_proposal_promoter.py`
2. Replace hard-coded `spread > 3.0` with `spread > get_family_thresholds(strategy_id)['max_spread_pct']`
3. Add family-specific evaluation before proposal creation
4. Keep proposal_eligible gated on operator approval
5. No live trading

## Risk

- Income/dividend proposals will start appearing — operator must review them
- Spread gate relaxation means wider-spread candidates can become proposals
- Family thresholds are conservative estimates — may need tuning after observation

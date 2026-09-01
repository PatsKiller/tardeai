# Phase 186C: Stage 1 Tomorrow Candidate Pipeline Report

Status:      HISTORICAL
as_of:       2026-06-02T00:21:42-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-02
**Mode**: PAPER ONLY — run_label 0900

## Scan Results

| Metric | Value |
|--------|-------|
| Symbols scanned | 59 |
| GO candidates | 4 |
| WAIT candidates | 7 |
| AVOID | 48 |
| Disqualified | 4 (low price spike) |
| Catalyst unverified | 14 |
| Run health | RUN_HEALTHY (59 >= 40 min) |

## GO Candidates

| Symbol | Score | RVOL | Gap% | Float M | Catalyst | Sector |
|--------|-------|------|------|---------|----------|--------|
| ANY | 51 | 217x | 66.6% | 4.1M | Sphere 3D acquisition of Cathedra Bitcoin | Financial Services |
| ELMT | 50 | 5.5x | 24.7% | 2.86M | Taylor Morrison/Berkshire Hathaway acquisition | Industrials |
| ABTS | 40 | 208x | 59.3% | 2.18M | Abits Group registered direct offering at $2.65 | Financial Services |
| NAMM | 40 | 42x | 47.4% | 4.49M | Gap-up session momentum | Basic Materials |

## WAIT Candidates

| Symbol | Score | RVOL | Gap% | Float M | Sector |
|--------|-------|------|------|---------|--------|
| HMR | 39 | 16x | 17.1% | 5.48M | Industrials |
| SAIC | 39 | 3.2x | 15.3% | 42.7M | Technology |
| HPE | 38 | 6.2x | 2.6% | 0M | Technology |
| CRE | 37 | 10x | 36.7% | 1.1M | Industrials |
| MASK | 37 | 4.1x | 51.1% | 0.82M | Technology |
| AIRJ | 32 | 6.8x | — | 32.6M | Technology |
| LFVN | 32 | 6.2x | — | 10.5M | — |

## Proposal Generation

| Metric | Value |
|--------|-------|
| Auto-proposals created | 1 |
| Proposal: ELMT #160 | momentum_scalp, $18.88 entry, R:R 2.01 |
| ANY skipped | Already has open trade (id=48) |
| ABTS/NAMM skipped | Did not generate strategy signals above threshold |
| Risk gate | 6 approved, 5 flagged |

## Position Capacity

| Metric | Value |
|--------|-------|
| Open positions | 6 (AGNC, ANY, CMCSA, NWG, SNOW, TMHC) |
| Max concurrent | 10 |
| Available slots | 4 |
| Max new/day | 25 |
| Today's new trades | 0 |
| Remaining daily cap | 25 |

## Strategy Distribution (proposals)

| Strategy | Count |
|----------|-------|
| momentum_scalp | 1 (ELMT) |

## Notes

- Only 1 auto-proposal generated from 4 GO candidates
- ANY blocked by existing open position
- ABTS/NAMM did not pass strategy signal thresholds
- Market scan from overnight data — live prices will revalidate at market open
- Additional scan runs (1000, 1200, 1400, 1600) will generate more candidates

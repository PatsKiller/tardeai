# Momentum Scalp Source Maturity

Status:      ACTIVE
as_of:       2026-06-28T22:49:34-04:00
Measured at: efcc51365 / not measured

**Status: PASS** | window: 30d  
_Generated: 2026-06-29T02:48:12.773382+00:00_  
_Source: `python3 scripts/momentum_scalp_source_maturity_report.py --days N --json`_  

**Combined source maturity: 4.5/5**

| Source | Before | After | Δ | Fresh data | In-window obs |
|--------|-------:|------:|---:|:----------:|:-------------:|
| Finviz | 3.9 | 4.5 | +0.6 | ✓ | — |
| TradeAI scanner | 3.9 | 4.5 | +0.6 | ✓ | — |
| Social Scout / social posts | 4.2 | 4.5 | +0.3 | ✓ | — |
| News / catalyst | 4.0 | 4.5 | +0.5 | ✓ | — |
| SEC / Form 4 | 3.0 | 4.5 | +1.5 | — | — |
| Quote / liquidity | 4.2 | 4.5 | +0.3 | — | — |
| Strategy signal sync | 3.8 | 4.5 | +0.7 | — | — |
| Proposal generation | 3.8 | 4.5 | +0.7 | ✓ | — |
| Validation fast path | 4.4 | 4.5 | +0.1 | ✓ | — |

## Validation maturity (separate from source maturity)

- Confirmed closed simulated validation trades: **2/30**
- Empirical gate met: **False**
- Strategy maturity 4.5+: **4.5+ NOT claimable**
- Blocker: validation sample 2/30 — empirical sample remains the blocker to 4.5

> SOURCE maturity (discovery/scan/signal/proposal/validation plumbing) is reported SEPARATELY from STRATEGY/validation maturity. This report does NOT claim strategy maturity 4.5/5.0; that requires the empirical validation sample.

> Read-only. No live broker writes. Operator confirmation / 2FA untouched.


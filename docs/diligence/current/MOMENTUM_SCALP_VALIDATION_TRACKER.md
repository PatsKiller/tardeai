# Momentum Scalp Validation Tracker

Status:      ACTIVE
as_of:       2026-06-28T22:49:34-04:00
Measured at: efcc51365 / not measured

**Status: PASS** | gate met: **False** | live-ready: **False**
_Generated: 2026-06-29T02:48:11.932087+00:00_
_Source: `python3 scripts/momentum_scalp_validation_tracker.py --json`_

> Counts use conservative confirmed attribution only (scalp_trade_attribution); ambiguous/non-executed rows excluded.

**2/30 confirmed closed paper trades (win 0.5, PF 1.4031). Sample insufficient — still TESTING.**

Confirmed trade IDs: [45, 22] (excluded ambiguous [19], 19 non-executed).

| Criterion | Have | Need | Met |
|-----------|------|------|-----|
| closed_paper_trades | 2 | 30 | False |
| win_rate | 0.5 | 0.5 | True |
| profit_factor | 1.4031 | 1.3 | True |
| calendar_months | 0.6 | 6 | False |
| human_approval | False | True | False |

## Next actions

- Ensure the in-window momentum_scalp paper path converts (see diagnose_momentum_scalp_paper_path.py).
- Collect confirmed closed paper trades toward the 30-trade / 6-month gate.
- Do NOT promote to live; per-order operator confirmation / 2FA remains required and is out of scope.

> Read-only. No broker writes. LLMs advisory only.


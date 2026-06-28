# Social Scout Replay

**Status: PASS** | window: 30d  
_Generated: 2026-06-28T23:20:19.663778+00:00_  
_Source: `python3 scripts/social_scout_replay_report.py --days N --json`_  

Replayed **1458** social scan rows.

## Pillar-count histogram

| Pillars | Count |
|---------|-------|
| 0/5 | 1380 |
| 1/5 | 6 |
| 2/5 | 0 |
| 3/5 | 0 |
| 4/5 | 72 |
| 5/5 | 0 |

## Social Scout surfacing

- Social Scouts surfaced (≥2/5): **72**
- Large-float Social Scouts (manual-review only): **69**
- Social-only Social Scouts (WATCH/WAIT/SCOUT only): **72**
- Graduated to momentum_scalp / GO (normal gates): **0**
- Scouts blocked from validation fast path: **72** (equals scouts surfaced — none are validation-ready)

## Top missing pillars

- catalyst_evidence: 72

## Top reason codes

- SCOUT_SOCIAL_VELOCITY: 72
- SCOUT_MARKET_CONFIRMATION: 72
- SCOUT_STRUCTURE_TRADEABILITY: 72
- SCOUT_STRATEGY_RISK_FIT: 72
- NEEDS_CATALYST: 72

> Read-only. No broker writes. A Social Scout is operator-awareness ONLY — it is never validation-ready or GO unless the normal route policy + deterministic gates pass. Validation maturity is unchanged by Social Scout surfacing.


# Proposal Supply Funnel Audit — 2026-06-26

Window: last **5** days · generated 2026-06-26T02:13:50.564778+00:00

## Funnel attrition

```
Stage                                Window    Per day  Notes
------------------------------------------------------------------------
Screener universe                      1286          —  symbol_profiles
Scored (trade_ai_scans)                5783       1157
Score ≥ 30 (WAIT+GO)                     50         10  0.14% are GO (≥40)
Score ≥ 40 (GO)                           8          2
Strategy signals                         65         13
Auto proposals                            8          2
Incubator promotions                     11          2
Total proposals created                 289       57.8
ATM approved (window)                     2
Linked to paper trade                     2  0.7% link rate
Pending now                               2
Broker queue pending                      0
```

## Scoring distribution

| Band | Count |
|------|------:|
| 40+ GO | 8 |
| 30-39 WAIT | 42 |
| 20-29 | 150 |
| 10-19 | 939 |
| 1-9 | 4491 |
| 0 DISQUALIFIED | 153 |

## Risk-gate blocks (window)

| Gate result | Count |
|-------------|------:|
| APPROVED | 116 |
| REJECTED | 43 |

## vs May-2026 baseline

- May audit: ~9 proposals/day, 0 execution-ready (spread/price blocks dominated).
- Current: **57.8/day** created, **0.7%** linked to trades in window.
- Downstream readiness improved if link rate > 0; scoring attrition still expected for momentum filters.

# Scalp Lifecycle Maturity

**Combined: 3.25 / 5** (raw 3.25) — meets 4.5: **False**  
_Generated: 2026-06-29T02:21:23.262404+00:00_  
_Source: `python3 scripts/compute_scalp_lifecycle_maturity.py --json`_  

> **Operator correction 2026-06-28:** combined maturity separates a mature engineering/control lifecycle from an immature empirical strategy lifecycle. There is no sufficient confirmed momentum_scalp paper-trade sample, so 4.5 is NOT met.

- Engineering / control maturity: **3.25 / 5**
- Empirical strategy maturity: **0.333 / 5** (validation sample: INSUFFICIENT_SAMPLE (2/30 confirmed closed); confirmed closed = 2)
- Momentum Scalp lifecycle: **3.8 / 5**
- Social Scalp lifecycle: **2.5 / 5**

| Dimension | Weight | Score | Points/5 |
|-----------|--------|-------|----------|
| Strategy config consistency | 15% | 1.0 | 0.75 |
| Intraday TTL / window enforcement | 15% | 1.0 | 0.75 |
| Social-only catalyst discipline | 15% | 0.0 | 0.0 |
| Route policy correctness | 15% | 1.0 | 0.75 |
| Liquidity / data-freshness handling | 10% | 0.0 | 0.0 |
| End-to-end traceability | 10% | 0.0 | 0.0 |
| Empirical funnel evidence | 10% | 1.0 | 0.5 |
| Outcome-learning loop | 10% | 1.0 | 0.5 |

## Caps applied

- Cap **3.8** (not binding): social-only could send GO-style alert
- Cap **4.1** (not binding): no end-to-end traceability
- Cap **4.4** (not binding): validation sample not met (2/30 confirmed closed — still TESTING)

## Evidence

| Check | Result |
|-------|--------|
| config_ok | True |
| expiry_test | True |
| window_test | True |
| alerts_test | False |
| route_test | True |
| liquidity_test | False |
| trace_test | False |
| no_bypass_test | True |
| config_test | True |
| trace_cols_present | True |
| funnel_runs | True |
| funnel_gate_met | False |
| closed_paper_trades | 2 |
| outcome_runs | True |

> Earned from machine evidence, bounded by hard caps. Engineering/control lifecycle is mature; the EMPIRICAL strategy lifecycle is not, because there is no sufficient confirmed momentum_scalp paper-trade sample (operator correction 2026-06-28). A zero confirmed sample caps combined at 4.3; a 1–29 sample caps at 4.4. No broker writes. LLMs advisory only; operator/2FA path unchanged and out of scope.


# Scalp Lifecycle Maturity

**Combined: 4.4 / 5** (raw 5.0) — meets 4.5: **False**  
_Generated: 2026-06-28T03:26:39.330317+00:00_  
_Source: `python3 scripts/compute_scalp_lifecycle_maturity.py --json`_  

- Momentum Scalp lifecycle: **4.4 / 5**
- Social Scalp lifecycle: **4.4 / 5**

| Dimension | Weight | Score | Points/5 |
|-----------|--------|-------|----------|
| Strategy config consistency | 15% | 1.0 | 0.75 |
| Intraday TTL / window enforcement | 15% | 1.0 | 0.75 |
| Social-only catalyst discipline | 15% | 1.0 | 0.75 |
| Route policy correctness | 15% | 1.0 | 0.75 |
| Liquidity / data-freshness handling | 10% | 1.0 | 0.5 |
| End-to-end traceability | 10% | 1.0 | 0.5 |
| Empirical funnel evidence | 10% | 1.0 | 0.5 |
| Outcome-learning loop | 10% | 1.0 | 0.5 |

## Caps applied

- Cap **4.4** (from 5.0): validation sample not met (momentum_scalp still TESTING)

## Evidence

| Check | Result |
|-------|--------|
| config_ok | True |
| expiry_test | True |
| window_test | True |
| alerts_test | True |
| route_test | True |
| liquidity_test | True |
| trace_test | True |
| no_bypass_test | True |
| config_test | True |
| trace_cols_present | True |
| funnel_runs | True |
| funnel_gate_met | False |
| closed_paper_trades | 3 |
| outcome_runs | True |

> Earned from machine evidence, bounded by hard caps. momentum_scalp remains TESTING until its validation gate (≥30 closed paper trades, ≥6 months) is met; that gate caps the combined score at 4.4. No broker writes. LLMs advisory only; operator/2FA path unchanged and out of scope.


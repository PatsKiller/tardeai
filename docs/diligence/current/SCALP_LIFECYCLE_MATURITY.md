# Scalp Lifecycle Maturity

Status:      ACTIVE
as_of:       2026-06-28T22:49:34-04:00
Measured at: efcc51365 / not measured

**Combined: 4.4 / 5** (raw 5.0) — meets 4.5: **False**
_Generated: 2026-06-29T02:47:51.568824+00:00_
_Source: `python3 scripts/compute_scalp_lifecycle_maturity.py --json`_

> **Operator correction 2026-06-28:** combined maturity separates a mature engineering/control lifecycle from an immature empirical strategy lifecycle. There is no sufficient confirmed momentum_scalp paper-trade sample, so 4.5 is NOT met.

- Engineering / control maturity: **5.0 / 5**
- Empirical strategy maturity: **0.333 / 5** (validation sample: INSUFFICIENT_SAMPLE (2/30 confirmed closed); confirmed closed = 2)
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

- Cap **4.4** (from 5.0): validation sample not met (2/30 confirmed closed — still TESTING)

## Evidence

| Check | Result |
|-------|--------|
| config_ok | True |
| _test_states | {'expiry_test': 'PASS', 'window_test': 'PASS', 'alerts_test': 'PASS', 'route_test': 'PASS', 'liquidity_test': 'PASS', 'trace_test': 'PASS', 'no_bypass_test': 'PASS', 'config_test': 'PASS'} |
| _indeterminate | [] |
| expiry_test | True |
| window_test | True |
| alerts_test | True |
| route_test | True |
| liquidity_test | True |
| trace_test | True |
| no_bypass_test | True |
| config_test | True |
| evidence_interpreter | /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python |
| trace_cols_present | True |
| funnel_runs | True |
| funnel_gate_met | False |
| closed_paper_trades | 2 |
| outcome_runs | True |

> Earned from machine evidence, bounded by hard caps. Engineering/control lifecycle is mature; the EMPIRICAL strategy lifecycle is not, because there is no sufficient confirmed momentum_scalp validation-trade sample (operator correction 2026-06-28). A zero confirmed sample caps combined at 4.3; a 1–29 sample caps at 4.4. Strategy maturity 4.5+ is NOT claimed. Source maturity (4.5-ready) is reported separately and does not lift this score. No broker writes. LLMs advisory only; operator/2FA path unchanged and out of scope.


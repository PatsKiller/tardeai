# ATM Re-enable — John's 7 Decisions

**Status:** PENDING — John must approve before any ATM mode change
**Date:** 2026-05-22

---

## Decision 1: Which accounts are eligible?

| Option | Risk | Recommendation |
|--------|------|----------------|
| **Paper account only** | Minimal — paper losses don't affect real capital | **RECOMMENDED NOW** |
| Paper + limited test | Low — but adds complexity | After burn-in |
| Live accounts | HIGH — no strategy proof yet | **BLOCKED** |

**Recommended:** Paper account only. Live accounts blocked until strategy proof ≥ 6.0.

---

## Decision 2: Max daily ATM entries?

| Option | Risk | Recommendation |
|--------|------|----------------|
| **1/day** | Conservative — slowest learning but safest | **RECOMMENDED (burn-in)** |
| 2/day | Moderate — reasonable after clean burn-in | After 3-5 clean days |
| 3+/day | Aggressive — overtrading risk | Not recommended |

**Recommended:** 1/day for first burn-in week, then 2/day after clean results.

---

## Decision 3: Max concurrent ATM positions?

| Option | Risk | Recommendation |
|--------|------|----------------|
| 1 | Very safe but slow learning | Acceptable |
| **2** | Good balance of safety and data collection | **RECOMMENDED** |
| 3+ | Correlation risk, harder to monitor | Not for burn-in |

**Recommended:** 2 max during burn-in.

---

## Decision 4: Max per-trade risk?

| Option | Risk | Recommendation |
|--------|------|----------------|
| **0.10%** | ~$120 paper risk per trade | **RECOMMENDED (burn-in)** |
| 0.25% | ~$300 paper risk | Acceptable after burn-in |
| 0.50% | ~$600 paper risk | Not for burn-in |

**Recommended:** 0.10% during burn-in (~$120 paper risk per trade at $1.2M portfolio).

---

## Decision 5: Max daily loss?

| Option | Risk | Recommendation |
|--------|------|----------------|
| **0.25%** | ~$300 daily paper loss limit | **RECOMMENDED** |
| 0.50% | ~$600 — may mask issues | After burn-in |
| 1.00% | ~$1,200 — too permissive | Not recommended |

**Recommended:** 0.25% (~$300) triggers ATM pause.

---

## Decision 6: Which strategies are allowed?

| Option | Risk | Recommendation |
|--------|------|----------------|
| **None / observe only** | Safest — dry-run only | Default until approved |
| Hand-approved list | Good — curated quality | **RECOMMENDED** |
| All TESTING | Risky — includes unproven strategies | Not recommended |
| All | Dangerous | **BLOCKED** |

**Recommended:** Hand-approved list only. Each strategy must have:
- Valid route audit
- Valid strategy_id (exists in YAML)
- Fresh quote capability
- R:R ≥ 2.0 computed
- Broker stop protection confirmed
- No classifier health blocker
- No unresolved strategy mismatch

**Initial candidates** (based on today's ATM activity):
- `dividend_growth_compounder` (4 approved today)
- `reit_income` (1 approved)
- `core_growth_compounder` (1 approved)

---

## Decision 7: Broker-native stops mandatory before entry?

| Option | Risk | Recommendation |
|--------|------|----------------|
| **Yes, hard required** | Safest — broker protects even if software dies | **RECOMMENDED** |
| Yes, with emergency fallback | Acceptable — auto-place if bracket fails | Acceptable |
| No, software-only | DANGEROUS — cron failure = unprotected position | **NOT RECOMMENDED** |

**Recommended:** Hard required. No broker-native stop = no ATM entry.
STOP-V2.1 reconciliation verifies stops exist after entry.

---

## Summary

| Decision | Recommended Answer |
|----------|-------------------|
| 1. Accounts | Paper only |
| 2. Max daily entries | 1/day (burn-in), then 2/day |
| 3. Max concurrent | 2 |
| 4. Per-trade risk | 0.10% (~$120) |
| 5. Daily loss limit | 0.25% (~$300) |
| 6. Strategies | Hand-approved list only |
| 7. Broker stops | Hard required |

# Candidate Freshness Architecture — Design Memo

**Status:** DESIGN, APPROVED, NOT YET IMPLEMENTED
**Date:** 2026-05-15
**Trigger:** Operator question + signal freshness audit + screener filter population fix
**Prerequisite:** Strategy classifier bug fixed in commit 409c055 (2026-05-15)
**Target Implementation:** Phase B-1 (~2026-05-29 onward, post A-6)

## Problem Statement

The Trade AI v12 system treats every screener-derived candidate signal as
same-day-expiring via the `fired_at::date = CURRENT_DATE` filter in
`auto_proposal_generator.py` line 208. This works for intraday momentum
strategies where setups are point-in-time, but it's wrong for slower
strategies where company fundamentals or technical setups persist for
weeks. The audit found:

- Repeat rates of 6-25% per strategy (most tickers don't re-appear naturally)
- No tickers appearing on 3+ days in 30 days for any strategy
- The incubator system already provides multi-day persistence for some strategies
- Strategy classifier bug (now fixed in 409c055) had inflated cross-strategy
  ticker overlap by counting social signals toward strategy matches

## Design Principle

Freshness should be per-strategy, not system-wide. A momentum_scalp
candidate and a bond_income candidate have fundamentally different decay
curves and should expire on different timescales.

The right architecture is three buckets.

---

## Bucket 1 — Same-Day Expiry (Intraday Signals)

### Strategies
- momentum_scalp
- gap_and_go

### TTL: 4 hours from fire, max 1 trading day

### Rationale
These setups die when the market closes. Gap fades by midday. RVOL spike
is meaningful only while it's happening. Pre-market signals from 04:00
should NOT generate post-open proposals at 11:00 — they're stale.

### Persistence Mechanism
- Signal entered -> 4-hour countdown begins
- Signal not promoted within window -> discarded permanently
- No incubator path for these strategies (or strict 4h limit in incubator)

### What Gets Re-Evaluated
- Nothing. These are one-shot signals. If the scalp didn't fire when the
  signal was hot, it doesn't fire at all.

---

## Bucket 2 — Multi-Day Watch Pool (Setup Confirmation Window)

### Strategies (with per-strategy TTL)

| Strategy | TTL | Reasoning |
|---|---|---|
| earnings_post_momentum | 5 trading days | Post-earnings drift window |
| earnings_pre_buildup | Until earnings_date | Event-tied, dies at announce |
| earnings_catalyst | Until earnings + 2 days | Allows post-event read |
| swing_breakout | 10 trading days | Breakout follow-through window |
| swing_trade | 10 trading days | Multi-day swing setup |
| speculative_growth | 10 trading days | Growth breakout patience |
| recovery_watch | 15 trading days | Multi-week recovery thesis |
| fib_retracement_bounce | 20 trading days | Fib retracement timeframe |
| sector_rotation | 20 trading days | Sector trends 2-4 week cycles |

### Persistence Mechanism
- Candidate enters strategy_watchpool table on first qualification
- Row tracks: entered_at, strategy_id, symbol, entry_snapshot
  (price/RSI/vol at entry), last_evaluated_at, evaluation_count,
  expires_at, current_status (ACTIVE | TRIGGERED | EXPIRED | FAILED_CRITERIA)
- Daily re-evaluation cron checks current price/RSI/volume against
  strategy criteria
- If still qualifies -> row marked last_evaluated_at = NOW()
- If explicitly fails criteria -> row marked current_status = FAILED_CRITERIA
- If TTL expires without triggering -> row marked current_status = EXPIRED
- New scan adds row only if symbol not already ACTIVE for that strategy

### What Gets Re-Evaluated Daily
- Current price within strategy's price band
- Current RSI within strategy's RSI band
- Current volume above strategy's volume floor
- Earnings date for earnings-tied strategies
- Sector rotation: still in leading sector?

---

## Bucket 3 — Long-Cycle Pool (Fundamental Persistence)

### Strategies (with per-strategy TTL)

| Strategy | TTL | Reasoning |
|---|---|---|
| dividend_growth_compounder | 60 days | Quality dividends are structural |
| income_add | 60 days | Income setups stable for quarters |
| bond_income | 60 days | Bond ETF characteristics stable |
| high_yield_income_bdc | 60 days | BDC/CEF income persistence |
| reit_income | 60 days | REIT cash flow cycles |
| international_dividend | 60 days | International dividend cycles |
| covered_call_income | 30 days | Beta/IV shifts monthly |
| core_growth_compounder | 90 days | Quarterly fundamental rebalance |
| core_index | 90 days | Index composition is quarterly |
| defense_thesis | 30 days | Sector thesis with technical overlay |
| tax_loss_harvest | 365 days | Wash-sale 30+30 day cycle, full year tracking |
| cash_or_stable | 60 days | Low-risk parking, stable characteristics |

### Persistence Mechanism
- Same strategy_watchpool table as Bucket 2
- Re-evaluation is less frequent -- weekly for most, monthly for
  core_index/core_growth, quarterly for tax_loss_harvest
- Full screener re-scan runs at re-evaluation cadence (not daily)

### What Gets Re-Evaluated

Weekly (Bucket 3 default):
- Current dividend yield (cut detection)
- Current payout ratio (deterioration)
- Beta drift (covered_call_income especially)
- Price vs SMA200 (still in trend?)

Monthly:
- ROE, gross margin, EPS growth (core_growth_compounder)
- Sector exposure (defense_thesis)

Quarterly:
- Tax loss positions (tax_loss_harvest -- only relevant near year-end)

---

## Cross-Cutting Concerns

### Concern 1 — Strategy Classifier Already Fixed

Audit found MLGO, RCEL, SIBN mapped to 16-18 strategies each. Fixed in
commit 409c055 by removing social/YouTube/sentiment from the 2-match
minimum. With classifier fixed, watchpool entries will reflect real
strategy alignment, not inflated overlap.

### Concern 2 — Avoid Stale Triggers

Bucket 2 and 3 watch pool entries carry an entry_snapshot. When the row
triggers a proposal, the proposal generator must use current
price/RSI/volume, not the snapshot values. The snapshot is for audit only.

### Concern 3 — Avoid Pool Bloat

At 79 rows/day across 20 strategies, with TTLs ranging from 5 to 365
days, the watchpool could plausibly hold 3,000-8,000 ACTIVE rows. That's
manageable but worth monitoring. Add an index on (strategy_id,
current_status, expires_at) to keep queries fast.

If the pool ever exceeds 10,000 active rows, that's a signal something's
wrong.

### Concern 4 — Backward Compatibility

Bucket 1 (momentum_scalp, gap_and_go) should NOT use the watchpool --
same-day expiry can stay on the current fired_at::date = CURRENT_DATE
path. This preserves the fast path and limits the architectural change
blast radius.

### Concern 5 — Re-Discovery Counts

If a Bucket 2/3 candidate expires and is re-discovered by a future scan,
the new entry is fresh. Track this in a prior_expiry_count column for
analytics.

---

## Schema Sketch (Not Implementation)

```sql
CREATE TABLE strategy_watchpool (
    id BIGSERIAL PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    screener_id TEXT NOT NULL,
    entered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    entry_snapshot JSONB NOT NULL,
    last_evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    evaluation_count INT NOT NULL DEFAULT 1,
    expires_at TIMESTAMPTZ NOT NULL,
    current_status TEXT NOT NULL DEFAULT 'ACTIVE',
    triggered_at TIMESTAMPTZ,
    triggered_proposal_id BIGINT REFERENCES paper_trade_proposals(id),
    failed_reason TEXT,
    prior_expiry_count INT NOT NULL DEFAULT 0,
    bucket TEXT NOT NULL,
    CONSTRAINT unique_active_per_strategy UNIQUE (strategy_id, symbol, current_status)
        DEFERRABLE INITIALLY DEFERRED
);
```

TTL config lives in strategy YAML files (one source of truth):

```yaml
# strategies/defense_thesis.yaml
freshness:
  bucket: LONG_CYCLE
  ttl_days: 30
  eval_cadence: weekly
```

---

## Implementation Phasing (Phase B-1)

### Phase B-1a: Classifier Verification (Defensive)
- Verify 409c055 classifier fix held through observation window
- Add metric: max strategies per ticker over rolling 7d window

### Phase B-1b: Schema + Bucket 1 No-Op Migration
- Create strategy_watchpool table
- Add freshness config to strategy YAMLs
- Keep momentum_scalp + gap_and_go on existing fast path

### Phase B-1c: Bucket 2 Migration (5 strategies first)
- Migrate: swing_breakout, swing_trade, earnings_post_momentum,
  recovery_watch, fib_retracement_bounce
- Daily re-evaluation cron
- 7-day before/after comparison

### Phase B-1d: Bucket 3 Migration (12 strategies)
- Migrate: all dividend/income/quality/core_growth/defense strategies
- Weekly re-evaluation cron
- 14-day before/after comparison

### Phase B-1e: Cleanup
- Drop legacy fired_at::date filter from Bucket 2/3 strategies
- Add watchpool stats to morning brief

---

## Sequencing

1. 2026-05-15 -- Classifier bug fixed (commit 409c055)
2. 2026-05-15 -- This memo committed
3. 2026-05-16 to 2026-05-20 -- Observe clean post-fix candidate data
4. 2026-05-21 -- A-5 honest decisions on validated pipeline
5. 2026-05-22 -- A-3 second-wave activation
6. 2026-05-23+ -- A-6 Phase A wrap-up
7. 2026-05-26+ -- Phase B-1 begins with classifier verification

## References

- Classifier fix: commit 409c055
- Schedule rebalance: commit 4bb0a92
- Roadmap: docs/strategy/BOT_MATURITY_ROADMAP_v1.md

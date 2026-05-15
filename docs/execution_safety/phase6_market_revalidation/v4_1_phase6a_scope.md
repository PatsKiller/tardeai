# Phase 6A Scope — Paper Approval Market Revalidation Hardening

**Date:** 2026-05-15
**Phase:** 6A
**Status:** IN PROGRESS

## 1. Purpose

Phase 6A hardens the paper trade proposal approval flow by adding a mandatory live market revalidation gate. No paper proposal can be approved using stale pricing or historical market data captured at proposal creation time. Every approval must pass real-time market validation before the risk gate, paper trade creation, or Alpaca paper submission.

**Phase 6A does not enable live trading. It hardens the paper proposal approval path so stale/unfavorable proposals cannot become paper trades.**

## 2. Existing Approval Flow (BEFORE)

```
User clicks Approve
  → Risk Gate check
    → Create paper_trades record (status=pending)
      → Update proposal to APPROVED_FOR_PAPER_TEST
        → Instant Alpaca paper order submission
```

The risk gate checked portfolio-level risk (position sizing, max exposure, daily loss), but did NOT verify whether the trade's entry price, stop, target, and R:R still made sense against the current market.

## 3. New Approval Flow (AFTER)

```
User clicks Approve
  → Live Market Revalidation (NEW GATE)
    → Risk Gate check
      → Create paper_trades record (status=pending)
        → Update proposal to APPROVED_FOR_PAPER_TEST
          → Instant Alpaca paper order submission
```

The live market revalidation gate runs FIRST, before anything else. If it fails, the approval is blocked and no paper trade is created.

## 4. Why Live Market Revalidation Is Required

Proposals are created from screener signals that may be minutes to hours old. Between creation and approval:
- Price may have moved significantly (earnings, news, momentum exhaustion)
- Stop may already be breached
- R:R ratio may have degraded below acceptable thresholds
- Liquidity may have dried up (wide spreads)
- Market may have closed (after-hours spreads unreliable)

Without revalidation, approving a stale proposal would create a paper trade with incorrect entry assumptions, leading to immediate stop-outs, poor R:R, or slippage on wide spreads.

## 5. Block Conditions

| Condition | Threshold | Behavior |
|-----------|-----------|----------|
| No live quote | N/A | **BLOCK** — cannot verify any market conditions |
| Stale quote | > 15 minutes | **BLOCK** — quote data too old to trust |
| Price drift | > 3% from proposed entry | **BLOCK** — trade parameters are stale |
| Stop breached | Current price <= stop (long) | **BLOCK** — would immediately stop out |
| Wide spread | > 1.5% | **BLOCK** — execution risk too high |
| R:R degraded | < 1.2:1 at current price | **BLOCK** — reward no longer justifies risk |

## 6. Warning/Pass Condition

| Condition | Threshold | Behavior |
|-----------|-----------|----------|
| Moderate price drift | 1.5% — 3% | **PASS with WARNING** — entry recalibrated to current live price |

When entry is recalibrated, the adjusted entry flows through to dollar_size, dollar_risk, and the paper trade record.

## 7. API Response Requirements

The `/api/v2/paper-proposals/approve` endpoint returns a `market_revalidation` object in all responses (success and failure):

```json
{
  "market_revalidation": {
    "passed": true/false,
    "symbol": "AAPL",
    "live_price": 294.22,
    "provider": "alpaca",
    "quote_age_seconds": 3,
    "price_drift_pct": 0.8,
    "live_rr": 2.1,
    "live_spread_pct": 0.03,
    "adjusted_entry": null,
    "blockers": [],
    "warnings": [],
    "message": "Market conditions confirmed..."
  }
}
```

## 8. Dashboard/Operator Visibility

The dashboard should display:
- Block reason when approval fails
- Warning details when entry is adjusted
- Live price vs proposed entry comparison
- R:R at current price
- Quote provider and freshness

## 9. Out of Scope

- Live trading enablement
- Broker credential changes
- Holdings modifications
- New execution strategies
- Changes to existing risk gate thresholds
- After-hours execution policy (future Phase 6 item)
- Approval simulator (future Phase 6 item)
- Automated approval (proposals still require manual approve action)

## 10. Safety Gates

| Gate | Status |
|------|--------|
| ALPACA_MODE=paper | **ENFORCED** |
| LLM_DISABLE_LIVE_EXECUTION=true | **ENFORCED** |
| Risk gate fail-closed | **PRESERVED** |
| Market revalidation fail-closed | **NEW** |
| Holdings.json authority | **UNCHANGED** |
| No broker modification without admin | **UNCHANGED** |

## 11. Rollback Plan

```bash
# Revert the revalidation gate commit
git revert 3758b0b

# Or: disable revalidation by reverting paper_trade_logger.py
git checkout 3758b0b~1 -- scripts/paper_trade_logger.py scripts/api_v2.py
```

**Emergency policy:** Do not disable revalidation without operator approval. Preferred emergency action is to block paper approvals entirely, not bypass revalidation.

## 12. No Live Trading Statement

Phase 6A operates exclusively within the paper trading domain. No changes affect live order routing, broker credentials, account settings, or execution pathways. ALPACA_MODE remains `paper`. LLM_DISABLE_LIVE_EXECUTION remains `true`. The holdings.json file is not modified.

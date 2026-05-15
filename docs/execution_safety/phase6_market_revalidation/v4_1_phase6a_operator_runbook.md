# Phase 6A Operator Runbook — Paper Approval Market Revalidation

**Date:** 2026-05-15

## 1. How the Approval Flow Works

When you click "Approve" on a paper proposal in the dashboard:

```
1. Fetch live quote for the symbol (Alpaca → Polygon → Finnhub → FMP → yfinance)
2. Validate against 6 market conditions:
   → No quote? BLOCK
   → Quote > 15 min old? BLOCK
   → Price drift > 3%? BLOCK
   → Stop already breached? BLOCK
   → Spread > 1.5%? BLOCK
   → R:R < 1.2:1? BLOCK
   → Drift 1.5-3%? WARN, adjust entry to live price, PASS
   → All clear? PASS
3. Run risk gate (position sizing, max exposure, daily loss limits)
4. Create paper trade record (status=pending)
5. Submit bracket order to Alpaca paper
```

## 2. What Blocks Approval

| Condition | Threshold | What It Means |
|-----------|-----------|---------------|
| No live quote | N/A | Market data unavailable — can't verify conditions |
| Stale quote | > 15 min | Data too old to trust for execution |
| Price drift | > 3% | Price moved significantly since proposal was created |
| Stop breached | price <= stop | Would immediately stop out |
| Wide spread | > 1.5% | Liquidity too thin — execution cost too high |
| R:R degraded | < 1.2:1 | Reward no longer justifies the risk |

## 3. What Warnings Mean

| Warning | Meaning | Action Taken |
|---------|---------|-------------|
| price_adjusted | Price drifted 1.5-3% | Entry recalibrated to current live price |

When you see "Approved with adjustment", the system used the live price instead of the original proposed entry. This affects dollar_size, dollar_risk, and the paper trade record.

## 4. What the Dashboard Shows

**On block:**
```
Not a good trade under current conditions: AAPL spread is 10.57%,
too wide for safe execution. Wait for tighter liquidity.

Live: $294.22 | Drift: 0.5% | R:R: 1.8 | Spread: 10.57%
```

**On success:**
```
PAPER TRADE #123 opened from proposal #45. Market conditions confirmed:
AAPL at $150.50 (drift 0.3%), R:R=2.1:1. Approved.

Live: $150.50 | Drift: 0.3% | R:R: 2.1
```

## 5. How to Test Manually

```bash
# Test the pure validation function with mock data
.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
from paper_trade_logger import validate_paper_proposal_live_market
from datetime import datetime, timezone
import json

result = validate_paper_proposal_live_market(
    'AAPL', 150.0, 145.0, 165.0, 40,
    {'last_price': 151.0, 'bid': 150.9, 'ask': 151.1, 'spread_pct': 0.13,
     'quote_timestamp': datetime.now(timezone.utc)})
print(json.dumps(result, indent=2, default=str))
"

# Run the wrapper with real market data (fetches live quote)
.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
from paper_trade_logger import _revalidate_market_conditions
import json
result = _revalidate_market_conditions('AAPL', 150.0, 145.0, 165.0, 40)
print(json.dumps(result, indent=2, default=str))
"

# Run unit tests (24 tests)
.venv/bin/python tests/test_phase6_market_revalidation.py

# Run API mock validation (7 scenarios)
.venv/bin/python scripts/test_phase6_market_revalidation_api.py
```

## 6. How to Interpret market_revalidation

```json
{
  "passed": false,              // Did it pass? false = blocked
  "live_price": 294.22,         // Current market price
  "provider": "alpaca",         // Quote source
  "quote_age_seconds": 3,       // How old the quote is
  "price_drift_pct": 50.9,      // How far price moved from proposal
  "live_rr": null,              // Risk:Reward at current price
  "live_spread_pct": 10.57,     // Bid-ask spread percentage
  "adjusted_entry": null,       // Recalibrated entry (if drift 1.5-3%)
  "blockers": ["price_drift..."], // Why it was blocked
  "warnings": [],               // Non-blocking issues
  "message": "Not a good trade..." // Human-readable explanation
}
```

## 7. Rollback

```bash
# Revert the entire Phase 6A commit
git revert <phase6a-commit-hash>

# Or revert just the code files (keep docs)
git checkout <pre-6a-commit> -- scripts/paper_trade_logger.py scripts/api_v2.py apps/command-center-v2/src/pages/PaperProposals.tsx
```

## 8. Emergency Procedures

**Do NOT disable revalidation without operator approval.**

Preferred emergency actions (in order):

1. **Block all paper approvals** — set proposals to RISK_BLOCKED in DB
2. **Investigate the issue** — check quote provider, market hours, network
3. **If revalidation is genuinely broken** — revert the commit (see above)

**Never** skip revalidation to push through an approval.

## 9. Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| "No live price available" | All quote providers failed | Check network, Alpaca API key, market hours |
| "Quote is X min old" | Quote API returned stale data | Wait for fresh quote; check if market is open |
| "Spread is X%, too wide" | After-hours or illiquid stock | Approve during regular trading hours only |
| "Stop breached" | Price dropped below stop | Proposal is invalid — reject and create new one |
| "R:R degraded" | Price moved, reward shrunk | Proposal is stale — reject and create new one |
| "Price drift X%" | Significant price movement | Proposal is stale — reject and create new one |
| "Approved with adjustment" | 1.5-3% drift | Entry recalibrated — check new entry is acceptable |

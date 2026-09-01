# 7 Triggered Stops — Pre-Schwab Verification

Status:      HISTORICAL
as_of:       2026-05-23T19:19:59-04:00
Measured at: efcc51365 / not measured

Generated Sunday evening 2026-05-23 before market open Monday 2026-05-25 09:35 ET.

## Positions with Price Below Stop

| Symbol | Account | Qty | Last | Stop | Dist% | MktVal |
|--------|---------|-----|------|------|-------|--------|
| KBR | schwab_taxable | 15 | $33.42 | $33.50 | -0.2% | $501 |
| LDOS | schwab_taxable | 5.2 | $126.17 | $142.76 | -13.1% | $657 |
| LHX | schwab_taxable | 2.5 | $312.15 | $322.32 | -3.3% | $786 |
| LMT | schwab_taxable | 1.4 | $533.63 | $590.00 | -10.6% | $750 |
| NOC | schwab_taxable | 1.2 | $557.33 | $612.04 | -9.8% | $683 |
| PFLT | schwab_taxable | 1025.3 | $8.12 | $8.21 | -1.1% | $8,326 |
| RTX | schwab_taxable | 4.5 | $176.86 | $180.71 | -2.2% | $792 |

**Total at-risk value: ~$12,500**

## Operator Action

Compare these values against Schwab account. For each symbol:
- If Schwab shows position FLAT (shares = 0) → broker filled, system will sync overnight
- If Schwab shows position OPEN with price below stop → broker missed, decide:
  - Place manual sell at market open
  - Cancel and replace the stop at current price
  - Hold (acknowledge no protection, document why)

## Context

These are all schwab_taxable positions with stops tracked in risk_management.json but no broker GTC stop orders (no stop_order_id). The risk page correctly flags them as TRIGGERED based on distance_pct < 0 (price below stop level). These are notional/planned stops, not broker-submitted orders.

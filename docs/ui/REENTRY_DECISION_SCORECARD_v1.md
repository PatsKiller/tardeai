# Re-Entry Decision Scorecard v1

**Route:** `/v3/portfolio/re-entry`  
**Library:** `apps/command-center-v3/src/lib/reentryDecisionScorecard.ts`  
**UI:** `ReEntryCommandHeader` + expanded row scorecard in `ReEntryCurrentIntelligence`

## Purpose

Tell the operator **what is ready to review now**, **what is near**, and **why** — without auto-executing.

Safety boundary: **advisory only**. No broker calls, orders, approvals, or 2FA.

## Lanes

| Lane | State | Operator meaning |
|------|-------|------------------|
| **NOW** | READY TO REVIEW | Price inside validated entry zone + all hard gates PASS + RSI ≤ 50 |
| **NEAR** | NEAR ENTRY | Within ~3% of zone, or in-zone with residual hard/soft waits |
| **WATCH** | WAIT / HELD / STALE / MISSING * | Monitor; not a clean re-entry review |

Deep-link: `?lane=NOW|NEAR|WATCH|ALL` (default NOW). Optional `?symbol=SYM` focuses and expands that row.

## Hard gates (must pass for NOW)

| Gate | Pass | Fail / UNAVAILABLE |
|------|------|--------------------|
| Market quote + RSI | Price and RSI present | MISSING MARKET |
| Evidence freshness | `asOf` ≤ 96h (default) | STALE |
| Validated entry zone | Entry low–high present | MISSING PLAN |
| Price vs entry zone | Inside zone | WAIT if outside / near |
| RSI not extended | RSI ≤ 50 for READY; ≤ 55 for NEAR band | WAIT if elevated / overbought |

## Soft gates (informational; do not alone block READY)

| Gate | Intent |
|------|--------|
| MA structure | Price vs MA50 / MA200 |
| MACD histogram | Positive or improving slope |
| Above support | Price ≥ marked support |
| Resistance context | Reclaimed / testing / below |
| Valuation | Soft WAIT if P/E extreme (>80) |
| Risk regime | Soft WAIT if risk-off / defensive |

## Terminal overrides

- **CURRENTLY HELD** → WATCH (manage as holding)
- **STALE** → WATCH (refresh inputs)
- **MISSING PLAN** → WATCH (build entry zone)
- **MISSING MARKET** → WATCH (refresh quotes)

## Display contract

Each row shows:

- State + action + plain-English reason
- Lane badge + `scoreLabel` (`N/M hard · X/Y soft · Z n/a`)
- Expand → full gate table: state · hard/soft · label · current · threshold · why
- Levels: support, resistance, stop, target, MA20/50/200, MACD, P/E

## Fail-closed rules

1. Missing evidence → **UNAVAILABLE**, never fake PASS.
2. Stale timestamps → **STALE**, never READY.
3. No inventing exit shares or prices (exit evidence layer).
4. Alerts elsewhere remain advisory; scorecard READY is not an order.

## Relation to rotation six-gate

| Product | Use |
|---------|-----|
| **This scorecard** | Symbol-level “should I review re-entry?” timing |
| **Rotation six-gate** | Confirmed capital lineage return-to-growth monitor |

They share levels extractors where possible but remain labeled as separate products on the desk.

## Tests

```bash
node apps/command-center-v3/src/lib/reentryDecisionScorecard.test.ts
```

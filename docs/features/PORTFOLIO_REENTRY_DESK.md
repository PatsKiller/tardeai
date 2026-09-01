# Portfolio Re-Entry Intelligence

Status:      ACTIVE
as_of:       2026-07-23T12:56:26-04:00
Measured at: efcc51365 / not measured

## Purpose

`/v3/portfolio/re-entry` is an advisory, persistent monitor for symbols exited during the trailing twelve months. It answers:

- What did the operator exit, when, and why?
- Was the latest exit identified as a stop or an operator sale?
- What are the current cached price, RSI state, and candidate entry mechanics?
- How far is price from the current candidate pullback zone?
- Which names are ready for review, near the zone, overbought, stale, already held, or missing evidence?
- What long-term role would a renewed position serve?
- Which price and RSI alerts are armed?

It does not create proposals, approvals, orders, broker calls, or 2FA requests.

## Existing sources reused

No second trade ledger or alert engine is introduced.

| Concern | Existing source |
|---|---|
| trailing-year exits | `/api/v2/redeploy/history?days=365` |
| realized closed-trade fallback and rollup | `/api/v2/journal/by-ticker?from=YYYY-MM-DD` |
| cached direct symbol intelligence | `/api/v2/watchlist/items?symbol=SYMBOL` |
| canonical symbol cards | `/api/v2/symbol-cards` |
| RSI/setup advisory | `/api/v2/setup-advisory/candidates?entity=watchlist` |
| current-position exclusion/status | `/api/v2/portfolio/holdings` |
| market regime | `/api/v2/risk-regime/latest` |
| persistent operator classification | `/api/v2/ui/prefs`, key `portfolio.reentry.assignments.v1` |
| persistent price/RSI alerts | `/api/v2/watch/alerts` and `/api/v2/watch/alerts/list` |

The UI accepts historical response aliases defensively because the trade-history endpoints predate a single shared envelope. Missing or stale fields remain visibly unavailable and never become fabricated values.

## Operator classification

One modal stores an explicit primary role:

- `CORE`
- `COMPOUNDING`
- `DIVIDEND`
- `SHORT`
- `SWING`
- `UNASSIGNED`

It also stores priority, monitor state, optional target account/weight, and an operator thesis. The server-owned UI preference makes the classification available across devices instead of depending on browser local storage.

## Deterministic review states

Long-side states use current cached RSI plus the current candidate entry zone:

- `READY_FOR_REVIEW`: price is in the zone and RSI confirms a non-extended setup.
- `NEAR_ZONE`: price is within a bounded distance of the zone with non-overheated RSI.
- `OVERSOLD_REVIEW`: RSI is oversold; this is a review state, not an automatic buy.
- `OVERBOUGHT_WAIT`: RSI is overbought.
- `WATCH`: evidence is current but no review threshold is met.
- `CURRENTLY_HELD`: the symbol has been repurchased and is no longer a clean re-entry candidate.
- `STALE`: the source timestamp exceeds the bounded cache age.
- `NEEDS_DATA`: price, RSI, or same-side entry mechanics are unavailable.

A `SHORT` classification uses only an explicitly bearish/short plan family. It never re-labels a long entry plan as a short plan. Short-side review uses `OVERBOUGHT_REVIEW`, and a short price alert is blocked when no bearish entry mechanics are available.

## Alerts

The modal can arm independent server-side Watch rules:

- `price_cross_below`
- `price_cross_above`
- `rsi_below`
- `rsi_above`

Price and RSI rules notify independently. An alert is not a combined re-entry approval. Fresh data, same-side price-zone agreement, risk/event context, account eligibility, and operator review remain necessary.

## Safety boundary

```text
BROKER CALL: NO
ORDER OR PROPOSAL: NO
APPROVAL MUTATION: NO
2FA: NO
AUTOMATIC RE-ENTRY: NO
RAW SECRET READ: NO
```

The page is persistent and actionable without becoming execution authority.

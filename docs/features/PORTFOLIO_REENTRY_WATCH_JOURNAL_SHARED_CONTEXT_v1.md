# Portfolio Re-Entry, Watch and Journal Shared Context v1

Status:      ACTIVE
as_of:       2026-07-23T19:21:05-04:00
Measured at: efcc51365 / not measured

## Purpose

Re-Entry classification is a first-class operator state, not a label isolated to one page. The same symbol context is visible on Re-Entry, Watch and TradeInView/Journal while preserving the distinction between deterministic source evidence and operator confirmation.

## Classification states

### CLASSIFIED — green

An operator has saved at least one meaningful persistent field: mandate, strategy flag, target account/weight, thesis, exit classification or queue disposition. Green means operator-confirmed, not merely inferred.

### AUTO-TAGGED — amber

The system has useful starting evidence but no operator confirmation. Sources can include broker action/description, real closed-trade journal, current Watch decision packet, sector, regime, earnings date, catalyst, technicals and resistance. Auto-tags remain editable and never masquerade as operator decisions.

### UNCLASSIFIED — gray

Neither an operator classification nor adequate deterministic starting evidence exists.

## Exit reason inference

Before a modal opens, the system interprets explicit source language:

- stop, stop-loss, trailing stop or protective stop → stopped out
- partial, trim or reduce → partial trim
- assignment or expiration → assignment/expiration
- intraday, scalp, round trip or day trade → momentum scalp
- sell, sold, closed or exit → discretionary sale

The operator can replace the inferred type, reason and notes before saving.

## Shared context cache

The scheduled Watch alert evaluator refreshes `portfolio.shared-symbol-context.v1` in the same RTH pass as:

- `portfolio.reentry.exit-universe.v1`
- `portfolio.reentry.resistance.v1`
- single-condition Watch alerts
- six-gate rotation-back alerts

For each symbol, the cache can include:

- classification status and saved mandate
- latest exit type, reason, date, account and source
- queue disposition
- Watch recommendation and narrative
- sector and regime
- RSI and trend
- catalyst and earnings date
- resistance state, level, distance, hold count and source
- concise journal annotation

## Journal and Watch behavior

TradeInView/Journal displays a shared annotation panel sourced from the same cache. It does not rewrite historical broker records or silently overwrite behavioral reviews.

Watch displays closed-position context beside its existing decision cards. Watch remains the current technical and decision-packet source; Re-Entry adds exit lineage, classification, rotation and return-monitoring context.

A classification saved on Re-Entry dispatches a browser refresh event so the Watch and Journal bridge can update immediately. The scheduled evaluator later republishes the durable shared cache from database evidence.

## Re-Entry controls

- Every primary row is expandable.
- KPI cards are clickable filters.
- Checkboxes support multi-symbol classification.
- Classification controls remain visible under the ticker.
- Tooltips explain symbol-specific state, price/exit comparison, RSI, pullback, entry mechanics, resistance source, analyst evidence and alerts.

## Resistance provenance

Resistance is displayed with an explicit source:

1. `CLOSED-SESSION CACHE` — preferred, including completed-session hold evidence.
2. `WATCH FALLBACK` — parsed from a current Watch decision-packet trigger when the closed-session cache has no row; hold count remains unavailable.
3. `MISSING EVIDENCE` — neither source provides a valid level, and the UI states why.

## Safety boundary

All context is advisory. No classification state, auto-tag, Watch recommendation, journal annotation, resistance reclaim or alert submits an order, moves capital, changes an approval, or requests 2FA.

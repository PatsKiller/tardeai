# Portfolio Re-Entry + Rotation Intelligence — Requirements Contract v4

Status:      ACTIVE
as_of:       2026-07-23T16:51:42-04:00
Measured at: efcc51365 / not measured

## Operator decisions

The operator selected:

- **1A — Transaction universe:** every real-account sell, including full closes, partial trims, stop-outs, ETF rotations, options assignments/expirations, and same-day unreconciled transactions.
- **2A — Accounts:** every connected real brokerage account, including Schwab, Fidelity, SnapTrade, and future live account sources.
- **3A — Classification storage:** persistent symbol mandate plus separate event-level strategy and exit classification.
- **4A — Rotation matching:** automatically suggest source-to-destination matches using account, timing, and dollar amount, but require operator confirmation.
- **5A — Rotation-back staging:** support full return or configurable tranches, defaulting to 25% / 25% / 50%.

## Baseline truth at authorization

The following statements are part of the acceptance record and must remain visible until independently proven complete:

- Single-symbol exit and re-entry monitoring: **substantially present**.
- Core and combinable sub-flags: **present**.
- Current versus exit price and pullback zone: **present when valid data exists**.
- Complete trend-direction intelligence: **incomplete**.
- Capital lineage and SCHG/SCHD rotation-back intelligence: **not yet implemented**.

The implementation must not silently upgrade an incomplete statement to complete. The UI must expose data age, unavailable fields, and blocking gaps.

## R1 — Authoritative exit universe

The trailing-twelve-month universe must start from real broker transactions, not from a material-proceeds subset or a downstream journal alone.

It must include:

- full position closes;
- partial trims;
- protective and trailing stop fills;
- discretionary sells;
- rebalances and rotations;
- tax-driven sales;
- option assignment, exercise, expiration, and close transactions where they reduce or remove exposure;
- same-day real-account transactions before downstream journal reconciliation completes.

Downstream sources may enrich and reconcile the record, but may not define or reduce the universe. A visible coverage panel must show each source count, latest timestamp, and reconciliation state. Missing or stale authoritative transactions are blocking and must not be presented as a complete year.

## R2 — Shared symbol mandate and event classification

Every symbol has a persistent mandate independent of any single sale event.

### Primary mandate

- CORE HOLDING
- SATELLITE / TACTICAL
- HEDGE
- UNCLASSIFIED

### Independent, combinable strategy flags

- GROWTH
- COMPOUNDING
- DIVIDEND / INCOME
- SWING
- SHORT
- DEFENSIVE
- HEDGE
- ROTATION

Examples that must be representable:

- Core + Growth + Compounding;
- Core + Dividend + Compounding;
- Satellite + Swing;
- Short + Swing;
- Defensive + Dividend;
- Core + Growth with a specific event classified as a defensive rotation.

Each exit event separately stores:

- stopped out;
- discretionary sale;
- partial trim;
- rebalance;
- tax sale;
- rotation;
- assignment / expiration;
- other;
- reason and operator notes;
- source account and destination account constraints.

## R3 — Single-symbol exit and re-entry intelligence

For every exited symbol show:

- all exit events in the trailing twelve months;
- exit date, account, shares, exit price, proceeds, realized P&L, and reason;
- current price;
- absolute and percentage difference from the selected exit;
- RSI and oversold / neutral / overbought state;
- candidate pullback / entry zone;
- distance above, below, or inside the entry zone;
- stop and target;
- current holdings state;
- data freshness and source provenance;
- clear state, next action, and plain-English reason.

No value may be fabricated when the current technical packet is unavailable.

## R4 — Complete trend-direction intelligence

The dashboard must add a direction block for each source and destination ticker:

- 5-day and 20-day price slope;
- 20 / 50 / 200-day moving-average structure;
- price relative to each moving average;
- MACD direction and histogram sign/change;
- relative-strength direction versus the configured benchmark;
- volume confirmation when available;
- improving, deteriorating, constructive, extended, or unavailable trend state;
- directional confidence and invalidation;
- evidence timestamp.

### Resistance intelligence pills

Every row and rotation pair must show, when supported by the source data:

- resistance price;
- current price distance from resistance in dollars and percent;
- ABOVE RESISTANCE, BELOW RESISTANCE, TESTING, or UNAVAILABLE;
- number of closed sessions held above resistance;
- number of resistance tests in the configured lookback;
- breakout / reclaim confirmation state;
- the exact session/date on which the hold count began.

The system must distinguish an intraday cross from a closed-session hold. Unknown hold duration must display UNAVAILABLE rather than zero.

## R5 — Analyst rating intelligence

The page must consume the repository's real analyst-consensus source, not Finviz pseudo-ratings.

For stocks show:

- current consensus label;
- strong-buy / buy / hold / sell distribution;
- analyst count;
- mean, median, high, and low price targets;
- upside or downside to the mean target;
- latest upgrade / downgrade direction and date when available;
- source and age;
- CIO-versus-Street divergence when available.

For ETFs and funds show the separate look-through analyst measure and label it as look-through, not as a direct ETF analyst consensus.

## R6 — ETF and fund look-through

For ETF/fund source and destination symbols show:

- analyst look-through percentage;
- expense ratio;
- distribution yield;
- sector and industry weights;
- top holdings and concentration;
- effective growth, value, dividend/income, defensive, and technology exposure when supported;
- current versus target portfolio weight;
- whether effective exposure increased or decreased after the rotation;
- material issuer overlap between source, destination, and remaining portfolio;
- data provenance and age.

The UI must explicitly answer whether an ETF has been overweighted, underweighted, increased, or reduced after a proposed or confirmed rotation.

## R7 — Rotation Link modal

For a source such as SCHG and temporary destination such as SCHD, the page needs a persistent Rotation Link modal with:

- source position;
- temporary destination;
- account;
- amount moved;
- shares moved;
- source exit date;
- source exit price;
- destination purchase date;
- destination cost per share;
- destination shares;
- reason: volatility reduction, income, defensive posture, tax, or other;
- intended destination duration;
- permanent versus temporary switch;
- target source allocation when returning;
- return mode: full or staged;
- default staged percentages 25% / 25% / 50%, editable and required to total 100%;
- operator thesis and invalidation;
- confirmation status and audit timestamps.

Automatic matching may suggest a link from real transaction lineage using same account, timing, amount, and destination buys, but it must never confirm the link without operator action.

## R8 — Monitor both sides of a confirmed rotation

The resulting pair must monitor:

### Source side

- current price and return-entry zone;
- RSI;
- full trend-direction block;
- relative strength;
- resistance distance and closed-session hold count;
- market-regime fit;
- analyst consensus or ETF look-through analyst measure;
- target allocation and amount required to restore it.

### Destination side

- current value and P&L;
- purchase cost and shares;
- dividend and income earned while parked;
- yield and expense ratio;
- trend and resistance state;
- analyst or look-through intelligence;
- current effective portfolio exposure.

### Pair intelligence

- source-versus-destination return since rotation;
- relative-strength spread and threshold;
- source recovery versus destination opportunity cost;
- tax and wash-sale constraints;
- same-account / cross-account restrictions;
- amount currently available to rotate back;
- partial versus full rotation-back plan;
- remaining destination balance after each tranche;
- explicit no-action reason when any gate blocks.

## R9 — Composite return-to-growth alert

The return alert must not count or fire from one price boolean. It requires all configured mandatory conditions:

1. risk regime turns constructive;
2. source trend changes from deteriorating to improving / constructive;
3. source-versus-destination relative strength reclaims its configured threshold;
4. source enters or confirms its re-entry zone;
5. RSI is constructive but not overbought;
6. no blocking tax, wash-sale, settlement, account, or data-quality constraint.

Each condition must show:

- PASS / WAIT / BLOCK / UNAVAILABLE;
- current value;
- threshold;
- evidence timestamp;
- plain-English explanation.

The alert may be armed only when every mandatory condition has a valid evidence source. It is evaluated by the existing scheduled alert lane and must deduplicate notifications. A notification is advisory only and never creates a proposal, approval, order, 2FA request, or broker call.

## R10 — Integration between Redeploy and Re-Entry

Redeploy and Re-Entry must use the same persistent mandate, event classification, and rotation-link record.

Every Redeploy event overview must include a prominent RE-ENTRY / ROTATION control that opens the shared modal for the selected event and symbol. It must show:

- current mandate and strategy flags;
- selected event classification;
- confirmed or suggested capital destination;
- current return-gate status;
- direct link to the complete Re-Entry workstation.

The operator must not need to classify the same symbol or event independently in two screens.

## R11 — Safety and honesty

- advisory only;
- no broker submission;
- no order creation or modification;
- no automatic capital movement;
- no automatic rotation-link confirmation;
- no real 2FA;
- no inferred tax conclusion presented as legal or tax advice;
- no Finviz field presented as a real analyst rating;
- no intraday resistance cross presented as a closed-session hold;
- no partial ledger presented as complete;
- no composite alert marked armed when required evidence is unavailable.

## Acceptance tests

1. A symbol can be Core + Growth + Compounding + Dividend simultaneously.
2. A separate event for that symbol can be classified as stopped out and defensive rotation.
3. Same-day real-account sells appear before journal reconciliation, with a pending-reconciliation badge.
4. Partial trims and full closes remain distinct events.
5. Automatic SCHG-to-SCHD matching is suggested but not confirmed automatically.
6. A confirmed SCHG-to-SCHD link persists and appears in both Redeploy and Re-Entry.
7. Full and 25/25/50 staged return plans are representable; custom stages must total 100%.
8. Analyst pills use real consensus and target data; ETFs are labeled look-through.
9. Resistance pills show distance, side, closed-session hold count, and start date or UNAVAILABLE.
10. ETF look-through shows whether effective weights increased or decreased.
11. The composite alert cannot arm when any mandatory condition is unavailable.
12. A single price cross cannot fire the composite return alert.
13. No broker write, order, approval, or 2FA path is introduced.

# Portfolio Re-Entry and Rotation Intelligence — Operator Guide

Status:      ACTIVE
as_of:       2026-07-23T16:51:42-04:00
Measured at: efcc51365 / not measured

## Purpose

The Re-Entry workstation preserves every real-account exposure-reducing transaction, separates the long-term ticker mandate from the reason for each exit, and monitors confirmed source-to-destination rotations. It is advisory only. It never moves capital, submits an order, requests 2FA, or confirms a rotation automatically.

## 1. Exit summary math

The front table is grouped by symbol.

- **Executions** is the number of real-account exit transactions in the selected history window.
- **Cumulative shares** is the sum of the absolute exit quantities.
- **Average exit** is the share-weighted average of available execution prices. When a source row has proceeds and shares but no price, proceeds divided by shares is used for that row.
- **Total proceeds** is the sum of absolute exit proceeds.
- Expand a symbol to audit the individual broker rows. Aggregation never replaces or deletes the source transactions.

## 2. Save, review, and suppress

Each exit has one queue disposition.

### Save / monitor long term

Use this for exits that remain relevant to a future re-entry decision. The ticker stays in the active long-term queue and continues to receive the available technical, regime, analyst, resistance, tax, and rotation intelligence.

### Review later

Use this when the exit has not been classified yet. It remains visible but is not represented as an intentional long-term monitor.

### Suppress from Re-Entry

Use this for momentum scalps, day trades, tactical round trips, data noise, or exits that have no long-term re-entry relevance. Suppression hides the item from the default long-term queue. It does not delete the broker transaction, journal evidence, Redeploy event, or audit history.

The scope filter supports:

- Long-term queue, hiding detected/classified scalps and suppressed exits
- All active exits, including scalps
- Day trades and momentum scalps only
- Suppressed items only
- All exits

The checkbox column and **Bulk Classify** action apply a common mandate, multiple strategy flags, event type, and disposition to the selected symbols and their exits. Individual exits can still be edited after expanding a symbol.

## 3. Mandate and event classification

The ticker mandate is persistent and shared with Redeploy.

- Core
- Satellite / Tactical
- Hedge
- Unclassified

Strategy flags are independent and multi-selectable:

- Growth
- Compounding
- Dividend
- Swing
- Short
- Defensive
- Hedge
- Rotation

The exit event remains separate because the same symbol may have different exit reasons over time:

- Stopped out
- Discretionary sale
- Partial trim
- Rebalance
- Tax sale
- Rotation
- Day trade
- Momentum scalp
- Assignment / expiration
- Not relevant
- Other

## 4. Rotation tracking: manual versus automatic

### Manual: confirm the capital lineage

Open **Rotation Link** on the source exit. Enter or verify:

- Source symbol
- Temporary destination
- Account
- Amount and shares moved
- Source exit date and price
- Destination purchase date, cost, and shares
- Reason and intended duration
- Temporary or permanent switch
- Target source allocation
- Full or staged return plan
- Relative-strength reclaim threshold
- Tax, wash-sale, account, and settlement clearances

The system may suggest a same-account destination from current holdings. A suggestion is not lineage. The operator must check **Confirm capital lineage**.

### Automatic: monitor a confirmed pair

After a confirmed Rotation Link is saved and the six-gate monitor is armed, the existing Watch evaluator checks it every 20 minutes during regular trading hours. The evaluator independently recomputes:

1. Constructive risk regime
2. Improving or constructive source trend
3. Source-versus-destination relative-strength threshold reclaimed
4. Source inside the latest validated re-entry zone
5. RSI at least 40 and below 70
6. Tax, wash-sale, account, and settlement constraints all clear

Missing evidence is `UNAVAILABLE`, never `PASS`. Unconfirmed lineage cannot fire.

### Automatic: notify

When all six gates pass, the evaluator writes an `alert_events` record and uses the existing Watch Telegram batch, daily cap, and daily deduplication. The notification means **review rotating back now**.

### Manual: execute the return

The alert never moves money or places an order. Before executing, the operator must re-check current price, size, account capacity, settlement, tax/wash-sale status, entry plan, and the staged or full return percentages.

## 5. Analyst evidence

The page uses the same backend read models as the Watch page:

- `/api/v2/pro-analyst/pills?map=1` for current professional consensus, analyst count, mean target/upside, stale state, and internal-versus-Street divergence
- `/api/v2/analyst-detail?map=1` for rating distribution and mean, median, high, and low targets

When the feed provides a rating-change event, the page displays:

- Upgraded or downgraded
- Prior rating and new rating
- Firm/provider
- Event date

When the feed does not provide a recent change, the page states **No recent change in feed** instead of inferring one.

Analyst evidence is memorialized beside the ticker and used to frame the thesis, review priority, and target-weight discussion. It does not override the entry zone, resistance hold, risk regime, tax constraints, or the six-gate return alert.

## 6. ETF and fund look-through

ETF/fund evidence is labeled **look-through** and is not represented as direct ETF analyst consensus. When available, the page shows expense ratio, yield, underlying sectors, top holdings, concentration, and analyst look-through. Portfolio-wide themes are not relabeled as a specific fund's holdings.

## 7. Resistance and re-entry evidence

The closed-session resistance board shows:

- Resistance price
- Current close
- Above, below, testing, or unavailable
- Distance in dollars/percent when available
- Consecutive completed sessions held above resistance
- Hold-start date
- Test count
- Evidence date

Intraday crosses do not count as completed-session holds.

## 8. Safety boundary

All Re-Entry and Rotation intelligence is advisory. No classification, analyst rating, resistance reclaim, alert, or composite gate authorizes an automatic order. Existing approval, account, risk, and 2FA controls remain unchanged.

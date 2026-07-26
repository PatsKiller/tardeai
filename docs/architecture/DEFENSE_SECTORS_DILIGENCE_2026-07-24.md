# Defense and Sectors Diligence — 2026-07-24

**Scope:** `/v3/defense` and `/v3/sectors` (`/v3/watch?tab=sectors`)  
**Status:** code and methodology review complete; live Tailnet rendering and payload inspection pending  
**Authority:** advisory only; no order, approval, 2FA, broker or production-config authority is created by this work

## Executive finding

The current implementation is substantially stronger than a typical retail sector dashboard. It has deterministic relative-strength states, two-close transition confirmation, portfolio look-through, complete-or-absent recommendation cards, account/risk rails, industry rotation data and model-critique lanes.

It should **not** yet be described as fully validated or enhancement-complete. The main shortcomings are truth hierarchy, mixed-window comparability, breadth precision, source provenance and recommendation calibration. The frontend also blends market facts, portfolio facts, recommendations, model critiques and action controls too closely.

This branch addresses the frontend truth hierarchy and makes the existing recommendation data visible on both pages. It does not change recommendation arithmetic or execution behavior.

## What is currently reliable

### Sector state

The sector engine aligns sector-ETF and SPY closes by date, deduplicates same-date ETF observations, computes 5/20/60-session relative returns, and classifies state from RS20 level and five-session RS20 slope:

- `LEADING`: RS20 >= 0 and slope >= 0
- `WEAKENING`: RS20 >= 0 and slope < 0
- `IMPROVING`: RS20 < 0 and slope >= 0
- `LAGGING`: RS20 < 0 and slope < 0

A state transition is not surfaced until the second consecutive close in the new state.

### Industry state

The industry engine fails closed on a partial Finviz export, covers roughly 144 groups, persists close states separately from midday display refreshes, and restricts transition alerts to book or operator-starred intersections.

### Recommendation cards

The defense recommendation engine drops incomplete cards. Long candidates require a real price, entry logic and invalidation. Rotate-in constituents pass liquidity, extension and earnings-blackout rails. Actionable controls remain downstream of account, approval and 2FA systems.

## Backend accuracy gaps

### 1. Breadth is labeled more precisely than it is calculated

The sector engine describes breadth as the percentage of members above their own 20DMA. The query currently averages all stored closes inside a 30-calendar-day filter and requires only 15 rows. That is not necessarily the latest 20 distinct trading closes, especially when repricing writes duplicate same-day rows.

**Required fix:** deduplicate by symbol/date and calculate the mean of exactly the latest 20 distinct session closes. Return `coverage_n`, `membership_n` and a quality flag with every breadth value.

### 2. Market internals are a capped sample

The market state line derives new-high/new-low language from the latest `market_movers` capture, which is explicitly capped to the top 15 rows per signal. It is useful as a movers sample, but it is not comprehensive exchange breadth.

**Required fix:** label it `top-movers NH/NL sample`, or replace it with a comprehensive universe breadth producer before using phrases such as broad strength or narrow tape.

### 3. Industry and benchmark windows are mixed

Industry week/month performance comes from Finviz, while the benchmark subtraction uses locally stored SPY 5- and 21-session returns. Vendor calendar conventions, close timing and adjustment policy may differ.

**Required fix:** calculate both legs from one vendor and one timestamp, or retain the current computation with an explicit `approximate_mixed_vendor_windows` quality state and confidence penalty.

### 4. Industry-to-sector mapping is modal, not canonical

The industry engine selects the most common sector associated with each industry in `trade_ai_scans`. That is practical but can drift as source labels or coverage change.

**Required fix:** version a canonical industry-to-GICS-sector map and report unmapped/conflicted groups.

### 5. The recommendation neutral map is not benchmark-aware

The engine uses an equal 9.1% neutral sector weight, a fixed 4% underweight floor and 2–4% account-equity sizing bands. These are transparent, but they are not tied to a chosen benchmark, account mandate, volatility budget, correlation or tracking-error target.

**Required enhancement:** calculate target gaps against an explicit benchmark/mandate and bound active tilts by account risk budget. Continue to show the existing equal-weight framework as one selectable policy, not universal truth.

### 6. Stock selection needs a fuller institutional quality layer

Current rotate-in constituents are primarily ranked by legacy Hermes composite, then filtered for liquidity, extension and near-term earnings. This is not enough for an institutional rotation recommendation.

**Required enhancement:** include earnings revisions, valuation relative to sector/history, free-cash-flow quality, leverage, ROIC, beta/correlation, short interest, catalyst calendar and crowding. Require sector confirmation + industry confirmation + stock quality + liquidity + non-extension.

### 7. Dated operator lean may be stale

The configured defensive lean restricts rotate-in recommendations to Utilities, Consumer Staples and Healthcare. It was set on 2026-07-18 and remains enabled until breadth, small caps and NH/NL confirm broadening.

**Required review:** do not auto-revoke it, but force a visible dated re-adjudication when current evidence conflicts with the directive or its underlying evidence is stale.

### 8. Fund look-through is configuration truth, not live holdings truth

Effective sector exposure uses configured factsheet weights. The config itself still asks the operator to eyeball the factsheet mapping.

**Required enhancement:** attach factsheet date, provider, coverage percentage and unmapped weight to each effective-exposure number; warn when a fund mapping exceeds its refresh SLA.

## Frontend findings and changes in this branch

### Problems

- `/v3/defense` is powerful but visually dense; deterministic facts, model opinions and action-adjacent controls compete for attention.
- `/v3/sectors` previously acted mainly as a monitoring card wall and sent allocation work to another page.
- Neither page presented one explicit sector → industry → ETF → stock recommendation hierarchy.
- Model badges appeared adjacent to market facts without enough explanation of their non-authoritative role.
- Industry mixed-window limitations and source freshness were not prominent.

### Changes

- Adds an **Institutional Rotation Brief** to both pages.
- Shows leading/improving sectors with industries underneath, the sector ETF and current stock candidates from complete recommendation cards.
- Shows weakening/lagging sectors as funding/reduction watches and complete protect/hedge cards separately.
- Adds trigger and invalidation language where the backend provides it.
- Adds a method/freshness drawer and an explicit mixed-vendor-window warning.
- Labels GPT/Grok/paid-model output as **critique**, not recommendation authority.
- Renames the sector surface to **Sectors & Industries** and embeds industry leaders/laggards under every sector card.
- Reframes the Finviz panel as a single-vendor performance tape rather than a recommendation engine.
- Leaves every existing action, approval, broker and 2FA boundary unchanged.

## Agentic-system integration contract

The governed agentic MVL in PR #163 should be attached as a review and learning layer, not as a quote source or trading authority.

### Rotation artifact adapter

Create an immutable `rotation_recommendation` artifact containing:

- sector snapshot hash and as-of time;
- industry snapshot hash and as-of time;
- portfolio exposure snapshot hash;
- recommendation config version/hash;
- benchmark/mandate identity;
- source refs and coverage;
- recommendation cards, triggers and invalidations;
- deterministic validation findings.

### Sentinel

Sentinel should reject or quarantine an artifact when it finds:

- stale or missing source timestamps;
- mixed windows presented without a quality warning;
- incomplete coverage;
- sector/industry contradictions without explanation;
- stale operator directives;
- missing benchmark, mandate or portfolio snapshot;
- impossible sizing, missing invalidation or forbidden authority;
- model text presented as a market fact.

Sentinel may not change the recommendation, stage an intent or override a deterministic failure.

### Independent critic lanes

Local, GPT and Grok lanes may critique the macro thesis, catalyst set, omitted risks and internal contradictions. Their outputs must retain exact provider/model provenance. Disagreement is surfaced; it is never resolved by majority vote.

### Darwin

Darwin should score recommendations at 5/20/60 sessions and by completed rotation lifecycle:

- sector relative return;
- industry-selection value added;
- stock-selection value added;
- maximum adverse excursion/drawdown;
- turnover and implementation slippage;
- false-positive/false-negative transition rates;
- calibration by confidence band and market regime.

Darwin cannot promote a rule or directive.

### Iris

MVL Iris should review lesson lifecycle, detect stale/conflicted rotation lessons and require operator adjudication for ratification. It must remain namespaced separately from the legacy taxonomy Iris.

### Hermes

MVL Hermes may preregister frozen hypotheses, for example whether broadening evidence warrants retiring the 2026-07-18 defensive lean. It may not activate the hypothesis or edit configuration.

### Concierge

Concierge may explain the evidence, show run status and cancel/resume a reflective run. It must not expose arbitrary shell, database, broker, approval or config-promotion authority.

## Acceptance gates before calling the pages validated

1. Capture live screenshots and JSON for:
   - `/api/v2/defense/posture`
   - `/api/v2/defense/industries`
   - `/api/v2/defense/recommendations`
   - `/api/v2/sectors/monitor`
2. Verify every displayed field against its producer timestamp and calculation version.
3. Recompute a sample of at least three sector rows and ten industry rows independently.
4. Verify portfolio look-through totals reconcile to holdings and disclose unmapped weight.
5. Apply the exact-20-session breadth correction.
6. Normalize or quality-penalize mixed vendor windows.
7. Run build, design guard, chip-scope test and browser checks at desktop and narrow widths.
8. Confirm all model outputs are visually and contractually subordinate to deterministic evidence.
9. Run a walk-forward shadow sample before changing the defensive-lean directive or recommendation thresholds.
10. Keep recommendations advisory until the existing approval/2FA architecture independently authorizes any downstream action.

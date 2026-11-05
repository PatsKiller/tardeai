# Home re-entry quote truth and source audit

Review date: 2026-11-04. Source audit base: `105df180ec68a1a20e700c185a14f638a77122a3`.
Scope: Home and Risk share the market-risk actionable card. This repair is presentation and stored-data reads only.

## Defect and correction

`GET /api/v2/market-risk/latest` projects `data/runtime/market_risk_latest.json`, then calls
`market_risk_book_join.join`. The stored `reentry_watch.stages` comes from confirmed session bars; its
`current_quote` previously came from `PgReader.regular_session_quotes` bounded by the assessment time. Before the
open that excludes a perfectly usable pre-market quote; immediately after the open it can also exclude a quote
observed just after that assessment. `marketRisk.actionableModel` separately copied `stages.verdict` and
`stage2.met`, even when its price display correctly refused the old regular-session observation.

The decision desk reads the existing `market_quotes` observations via the data-broker projection. It does not use
the risk assessment's regular-only display selection. The candidate CIO rendering libraries were not the Home
component responsible for this mismatch.

The API join now refreshes current price from the same existing Alpaca observation ledger in one bounded,
dedicated, read-only batch query. It runs independently of holdings availability. Each quote carries source,
observation time, session/date, request evaluation time and explicit freshness. This is **not** a provider request,
a streaming-live guarantee, an exchange trade timestamp or an official daily close. Confirmed stages, the
regular-session close reader and daily bars are unchanged.

The UI requires an explicit recognised quote schema and validates every accepted schema against the caller clock.
Both current observations and legacy regular observations expire even if an old API assessment is retained.
An expired legacy observation may remain labelled historical context; it cannot keep Now or CONFIRMED.
Both read-only setup boundaries own and close the new connection on setup failure, and the original refusal is
preserved if cleanup or diagnostic recording also fails. Cleanup diagnostics record error types only; no security
baseline or suppression change is used. The UI re-ages the observation before using it. A current price below the existing invalidation
level vetoes an old positive stage verdict: `INVALIDATED`, with Stage 2 no longer marked met. An unavailable/stale
quote renders current confirmation `UNVERIFIED`; it cannot silently borrow yesterday's close or keep CONFIRMED.
A positive current display also requires an existing finite positive invalidation level. If that prerequisite is
missing or malformed, the quote can still be shown but confirmation is UNVERIFIED with the missing-floor reason;
no level is invented and no historical stage is changed. The current price and percent share the same price/reference pair. A quote failure does not erase the historical
bar evidence or write a trading decision.

The operator-requested public-price regression uses a synthetic symbol/account: exit 137.19, invalidation 134.50,
prior close 140.47, observed price 132.99 at 09:00 ET. It expects:

`now $132.99 (−3.1% vs exit) · pre-market 09:00 ET` and `INVALIDATED`.

The actual operator reproduction moved between observations: the captured decision-desk quote was already newer
than the quoted incident fixture. The durable incident packet keeps each capture's own time; the test deliberately
pins the requested numbers, rather than calling a moving quote a fixed expectation.

## Validation and limits

The committed frontend regression fails against the old implementation on the CONFIRMED/INVALIDATED assertion;
the backend's new cases likewise fail before implementation. Existing registered tests cover the new reader/API
refresh, stale/future/wrong-source/invalid observations, failure and connection cleanup, and historical-reader
regressions. A browser fixture renders the actual component at 1440 and 390 pixels: invalidated and unavailable
states are distinct and no horizontal page overflow appears. No live browser traffic was used for those proofs.

Run `node --experimental-strip-types src/lib/marketRisk.test.ts` from the app directory and the existing
`tests/test_market_risk_reader_20261031.py` and `tests/test_reentry_truth_20261102.py` Python suites from repository
root. Deployment acceptance remains separate: verify the serving source and actual endpoint after release.

## Other Home price/verdict surfaces

The following is a source audit, **not** a claim that each value was wrong at runtime. Existing session-based
analysis and historical returns are allowed to stay historical when their scope is clear. Follow-up identifiers
below are remediation references for lead triage, not a claim that another fix shipped in this PR.

| Surface | API / producer | Clock handling and disposition |
|---|---|---|
| Global price stamp, PORTFOLIO and TODAY | overview; canonical observation envelopes / portfolio snapshot | Separate position, valuation, quote and P&L clocks already exist. No additional live-quote contradiction established. |
| Global TRADING / REALIZED | overview journal projection | Historical scope, through-date and rebuild clock; not current-price verdicts. |
| Global REGIME; Market in one look regime | risk-regime/latest; data-broker regime snapshots | **HQ-01:** freshness lives beside `data`; generic `useApi` unwrap discards it and these consumers do not gate the verdict. Preserve the envelope before claiming current regime. |
| Global VIX | trade-ai/summary; scanner VIX observation | **HQ-02:** source/time exist in provenance but no independent VIX-age warning; SETUPS freshness does not establish VIX freshness. |
| Global SETUPS / latest scan | scanner summary | Explicit scan freshness/population/degraded-run judgement already consumed. |
| Market-risk banner, summary, fact and compact card | market-risk projection; stored engine snapshot | Top-level assessment age checked. This repair separates quote age from assessment age; it does not change market-risk scoring. |
| Protect / Hedge / Rotate / sectors / exposure / budgets | market-risk projection plus book join | Stored analysis and holdings join, with evaluation/source clocks; not inherently a live quote feed. No new wrong-value runtime claim. |
| Stopped-out price and verdict | market-risk re-entry quote + stages | **Fixed here:** current quote refreshed, negative invalidation veto, unavailable confirmation explicit. Historical stages remain unchanged. |
| Home Portfolio / Today / cash | overview; positionsFreshness/cashPct | **HQ-03:** retained API transport failure is not included in money/position freshness; stored observation ages, but transport truth can be lost. |
| Accounts / YTD | portfolio/performance plus overview fallback | **HQ-03:** accountRows does not locally inspect performance as-of/transport freshness. Historical returns are not automatically wrong, but the ageing contract is incomplete. |
| What moved your book today | overview.top_movers | **HQ-03:** no per-row source date/freshness consumed; surrounding position-age badge is the only clock. |
| Do-now protection, heat and source verdicts | home/do-now and CIO page projections | Source gaps, retained-data staleness, stop categories and broker-read timestamps are explicit. |
| Best opportunities | opportunities preset top5; stored opportunity projection | **HQ-04:** list as-of exists, Home discards it; conviction/R:R have no list-time quote/session/age gate. Live details do not make the list live. |
| Market in one look sectors / hedge / inverse lights | defense/posture; sector/price and hedge snapshots | **HQ-05:** backend supplies stale/age/as-of, Home ignores them when rendering leading/lagging and hedge verdicts. |
| System pulse platform / scan / deploy | health/scanner/deploy projections | Dedicated freshness and error models already consumed. |
| System pulse Data health | overview.pipeline_status / dataset freshness | **HQ-03:** retained API-body transport failure is not included in the fresh label. |
| Major News day-percent grid and modal | portfolio/book-map; holdings-backed book-map rows, optional Finviz fallback | **HQ-06:** as-of discarded, no quote/session gate; missing day percent becomes +0.00%; cache key omits the auxiliary Finviz clock. Unknown must not become zero. |
| AI briefing summary and content | command.llm_intelligence; intelligence cache | **HQ-07:** generated_at discarded by summary/content rendering; a last-good financial narrative can appear without its age. |
| Executive Brief drawer | command.executive_brief | Explicit age and stale state already rendered. |
| Market movers drawer | market-movers; stored Finviz capture | **HQ-08:** nonempty old capture shows time without full date/age gate. It is a deliberate RTH snapshot, not live quotes. |
| Classic view / Recovery Watch | same sources plus risk, history and command consumers | Shares the above source risks; no independent live-source comparison established. The separate Recovery Watch consumer is not cleared by this card repair. |

These follow-ups require their own source-to-render tests and priority decisions. No additional endpoint calls,
model calls, portfolio writes, policy changes, broker reads or schedule changes are part of this audit.

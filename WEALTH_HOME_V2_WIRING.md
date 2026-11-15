# Wealth Home v2: source-to-view wiring and qualification

## Single existing publication path

`n8n dp-live cc-product-home -> scripts/cc_products_build.py --product home -> scripts.lib.cc_products.builders::build_home -> wealth_home_v2::collect -> wealth_home_v2::build -> existing home.slices.wealth_v2 -> cc_product_current / existing hot tier -> product_route::serve_home_slice -> api_v2::_wealth_home_v2 -> wealth_home_v2::serve -> /api/v2/wealth/home-v2 and /api/v2/wealth/operating-header -> homeV2Adapter / operatingHeaderModel -> HomeLive / OperatingHeader -> HomeTodayPage, HomeOutlookPage, HomeNeedsPage`.

All source aliases below traverse this path. The Home producer formats financial strings once. GET reads one stored slice and updates calendar/ages only; it never invokes a producer, model, scheduler or provider. The composition clock is `built_at`, explicitly `build_time`; each financial observation retains its own clock and threshold. A newly built composition cannot freshen a stale source.

## Existing source contracts

- **P**: `cio-pages-product -> cio_truth -> w7_pages::project_pages -> cio.pages.portfolio`; household/account values, cash, current-holdings day estimate and coverage. Value clock uses the retained mark/position clock, never `valuation_as_of` (batch build metadata); canonical day-P/L observation clock remains unknown when the producer says unknown.
- **S**: same CIO producer -> `cio.pages.positions.rows` and `cio.pages.stops`; canonical account/instrument identity, canonical protection verdict/reason/counting, row stop source/clock, stored quantity coverage and canonical open/closed freshness threshold. The narrow projection edit retains existing `protection_state` and `protection`; no new classifier.
- **Q**: same CIO producer -> `cio.pages.do_now`; complete `all_items` when provided, bounded `items` otherwise, typed categories/counts and own `as_of`.
- **R**: same CIO producer -> `cio.pages.regime`; independent label/confidence/components and own `as_of`.
- **M**: existing `cc-product-market-risk -> market_risk.latest.projection`; tier/score/reason, own `as_of`, existing one-hour threshold.
- **C**: same stored M projection -> existing `market_risk_home_context::home_context -> home_v007`; guarded quote/change facts, event facts, headlines, hedge thresholds, field states/source clocks. Unknown or rejected quote facts are not replaced with raw prices.
- **W**: existing market-risk book precision/re-entry producer -> `market_risk.latest.projection.reentry_watch`; existing stages/conditions, exit date, session date and recorded reason. Date-only observations remain date-only, not fabricated UTC clocks.
- **F**: existing market-risk producer -> `overnight_markets`; exchange/session/date, current print, dated reference and level-only flag, existing per-block threshold.
- **SC**: existing warm-cache producer -> `data/runtime/trade_ai_cache.json`; dated VIX, scanner run receipt, stored gainers. Finished-run eligibility is not inferred from cache assembly.
- **H**: existing Health Agent -> `data/portfolios/state/health_agent_status.json`; snapshot `captured_at`, findings population and existing three-hour `needs_action.HEALTH_STALE_H`. This file may lag the separately stored DB Health snapshot; this limitation is explicit below.
- **I**: existing Home `incidents` slice -> registered category/type, first/last occurrence clocks. History is not current protection.
- **B**: existing Home `since_close` slice -> generated historical brief snapshot; text shown only if typed text actually exists.

## Per-element acceptance/wiring checklist

Each row identifies the actual stored field or an explicit missing contract. Unknown is nullable/grey, never synthetic zero. All financial formatting occurs in `wealth_home_v2::build`; UI filters and progressive disclosure only select already formatted rows.

| View / element | Source -> stored field | Clock / correctness / available behavior |
| --- | --- | --- |
| Header 1 Session label | existing `market_risk.sessions::session_label` | Real NYSE calendar including holidays/early close; overnight displayed Closed |
| Header Session last date | `sessions::last_closed_session` | Actual exchange date; separate from unproven P/L interval |
| Header Session next open | `sessions::is_trading_day` | UTC stored value; operator secondary explicitly ET |
| Header 2 Session estimate dollars | P `day_pl_usd` | Current-holdings estimate; source interval unproven, amber |
| Header Session estimate percent | P `day_pl_pct`, `day_pl_coverage` | Keeps method and eligible n/m, no verified account return claim |
| Header 3 Household value | P `total_usd` | Retained mark/position clock; valuation build metadata separate; household distinguished from accounts |
| Header Cash dollars / percentage | P `cash_usd`, `total_usd` | Percentage producer-derived only on positive known denominator; explicitly derived |
| Header Approximate YTD | no compatible flow-adjusted stored contract | Unknown; raw balance growth is not profit |
| Header 4 Temperature tier / score / stance | M `tier`, `score`, `reason` | M own clock, tier state retained separately from freshness |
| Header 5 Regime label / confidence | R `label`, `confidence` | Independent R source and age; missing score stays unknown |
| Header 6 VIX value | SC or R `vix`, `vix_source`, `vix_observation_time` | Neutral; source freshness contract, not a fabricated 36h policy |
| Header 7 Operating mode / kill / submit | no typed stored operating-flags contract | Unknown; no broker inspection or flag inference |
| Header 8 Health critical / total | H `findings[].severity`, findings population | Same snapshot denominator; stale snapshot is grey with retained counts |
| Header Needs badge | Q `total` | Qualified nonnegative integer only; present in header-only payload |
| Today 1 Daily decision left tier / score | M tier, score, reason, episode | Saved engine evidence; no new advice synthesis |
| Today Decision Buys | no stored typed buy-risk stance | Explicit not served |
| Today Decision Stops to decide | no typed stop-decision subset | Explicit not served; broad protect count not substituted |
| Today Decision Unprotected / largest | no complete proved current subset summary | Explicit not served; raw missing stop not classified as gap |
| Today Decision Re-entry ready / near / total | W available stages but no served near aggregate | Explicit not served; no invented near threshold |
| Today 2 Snapshot Portfolio | P `total_usd` | Retained mark/position clock; batch build separate |
| Today Snapshot Session estimate | P `day_pl_usd` | Signed estimate; stale source retains sign and freshness qualifier |
| Today Snapshot Approximate YTD | compatible period/flows absent | Unknown |
| Today Snapshot Realized P/L | eligible ledger/basis coverage absent | Unknown, not zero |
| Today Snapshot Trading record | comparable finished-trade population absent | Unknown, not zero |
| Today 3 Movers Price | C `symbols[].quote` measured facts only | Each guarded source clock; held/watch membership from canonical held/W populations |
| Today Movers Change / reference | C `day_change.value.pct`, reference session | Current print versus prior completed NYSE session close; no unproved dollar contribution |
| Today Movers Held / Watch filter | canonical P/S symbols / W keys | Filters served scope tags; no browser financial arithmetic |
| Today 4 Protection status | S canonical `protection_state/protection` | Active requires strict flag, positive level, row clock, canonical threshold; missing proof grey |
| Today Protection pending | S `stop_state=pending_activation` | Pending distinct from active; amber |
| Today Protection partial quantity | S `resting_loss_qty`, `resting_coverage_shortfall_qty` | Positive remainder amber; exact covered/uncovered quantities retained |
| Today Protection level / distance / shares | S stored stop level/distance/fractional shares | No recomputation of stop or rounding shares to integer |
| Today Protection account detail link | S normalized account alias and symbol | Existing Holdings `hv_query` + `hv_account` filters |
| Today 5 This week event rows | C `next_event.value` | Recorded date-only events explicitly timing-unconfirmed; bounded coverage named |
| Today 6 What to read first titles | C guarded `headlines.value[]` | Exact stored title; all entity matches unverified candidates |
| Today News publisher / publication / ingest | C per-headline source/publication and headline fact `as_of` | Independent clocks, safe HTTP(S) original source links |
| Today News contextual links | canonical held membership / W watch membership | Held Holdings filter; otherwise existing classic watch intelligence reader |
| Today 7 Accounts value / cash | P `accounts[].total_usd/cash_usd` | Account's own clock; no household return substituted |
| Today Accounts session estimate / detail | P `accounts[].day_pl_usd`, account alias | Signed estimate; account-scoped Holdings link |
| Today 8 Setups run / scanned / GO | SC run identifier and summary counts | Stored run receipt only; ranked latest-finished setup membership unproven |
| Today 9 Watch / re-entry stage | W status/headline/exit/session date | Retained advisory evidence; existing date-only clock not promoted |
| Today Watch five dots | W `conditions[].met` | Only exactly five typed booleans; missing not treated false |
| Today 10 Historical brief | B typed `summary/brief`, `generated_at` | Historical figures retain generation snapshot; absent typed text explicit |
| Today 11 System pulse source cards | per-source collection receipts | Home coverage, not Health findings or platform green declaration |
| Outlook 1 Temperature contributors | M categories, tier/score/episode | Existing source evidence; no invented gauge thresholds |
| Outlook 2 Regime components | R `parts` / retained component states | Independent engine, own source clock |
| Outlook 3 Engine disagreements | CIO `conflicts.findings` | Registered findings only, no disagreement invented from risk tier |
| Outlook 4 Sector states / return / RS | M `sectors.groups` plus existing canonical eleven-sector universe | Missing groups grey with a reason; no fictional momentum |
| Outlook 5 Hedge progress | C `hedge.lagging_progress/exposure_progress` | Existing engine threshold facts only; missing independent rotation explicit |
| Outlook 6 Week ahead | same C dated event facts as Today | Bounded held/watch coverage, recorded date not confirmed time |
| Outlook 7 Futures / overseas levels | F print/session/date/source | Each independent print clock; level-only suppresses change |
| Outlook Futures change / reference | F `change_pct`, reference basis/date | No change without dated reference |
| Outlook supporting Headlines | same C unverified candidate rows | Exact titles/source links, no personalized consequence |
| Outlook supporting Scanner movers | SC `top_gainers/top_losers` | At most five up and five down; missing down sample explicitly not served |
| Needs Summary Money decisions today | no typed money-decision subset | Unknown; total queue does not masquerade as money decisions |
| Needs Summary Protect money | Q complete all_items category / typed counts | Qualified source + nonnegative integer; unknown zero suppressed |
| Needs Summary Decide | same Q category | Qualified count and existing queue reason |
| Needs Summary Fix system | same Q category | Qualified count; no incident count substituted |
| Needs Summary Queue freshness | Q own `as_of`, stale qualification | Source state independent from page build clock |
| Needs Protect rows / details | same canonical S protection rows | Account-scoped, pending/gap/unknown separate |
| Needs Decide rows | Q valid category=decide entries | Malformed neighbors cannot shift/drop decisions |
| Needs Re-entry tracker | same W status/conditions | Historical/currentness qualification retained |
| Needs Fix source gaps | producer source-read receipts | Review only; no scheduler mutation from page |
| Needs Incident history category | I registered category / alert type | Separate history collapsed; actual cause provenance limitation below |
| Needs Incident first / last seen | I occurrence clocks | Date-qualified history, never current protection proof |
| All three views Show all / query filters | complete supplied section rows | Client disclosure/filtering only; no financial sums recomputed |
| All views desktop / phone / supporting readers | same section contract and semantic links | Requires served release browser proof; local tests do not certify live destinations |

## PROCESS / CONTRACT / SELFHEAL / PROOF

**PROCESS:** extend the existing `cc-product-home` lane only. Its existing dp-live schedule is minutely during the configured market window and hourly off hours; retry policy is `transient-2`. Existing child deadline, read-only connection, host lock, concurrency/memory/body budgets remain in force. No scheduler or lane mutation is included.

**CONTRACT:** `wealth_home_v2::validate_contract` runs before the new slice returns: required WealthHome@v2 schema, all eight color-state header cells, every Today/Outlook/Needs panel key, rows/metrics lists, and typed value for each served header display. Missing slice/schema/field returns unavailable or fails this slice instead of a plausible green. `config/ci_gates/WEALTH_HOME_V2_20261115.json` is an executable CiGate@v1 registry entry naming the pure pytest suite. UI Node behavior suite is separately qualified; build-hook registration belongs to the parent-owned package claim.

**SELFHEAL:** the existing Home lane retries transient failure twice and its next natural tick re-reads existing sources. Failed product publication retains last-known-good data; missing/expired products and sources retain evidence with age and explicit unavailable/stale state. No new durable store, alert, scheduler, broker read, external provider, or repair write. Existing output_signal is `db_max(cc_product_build_log.finished_at WHERE product_id='home')`, expected cadence 1h. That whole-product signal alone does not prove the new slice: the mandatory slice validator, explicit missing-slice response, CI gate and served slice inspection provide that proof. Existing Home stale/hard windows remain market 180/900 seconds and off-hours 9000/14400 seconds. Wealth composition slice reuses existing `limits_for(home)` stale policy: 180 seconds during the market publication tier and 9000 seconds off hours. Financial source clocks remain independent; fresh composition does not freshen old observations.

**PROOF:** synthetic tests include selective duplicate identities versus an undoubled control, conflicting three-row duplicates, fractional shares, missing versus zero, unknown clocks, real exchange holidays/early close, unverified acronym/venue headlines, strict canonical active positive control, partial quantity, malformed queue neighbors, invalid counts, source/Home staleness propagation and no-compute GET tripwires. The real `build_home -> actual emitted slice_clocks -> serve_home_slice -> serve` test proves composition clock/expiry rather than inventing its fixture clock. Existing isolated-Postgres recovery regression tests verify unchanged/recovery semantics. Independent review is separate from author tests. Final acceptance still requires lead activation and served build/API/browser evidence at desktop and phone widths.

## Concrete remaining source gaps / ownership

- Typed operating flags, flow-adjusted YTD, realized ledger coverage, comparable trading record, ranked completed-run setups and full confirmed held/watch calendar remain unavailable; unknown displays are intentional and named per element above.
- Health file can be older than the DB snapshot used by the existing full Health endpoint. This first small batch names its snapshot and age; it must not claim cross-store equality without selecting the same qualified snapshot.
- Protection's canonical fields were narrowly retained in w7 under an approved mechanical claim, then edits paused when parent requested original-owner release confirmation. Parent decides integration after release evidence; no further w7 edits by this worker.
- Existing `home_incidents::SQL` fallback event text lookup is broad type/symbol/time matching rather than incident identity. Registered category is preserved, but fallback cause text may refer to another event. Source repair remains outside this claim; never classify from fallback message.
- Current backend release's dividend qualified/forecast provenance delta is preserved exactly in api_v2. No backend replacement.
- Backend activation uses the established lead R14BE worktree build/activate procedure; frontend activation is separate. Worker does not activate production. Rollback remains lead-owned prior served pin.

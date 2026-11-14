# Wealth Management 501

**Trade-AI investment-desk architecture and engineering operating standard**  
Version 1.0 · 14 November 2026 · Owner: John Whiting · Status: directive for implementation; not a claim of completed delivery.

## 1. Mission and authority

Build one coherent, actionable wealth-management and investment-desk product. The user must understand what they own, what they paid, what it is worth, what they earned, what threatens it, and the next decision. Every page, tab, detail, export and background producer serves this mission. Institutional discipline is the quality target; no affiliation with, certification by, or equivalence to Citadel, Goldman Sachs, Morgan Stanley or Charles Schwab is asserted.

This guide adds product and engineering requirements to existing approved page designs. It does not erase unresolved acceptance items or authorize rewriting a frozen release. Explicit current user decisions govern scope. The grant system is disabled for this sprint and there is no GitHub push/PR dependency. Preserve authentication, 2FA, broker locks, real-order safeguards and permissions. Development and audits do not submit orders, approve financial actions or resend paid/provider communications.

## 2. The front-page investment mandate

Home opens with a concise **Investment Desk Brief**, followed by ranked decisions and the book summary. Its primary advisory groups are:

| Group | Required answer | Evidence and next step |
|---|---|---|
| Reduce / exit review | What existing exposure merits review, and why now? | Account, position, mandate, concentration, dated thesis/risk change; safe review workflow. |
| Hold / monitor | Why retain the holding, and what would change the decision? | Thesis, horizon, valuation/risk context and explicit invalidation conditions. |
| Add / rotate candidates | What destination is supported, and where would capital come from? | Source capital, destination thesis, alternatives including cash, suitability/data gates and cost/tax uncertainty. |
| Wait | What precise condition must change? | Price/valuation/catalyst/date/data condition, owner and reevaluation trigger. |
| Protect / unblock | Which missing protection or system fault affects investment decisions? | Money/account scope, actual evidence, urgency and a working safe destination. |

Recommendations are not generic news sentiment or unexplained BUY/SELL badges. Each card contains fact versus inference, reason, supporting evidence times, affected holdings/accounts, horizon, confidence and coverage, alternatives, trigger, invalidator, next action and recommendation identity. Show sizing only where supported by the user's configured policy; do not invent risk tolerance, tax circumstances or limits. A blocked recommendation remains visible with its reason rather than masquerading as an executable instruction.

A major event involving Nvidia or any other company must be verified from dated primary evidence before it influences advice. Trace direct positions and sourced ETF/sector exposure; never invent look-through weights. Distinguish the event's time, quote time and analysis time. A market headline alone is not a portfolio recommendation.

## 3. Whole-site information architecture

Inventory every actual router route and subtab, including aliases and classic views. The following page families define intended decisions; existing routes must be mapped rather than renamed blindly.

| Surface | Primary user decision | Required content / workflow |
|---|---|---|
| Home | What needs my attention now? | Desk brief, ranked actions, selected-scope wealth/performance, movers, upcoming catalysts, concise operating exceptions. |
| Portfolio / Holdings | What do I own and what has it earned? | Ownership, entry/cost, price, value, dollar/percentage gains, allocation, fundamentals, protection and actionable details. |
| Retirement | Is the long-term allocation aligned? | Account-aware allocation, concentration, income and supported planning assumptions; no invented suitability inputs. |
| Performance / Returns / Income | How did investments perform over the chosen interval? | Defined periods, cash-flow treatment, realized/unrealized/income/fees, coverage and drilldown. |
| Risk | What exposure could harm the book? | Explainable measured exposures, concentration, source quality, protection gaps and scenario assumptions. |
| Defense | What protection alternatives are supported? | Existing protection versus proposals, costs/tradeoffs, prerequisites and review links. |
| Re-entry | When is a previously exited position worth reconsidering? | Exit context, updated thesis, sourced levels, triggers and invalidation. |
| Rotation / Redeploy | Where should reviewed capital move? | Source and destination together, rationale, cash alternative, account/lot constraints and policy gates. |
| Watch Overview | What monitored ideas changed? | Actionable changes, alerts, catalysts and ranked next steps; consistent membership. |
| My List / Suggestions / Prospects | Which ideas am I tracking and why? | Membership provenance, current ownership, expiry, thesis stage, clocks and safe research actions. |
| Setups / Sectors / Discover / Pullback | Which researched opportunities meet defined conditions? | Sourced screens, explicit scoring method, current conditions, levels and valid research destinations. |
| Watch Alerts / History | What happened and was it handled? | Event and delivery clocks, latest failure versus earlier success, history and acknowledgement boundaries. |
| Security details / Chart / Lots | Why hold or consider this security? | Position context, cost/returns, fundamentals, chart/levels, thesis, catalysts, evidence and protection. |
| Trading / Active Trader / Strategy | Which governed proposals are ready for review? | Readiness, source completeness, strategy rationale, risk/cost assumptions and existing controlled action path. |
| Journal | What did actual decisions produce? | Sourced fills, basis coverage, trading-session identity, outcomes and links to prior recommendations. |
| CIO / Questions / Research / Reports | What does the desk know and why? | Durable questions, answers, evidence, thesis/recommendation history, changes and outcomes. |
| Ops / Health / Jobs / Agents / Controls | Which investment workflows are impaired? | User impact first, owner/next action, accurate populations and clocks; technical details beneath. |

Every page must have an intended user decision, primary action, selected scope, clear data states, keyboard/mobile behavior and a route-specific acceptance row. Dead links, universal “Ask CIO” CTAs, permanent placeholders and silent routing fallback are not finished features.

## 4. Portfolio product specification

### Information hierarchy

1. Scope/account selector and session banner.
2. Wealth and performance summary with evidence/coverage.
3. Compact priority exceptions with useful review links.
4. Dominant holdings workspace; performance/allocation/income views.
5. Position details and optional diagnostics.

Do not allocate half the primary screen to technical validation prose while basic holdings fields are hidden. Keep material warnings visible; move internal LQ IDs, writer names and diagnostic detail into a drilldown. Missing-data explanations must say what is missing and the supported next step. A reworded placeholder does not complete its backend.

### Holdings fields

- Security/company, canonical account and instrument identity; preserve the same ticker in multiple accounts.
- Quantity, current price, quote session/source/time, market value and portfolio weight.
- Average remaining cost **per share**, total remaining cost basis and lot detail. Separate average basis from first purchase price.
- Regular-session change in dollars and percent; extended-session change separately.
- Unrealized gain/loss in dollars and percent where compatible basis/valuation exist. Partial basis produces partial coverage, never a fabricated total.
- Protection state, actual covered quantity, relevant stop and measured hypothetical downside. Stop price is not a guaranteed fill or a known maximum loss.
- Fundamentals preset: trailing and forward P/E separately, EPS, market capitalization, sector/industry and dividend yield where supported.
- Research preset: sourced support/resistance, methodology, timeframe, age, distance and thesis/catalyst references.

Use Overview / Performance / Fundamentals / Protection column presets rather than tiny unreadable columns. Search, sort, account/asset/status filtering and CSV must use the same data contract. Group cash distinctly without removing it from account totals. Mobile prioritizes security, price, average cost and unrealized dollars/percent, then expandable protection/fundamentals.

P/E requires earnings-period and source metadata. Nonpositive earnings display N/M with a reason; cash is N/A. Funds/ETFs use an explicitly sourced fund metric if available, not a fabricated company P/E or naive average of constituents. Missing fundamentals become owned integration work, not invented values.

Safe contextual actions include reviewing protection, lots, valuation, thesis, levels, proposals and research. All actual financial execution remains behind existing controls; viewing the page never trades.

## 5. Canonical data and financial definitions

“One source” means **one canonical broker/read-model layer and one authoritative source per field**, not pretending one vendor supplies every fact. Approved upstream broker, quote, fundamentals and research feeds may differ. Normalize them centrally; client pages must not select competing sources or silently combine incompatible observations.

Each field's authority matrix records upstream source, canonical owner, transformation/version, key, currency/unit, source observation time, ingestion time, calculation time, freshness rule and fallback policy. An account+security key must survive symbol changes and instrument types. Prefer stable IDs; ticker-only joins are insufficient.

### Required financial distinctions

| Measure | Definition / requirement |
|---|---|
| Account value | Assets/cash/liabilities under the documented accounting scope; not profit. |
| Holdings price move | Defined price-reference change for a matched position snapshot; not automatically economic P&L. |
| Unrealized P&L | Compatible current valuation minus supported remaining basis; percent uses supported basis. |
| Realized P&L | Sourced sale proceeds and matched disposed basis, with fees treatment; unknown-basis proceeds are not profit. |
| Period investment profit | Reconciled value/flow/income components without double-counting; explicit coverage, accounting convention and account aggregation. |
| Return % | Named methodology appropriate to available history and flows; do not sum position returns or imply a verified return from incomplete observations. |
| Verified economic P&L | Stored reconciliation supported by matched boundaries, fills, flows, income and evidence per account; never synthesized by page GET. |

Provide Today/WTD/MTD/YTD plus rolling 1W/1M/1Y and custom dates. Label calendar-to-date versus rolling boundaries, timezone, trading session and partial history. Include sold positions and correctly handle transfers, deposits/withdrawals, dividends, fees and corporate actions. Internal transfers must not double-count across selected accounts. Missing basis must not hide otherwise valid price/level data.

Support and resistance are attributed technical analysis, not guaranteed prices. No unsourced composite risk score, confidence score or arbitrary threshold is permitted.

## 6. Session and time contract

Separate positions_observed_at, quote_observed_at, official_close_at, source_as_of, computed_at, built_at, published_at and served_at. Rebuilding/re-reading never renews source truth. A fallback to wall-clock time cannot certify broker observations or market evidence.

Use market-calendar, venue, timezone/DST and early-close rules. The banner identifies **regular session**, **premarket**, **after-hours** or **market closed / last completed session**, with exact date/reference and coverage. Ordinary session price change and extended-session price change remain separate. Extended quotes reference the appropriate regular-session official close and cannot be claimed from a delayed/overnight/NAV mark without supporting session evidence. Weekend displays retain the last session date, not a fictional “today after-hours” result.

Example structure (not live values): “After-hours price move · session/date and interval · since regular close · quotes as of [time] · coverage [measured/eligible].” Unknown/partial evidence stays explicit.

## 7. CIO advisory and retained memory

Deterministic financial/risk calculations live in tested canonical services. The governed CIO synthesis explains evidence and alternatives; model text cannot override data-quality, authority, execution or financial gates. No model call occurs merely because a page opens.

Persist question/request ID, authorized user scope, source snapshots and evidence IDs, reasoning/thesis version, recommendation and alternatives, gates, provider attempt versus confirmed answer, decision, user feedback and later outcomes. Same user/request retry must not create duplicate paid effects. Uncertain provider outcomes enter a visible reconciliation state, not blind resend.

Memory must survive web/worker restarts, releases and rollback. Preserve history and append corrections/supersession rather than overwriting the original decision. Link Home advice -> security/thesis -> CIO conversation -> evidence -> subsequent outcome. Access controls follow the user/account scope. Measure retention with an actual stored record read back after lifecycle transitions, using isolated fixtures for tests; don't send live financial/provider probes.

Event-driven reevaluation plus a bounded scheduled catch-all updates advice only when justified by source changes or policy. Cache synthesis by evidence/policy identity and preserve the original evidence times. Contradictory advice for the same scope/session must be detected, explained or superseded.

## 8. Background architecture: n8n 24/7

**The overview/header refresh operates 24 hours a day, seven days a week, independent of browser traffic, Claude sessions, weekdays, nights, weekends and holidays.** Other producers keep their explicitly appropriate market/calendar cadence; the overview rule is not permission to turn every market action on overnight.

Flow: approved source writers -> canonical evidence and normalized models -> bounded background builders -> versioned stored products -> cheap authorized readers -> views/exports. Governed CIO synthesis consumes the same evidence and writes durable advisory products.

For every product specify schema/version, key/user/account scope, owner, required inputs, source clocks, expected cadence, freshness/last-good/expiry rules, cost limits, overlap limits and failure policy. Request threads do not perform heavy builds. Compatible stale-last-good may be served only within its stated window and visibly labelled; expiry returns unavailable, not an automatic legacy compute fallback. Migration flags are explicit.

### Root-cause closure for the header incident

The observed R7 failure was an expired overview projection last built Friday20:59ET, with a weekday-only producer behind a stored-only reader. Rollback restored the header; it did not repair the lifecycle contract.

Closure requires all of the following:

1. Inventory exact existing cron/timer/n8n/agent refresh responsibilities and receipt paths.
2. Choose measured bounded cadence and a last-good window accommodating interval, allowed delay and bounded retries, without falsifying underlying price/position freshness.
3. Establish a single scheduler owner, fence old admission/drain in-flight work if switching, and activate reviewed n8n 24/7 admission.
4. Seed a compatible usable product and prove an actual automatic scheduled refresh with successful durable receipt; tests alone/manual rebuilds do not prove scheduling.
5. Disable only mapped duplicate overview/header cron, timers, session one-shots and agent refresh loops after the replacement is proven. Preserve unrelated jobs, source writers, CIO memory and monitoring. Split shared jobs instead of disabling their unrelated responsibilities. Retain exact before/after entries and rollback.
6. Missed/refused/failed refresh detection, bounded idempotent retries/backoff, overlap limits and escalation must work without page traffic. Automatic recovery must be demonstrated with isolated failure/recovery tests and a real normal post-fix receipt.
7. Stored-reader cutover gates require compatible output, healthy producer, clocks/coverage and live verification. Rollback covers reader/producer version compatibility, not only files.

Self-healing is bounded recovery within this authority. It is not repeated restarts, indefinite retries, silent stale-data acceptance, invented timestamps or autonomous financial action. Alert-monitor failure must not erase the failure it is supposed to report.

## 9. Contracts and states

All financial/advisory responses need an envelope or equivalent versioned contract containing product ID, schema/calculation version, scope, snapshot/evidence ID, source/session clocks, values/units, coverage, status/reason and next safe action. Keep source observation separate from assembly/publish time.

States distinguish fresh, allowed last-good/stale, unavailable, incompatible, partial coverage, unproven reconciliation and not applicable. These are not interchangeable with zero or empty arrays. Preserve held/admitted/attempted/delivered/needs-reconciling effect states where applicable.

Rows, drawers, summaries, other pages and exports must agree under the same scope/metric/session/snapshot. Explicitly name populations and rounding differences. Do not compare all accounts to one account or market-risk regime to per-position downside as if they were the same metric.

## 10. Engineering-team operating rules

- One Anthropic lead and at most one subcoordinator; DeepSeek-first authors/reviewers. Narrow ownership per slice, explicit handoffs and no overlapping edits. Never manufacture stale-claim approval requirements; follow the applicable authorized claim process.
- Existing scoped local release authority applies. No GitHub pushes/PR dependency, no invented grants, no sudo assumption and no unrelated configuration changes.
- Author investigates the existing code/data path before changing it. Classify available-but-hidden versus missing source versus missing calculation/history. Prefer the smallest coherent vertical fix; do not rewrite whole pages/services to add a field.
- Every finding has actual affected routes, source/contract, owner/reviewer, next executable step, failure evidence, acceptance and deployed status. A queued message is not started work.
- Use NOT_STARTED / WAITING(actual holder) / RUNNING(PID,start,progress) / PASSED(real exit) / FAILED(reason) / INCOMPLETE(timeout). Preserve failed/skipped/baseline results; no weakening tests to obtain a green summary.
- Scope tests to real risk. Shared API/financial changes merit broader regression; typography-only changes do not require ritual full-suite mutation loops. Use isolated fixtures; no production DB/cache leakage into tests.
- Resource caps and storage routing remain enforced. Heavy builds/tests use the approved bounded slots and guarded /data storage. A watcher waits in background; it does not hold remediation hostage.
- Review exact patch/content and test actual frozen source. Distinguish commit identity, test export, build artifact and live version. Inspect ignored-file/hash edge cases before claiming source is missing.
- No source, data lineage, timer, architecture or outcome is asserted without evidence. Do not invent AEM's meaning; identify it before proposing changes.

## 11. Release and live acceptance

Ship small independently qualified slices promptly; no nominal-window delay or unrelated feature warehouse. Do not expand a frozen candidate. Prepare rollback before activation. A partial activation/manifest failure remains explicit even if the web server switched.

Before each release map changed modules/contracts to affected pages, tabs, details and shared consumers. After **every release**, check the actual affected live UI, supported read-only interactions and financial data, including desktop and phone layouts. HTTP200, a build or a screenshot alone is not full acceptance. Preserve the broker denylist; allow only verified safe reads required by the check rather than turning the whole denylist off.

Coverage record fields: release/source/build identity; route/tab/detail; expected user decision; selected account/security/session; source/snapshot/clock; viewport; interaction; observed result; PASS/FAIL/NOT_TESTED; owner; evidence and next action. Verify row == drawer == CSV where relevant. Do not claim every page checked from 13 API probes.

Run immediate targeted verification and bounded +15/+30/+60 checks for each release's risk. Report UI availability separately from financial reconciliation and producer health. Material regressions trigger incident-first repair/rollback. Every UNKNOWN has a supported reason and an owned remediation; the display must not manufacture a result to look complete.

## 12. Durable project control and completion

Retain this guide, exact instructions, owner/acceptance ledger, evidence index, CURRENT/NEXT, pending unsubmitted messages and checksummed checkpoints in the server campaign handoff and project deliverables. Record receipt/read/assignment separately from implementation and live proof. Update before compaction, after review, release and incident. Recover by reading current state; never replay old commands blindly.

Rolling delivery order: restore runtime truth -> repair 24/7 producer contract -> expose supported Portfolio basics -> complete owned financial/history/fundamental gaps -> deliver front-page advisory vertical slice -> apply the same investment-desk model across all route families. Parallel independent work may continue within resource limits. Each slice closes with review, release and live evidence. An eight-hour target is a delivery budget, not permission to relabel unfinished acceptance.

**Done means:** the intended investment decision is usable; fields are supported and consistent; safe next actions work; producers refresh without page traffic; CIO memory survives lifecycle transitions; failure/recovery behavior is proven; all affected views are independently verified on the deployed release; remaining gaps are explicit. “Ready”, “folded”, “reviewed”, “200” and “live” do not mean the same thing.

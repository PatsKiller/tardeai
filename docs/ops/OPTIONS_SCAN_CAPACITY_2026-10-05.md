# Options coverage and scan capacity — 2026-10-05

The October 5 review repair also adds a **Create standing plan** modal for any symbol, using the
existing ticker directive and options-intent writer. It previews before saving, preserves the
previous plan in the preview, refuses a changed-version overwrite and waits for the scheduled
matcher. Editing a plan invalidates older contract matches. Strategy and risk/reward tooltips
explain capital, upside limits, full downside and assignment; delta is not assignment probability.
An optional **LLM summary of this standing plan** reuses the governed ensemble job/result store,
bound to the exact intent and captured scan. It shows each model's reasoning and recording time;
no result is invented and page loads do not request models. These controls create advisory plans,
not account allocation, trade approval or broad-scan activation. Fixtures verify the UI paths;
organic matcher/model results for newly saved plans remain a runtime acceptance requirement.


Status: IMPLEMENTED IN SOURCE; expanded worker DISABLED pending measured capacity and activation.
Authority: advisory research only. This document does not approve broker activation, orders,
changes to risk thresholds, 2FA, memory influence, or provider limits.

## Review and economics repair — 2026-10-05

Status: source repair, verified with hermetic tests and replay of the captured production
snapshot. Deployment and fresh market acceptance are separate receipts; this section does not
claim a new scan or a profitable trade. Base/previous served release: `c96bec23c`.

The previous release mixed bid/ask payoff figures with midpoint premiums and hedge floors.
`options_economics.stamp_payoff` now selects one captured price basis and rebuilds the premium,
contract total, nested economics, payoff and covered/insured-lot figures together. Extra held
shares are identified separately. Quotes are estimates, never labelled executable merely because
both sides exist; closed-session or failed-liquidity POP/EV is withheld. Protection scenarios show
stock-alone loss, stock-plus-put loss and the difference on the insured lot. Model profitability
is not an insurance suitability score.

Investment review is independent of execution eligibility. `review_workflow` reports
`READY_FOR_REVIEW`, `NEEDS_RESEARCH`, `NEEDS_DATA`, `BLOCKED`, `APPROVED_AWAITING_QUOTES`,
`READY_FOR_PREFLIGHT` or `REJECTED_OR_EXPIRED`, with reason, owner and next action. Existing
approvability, enterprise blocks, quote validation, strategy policy and per-order 2FA remain
binding. A symbol-level CIO decision is context; it is not approval of a different option
contract, strategy or account. Model votes do not count as a CIO decision.

GET proposal reads project legacy cached economics without overwriting the source receipt,
fetching quotes or creating approvals. Both card versions use the corrected amounts. Same-expiry
packages no longer claim different expiries; combined capital/scenarios are explicitly hypothetical
if all displayed ideas were selected. Missing quote time stays unknown, not the scan fetch time.

Standing intents retain their existing producer and directive store. Their GET projection joins
canonical option-contract identities to existing account-specific proposal/thesis/decision links.
A matching contract in a different strategy never transfers a decision. Unmatched contracts are
reported as **not staged**, with account allocation and thesis requirements, and counted separately
from proposals. Cached intent prices say captured spot and show contract/underlying quote times.
Delta is no longer presented as assignment probability; annualized premium yield is explicitly
not an expected return. Long-dated intent matches retain their declared horizon, separate from
the main scanner's 7–365 DTE scope. No new thesis or approval store is introduced.

The 2026-10-05 **23:58:28Z** production snapshot contained 5,562 unique inventory symbols,
including all 23 held symbols, 5,551 watchlist names and 102 reentry names (memberships overlap).
Its coverage ledger marked six evaluated and 5,556 pending, with zero completed full-chain
receipts. This is not proof that no bounded chain reads occurred. Offline replay of the eight
cards yields **3 ready for investment review, 1 needing research, 3 needing data and 1 policy
block**, with all eight execution-ineligible and the original snapshot unchanged.

Expanded scanning remains disabled and unmeasured. The main view exposes pending evaluation and
capacity arithmetic; 5,562 mandatory names at 15 minutes imply at least **370.8 fresh chain
requests/minute**, before retries and projection. A configured rate is not observed throughput.
Provider allowance, measured runtime capacity and governed scheduler activation remain required.
No scan cadence, limits or trading settings were changed to manufacture more ready cards.

Verification must cover coherent debit/credit arithmetic, residual-share scope, invalid quotes,
review versus execution counts, exact strategy/account decision scope, immutable cached GETs,
intent joins, both browser card versions and unchanged execution restrictions. Close the broad
search target only with natural full/priority run receipts and the existing five-session criteria.

## Observed problem and requested service

The October 5 Options screen showed ten cards from a capped universe. The supplied screen was
not evidence that every holding, watched security or reentry name had been evaluated. The old
producer capped researched watchlist input at 120, reentry input at 120 (with a separately capped
dashboard snapshot), and displayed only strategy slots. Neutral/bearish evidence could fall
through to a bullish cash-secured-put branch. GET readers could regenerate proposals.

The operator selected broad US-listed optionable stocks/ETFs, complete holdings/watch/reentry
membership, four queues (income, protection, watch/reentry alternatives, new opportunities),
full strikes and both option sides across **7–365 DTE**, a daily scan starting **09:35 ET**, and
refreshes of all held/watched/reentry/shortlisted names every **15 minutes** during the official
exchange session. No 0DTE. Inclusion never proves suitability, research completeness or readiness.

## Capacity evidence and activation boundary

A read-only database count on 2026-10-05 at approximately 20:42Z returned **5,541 distinct active
or researched watchlist symbols**. This is a dated inventory observation, not a provider coverage
measurement. Watchlist refresh alone requires at least 5,541 / 15 = **369.4 chain requests/minute**
if each distinct symbol needs one fresh response. Twenty-six regular-session refresh cycles imply
**144,066 watchlist chain requests/day**, before other names and after deduplication within each
cycle. Reusing a snapshot younger than 15 minutes reduces overlapping full/priority work; it does
not prove a sustainable 15-minute refresh service.

| Capacity question | Current evidence |
| --- | --- |
| Provider entitlement and shared request allowance | Not verified; no new allowance assumed |
| Broad optionable source total and pagination | Receipt required; live completeness not measured |
| Chain response latency, normalized bytes, expiry/contract totals | Worker records per request; no organic full-run sample yet |
| Disk growth from immutable compressed chain versions | Not measured; archive retention requires an explicit operational decision |
| Full-run duration and oldest mandatory-name age | Not measured; must include proposal projection, not only acquisition |
| Memory and API response cost at full-universe proposal volume | Bounded chain cache and indexed coverage implemented; production peak not measured |
| Additional paid research | Existing shared acquisition queue, pending-request reuse and existing drain budget; scan acquisition itself makes no LLM call |

`config/options_scan.json` ships with `enabled: false`, no capacity approval, and no request rate.
The optional preference question offered keeping this full requirement, narrowing the priority
set, or accepting measured slower refresh. Until a recorded operator choice changes it, the full
requirement stands. No smaller service is represented as satisfying it.

Before activation, record the approved provider allowance, measured latency/bytes/disk/memory,
full and priority completion times, fairness and source failures in a capacity receipt. If the
service cannot meet the requirement, return the evidence and a concrete revised cadence or
provider arrangement for operator decision. Do not raise limits or silently trim the universe.

## Implementation and ownership

- `options_engine` remains the proposal owner. `run_options_scan.py` is its acquisition worker;
  `options_scan.sqlite3` is an operational scan/checkpoint/chain cache under the existing state
  directory. It is not a security thesis store. Research remains on the shared CIO spine and the
  existing symbol-thesis priority acquisition queue.
- Requests coalesce by profile and retain idempotency aliases. Each symbol result and immutable
  chain hash is checkpointed. Failed acquisition remains visible. Publication is a separate
  pending phase: a crash after acquisition leaves the run retryable without refetching chains.
- Full chains are read lazily with a four-entry in-process cache. Coverage indexes proposals and
  accounts by symbol. Account lots aggregate inside their account; shares never cover another
  account's short call. Nonstandard deliverables never assume a 100-share multiplier.
- Broad membership uses the existing governed Finviz HTTP path, cookie then token fallback,
  preserving its global throttle/cooldown. A CSV response alone does not establish completeness:
  the returned distinct count must reconcile with the declared source total.
- Full-chain requests use the existing Schwab read adapter and its shared rate gate, without a
  strike count and with explicit 7–365-DTE dates. Missing maps, inconsistent returned contract
  counts, empty responses and failures cannot become COMPLETE.
- While the expanded worker is disabled, the compatibility producer retains its previous bounded
  provider workload. The new coverage ledger still includes uncapped inventory and shows pending
  chains. Once activated, old generation callers become read-model readers.
- No new cron line is installed by this code change. The provided launcher uses the configured
  deployment interpreter. Proposed scheduler: one worker tick per minute, with bounded slices;
  its official NYSE calendar creates the daily and 15-minute run keys, including early closes.
  Installing it requires the usual scoped cron/config and release grants.

## API and operator contract

| Surface | Behavior |
| --- | --- |
| GET `/api/v2/options/proposals` | Cached, paginated ideas (50 default, 250 maximum); queue and readiness counts; no acquisition or paid review |
| GET `/api/v2/options/coverage` | Every known security with source lanes, research status, per-account share capacity, chain identity/status and reasons; paginated; active-run progress is read from checkpoints |
| GET holdings funnel / overview / positions | Existing producer snapshots only; absence is UNAVAILABLE, not an empty successful scan |
| POST `/api/v2/options/scans` | Queue request only; 409 CONFIG_REQUIRED while expanded scanning is disabled; no synchronous provider work |
| Validate page quotes | Explicit existing quote-validation action for the displayed page |
| Request model reviews | Explicit bounded existing review queue; opening a page does not enqueue reviews |

Four queues separate different decisions. Readiness sorts before the heuristic score. Pagination
never limits the recorded inventory. All eight expression families are represented in captured-
chain research: covered call, cash-secured put, protective put, long call, long put, credit vertical,
debit vertical and collar. Bullish and bearish verticals have coherent strikes and expiration.
Representative expressions are produced for each eligible expiry; this is not an exhaustive
search over every possible strike pair or a calibrated optimal-strategy recommendation.

Additional expressions remain `advisory_only`, blocked pending strategy policy, quote/liquidity
checks and CIO review; no new broker route is enabled. Cash-secured-put research records the
ownership-consent requirement. Research direction conflicts require review and never select a
bullish expression by default. Shared artifact identities are retained across source memberships.

Package economics use signed bid/ask cashflows and terminal payoff for the actual structure.
Probability means modeled probability of **profit after premium**, not probability of finishing
in the money or an observed win rate. Fees/slippage assumptions and IV/proxy basis are explicit;
missing/invalid evidence withholds the estimate. Existing financial gate inputs remain separately
identified and no trading threshold is lowered by this tranche.

## Verification and release acceptance

Hermetic tests cover uncapped membership, conflicts, account cover, eight package payoffs,
long-dated/no-0DTE expressions, incomplete chains, duplicate requests, crash-resumable publication,
immutable chain reuse, provider errors, missing source totals, and cached GETs. Fixture rows are
never organic decisions or trading outcomes.

Release requires local acceptance, independent review, exact candidate-SHA CI, scoped deployment
grant and matching process pins. Expanded-worker acceptance additionally requires an approved
capacity receipt and natural production receipts across **five trading sessions** showing:

1. All required memberships reconcile; source failures, unsupported instruments and exclusions
   remain explicit rather than disappearing.
2. Full and priority refresh ages meet the chosen service; no alphabetic starvation or duplicated
   paid research; acquisition and publication finish under restart/failure conditions.
3. Source identity, thesis version, chain snapshot and quote age can be followed into each idea.
4. Only verified, fresh transitions reach existing notification policy. No forced changed
   recommendations or manufactured successful outcomes.
5. Disabled agents, broker/2FA authority, trading thresholds and memory-influence settings remain
   unchanged. Advisory-family completeness is distinct from execution-family authorization.

Rollback: disable the expanded worker through the governed config path, stop its scheduled
launcher, and promote the prior approved release using normal rollback procedures. Preserve
scan/history files for investigation. No rollback deletes research or rewrites historical outcomes.

# W7 page redesign field trace

**Status:** REVIEW CANDIDATE · fixture verification, not release evidence
**Updated:** 2026-10-24

Task `DSN-20261024-w7-pages-P1-T1`; approved boards 12–15 and 17. This is the
W7 companion to the desks redesign field trace. Shared financial and CIO facts
are read through `scripts.lib.cio_truth.resolve`; W7 has no fallback aggregate,
broker caller, writer, schedule or order behavior.

| UI element | API field under `/api/v2/cio/pages` | Store / column or key | Writer / owner |
|---|---|---|---|
| Home Do now | `do_now.items`, original order, first seven | CIO ranked projection passed to `cio_truth` | CIO projection, W1 |
| Action title, reason, destination and account | `do_now.items[].{title,why,action.where,action.label,account_label}` | Original CIO record/projection evidence, order preserved | CIO InstrumentRecord writer, W1 |
| Active, pending and unprotected stops | `stops.{active_count,pending_count,unprotected_count}` | `stop_last_known` per account+symbol; planned `stops.json` is distinct | Broker-read sync / stop observations, W1 |
| Awaiting fill, nearest active stop | `stops.{awaiting_fill,awaiting_fill_count,nearest}` | Same resolved stop state; a crossed price is never a confirmed fill | W1 resolver |
| Regime, VIX, source time | `regime.{label,vix,as_of,stale,gap}` | Classifier output / registered regime projection | Regime classifier, W1; lane restoration W8 |
| Favoured sectors | `sectors.favoured` | Shared multi-horizon sector projection | W3, resolved by W1 |
| Waiting approvals | `approvals.total` | Same typed pending queue used by header | Queue writers, W1 |
| Risk losses, heat, unprotected value, largest name | `positions.{loss_at_stop_usd,portfolio_heat_pct,unprotected_value_usd,largest_name}` | Current risk projection, never stale file totals | W1 resolver / risk projection |
| Position table | `positions.rows[].{symbol,account_label,shares,price,stop_price,distance_to_stop_pct,loss_at_stop_usd,stop_source,stop_state}` | Canonical holdings and per-account observed/planned stop state | Holdings sync, W1 resolver |
| Concentration rows | `positions.concentration[]` | Current canonical aggregate | W1 resolver |
| Correlation | `/api/v2/correlation`, `correlation_matrix`, `as_of` | Published correlation cache | Correlation lane, W8 |
| Recovery evidence | `/api/v2/recovery`, `items[].{symbol,account_label,analyst_verdict,reason}` | Existing recovery projection | Recovery writer |
| CIO status and measurement time | `cio_status.evaluations[]` | One shared evaluation model | W1 resolver |
| Cash waterfall | `capital.{cash_usd,reserved_usd,earmarked_usd,investable_usd}` | Canonical holdings cash + published capital plan | W1; cash and earmarks counted once |
| Potential raise | `capital.prospective_raise_usd` | Future trims in published plan, separate from current cash | W1 |
| Class-specific concentration policy and near-limit warnings | `concentration_policy.{classes,lookthrough_company_limit_pct,lookthrough_sector_limit_pct,near_limit_fraction}`; each class `limit_pct,near_limit_pct` | One IPS concentration key, class evidence and operator approval | W1 owns classifications/limits; W10 owns R13 evaluation; W7 formats source values only |
| Cash range, current and post-plan share | `capital.{cash_band,current_cash_pct,post_plan_cash_pct}` | Confirmed investment policy and published plan | Operator policy, W1 |
| Portfolio/account look-through denominator | `lookthrough.portfolio_total_usd`, `by_account[].portfolio_total_usd` | W1 `portfolio.total_usd`, `accounts[].total_usd` | Canonical holdings aggregate, W1 |
| Position, valuation and quote clocks | `lookthrough.{as_of,valuation_as_of,quote_as_of}` | W1 `portfolio.{positions_as_of,valuation_as_of,quote_as_of}`; selected account's `accounts[].as_of` | Canonical holdings reader, W1; unknown position time stays unknown |
| Fund weights and source contributions | `lookthrough.top_underlying[].sources[]` | `fund_holdings_cache.json[fund][stock]`; W1 current holding market value | `portfolio_lookthrough_themes` writer; W7 read-only projection |
| Sectors and industries | `lookthrough.{sectors,industries}[]` | C1 `company_facts.{sector,industry}.{value,source}` bound to the same confirmed GUID | CIO company-facts writer; W7 grouping |
| Funds without data and partial fund tails | `lookthrough.{funds_without_holdings,gaps}[]` | Current fund holding value × unpublished weight fraction | W7 derived from same holdings/cache; no provider calls |
| Account sync gaps | `lookthrough.account_gaps[]` | W1 account status, value and source clock | Holdings/account registry through W1 |
| Theme exposure and target gaps | `lookthrough.{themes,theme_gaps}[]` | Existing writer's theme constants, published index constituents, `etf_fund_universe.sleeve_targets`; current underlying dollars | Existing look-through writer definitions; W7 read-only arithmetic |
| Narrative and source time | `lookthrough.narrative.{text,as_of,reason}` | `lookthrough_themes.{grok_narrative,grok_status,grok_generated_at}` | Governed look-through narrative lane |

Unknown data remains `None` with a named gap. A missing canonical denominator
never falls back to the old look-through snapshot. Funds with missing or invalid
weights remain unresolved funds. Unknown industries remain Unclassified with a
dollar amount. The fund coverage percentage uses fund value; theme percentages
use looked-through value; stock percentages use the whole portfolio.

Model refusals are withheld even if an old artifact says `grok_status: ok`.
Narrative timestamps stay separate from current holdings timestamps. Account
filters require that account's own denominator and never fall back to global.

Dependency handoffs: W1 owns `cio_truth` and current risk inputs, W5 owns
`DeskPage`, W2 owns the additive API route registration. The W7 adapter takes
`root` containing `data/`, accepts a DB query function for persisted observations,
and invokes `resolve` exactly once. It performs no network requests or writes.

Validation receipts and fixture screenshots are recorded in the persistent W7
worklog and alongside the approved mockups; fixture values are synthetic and
are not included as product defaults. Release and merge remain the coordinator's
and operator's work.

The later conflict-engine direction also binds this work: W1 supplies canonical
engine findings and W9 owns the reusable `ConflictLine` / `ConflictSheet`.
W7 performs no conflict classification, treats no raw disagreement array as a
flag, and makes no automatic resolution. That UI dependency remains pending;
missing source data and pending stop activation are still described explicitly.

Addendum 2 is binding: `EXCEPTIONS_MATRIX.md` in the conflict-resolution handoff
supersedes the original design where they differ. W10 owns tiers T0–T4, the
final R1–R16 rules and never-auto list, the 31-flag golden replay, and the urgent
governed-route worker prerequisite. W7's forwarding test preserves fields such
as `tier`, `owner`, `clears_when` and `next_run`; it is not engine acceptance.
The old 24 reference tests and 15-flag expectation are not final proof. No
queued-job drain or live activation is part of W7.

Sector display preserves W3/W1 measurement semantics: `favoured: null` is not
published (with its gap reason); a measured empty list means none favoured.
W7 never derives posture or favoured sectors from daily returns.

Addendum 3 replaces the universal concentration-cap display with W1's
class-specific policy section. Risk's largest-position card uses that
position's published classification and limit. Missing classifications have no
assigned cap and show their gap. The old operational alert threshold is not
displayed as current authority. Each class's near-limit threshold comes from
W1; the global warning fraction is formatted as a percentage. W7 does not
classify funds, compare exposures to thresholds, generate R13 findings or
rebalance anything. Account-filtered allocation percentages use that account's
basis; policy limits apply to the whole portfolio, as the UI states.

Local evidence at the source checkpoint: 53 affected tests passed with
`psycopg2` hidden; the final W7 subset has 14 passing tests. Full `npm run build`,
the four integrity ratchets, lane registry, CIO completeness and docs-index
checks passed. A copied-tree check with W1 core source `f74bea404` returned 27
positions, 14 industry groups and a 240,881-byte response. It made no DB or
provider calls and verified all copied/source hashes unchanged. Live status
and broker observations were explicitly unavailable in that check.

Mobile tap checks and screenshots are **unexecuted**. Chromium escalation for
the shared frame was rejected for expanding access beyond the configured
sandbox; the coordinator instructed W7 not to retry or use indirect execution.
The fixture preparation also stopped at `spawnSync git EPERM` before launching
a browser. Neither event is a passing UI result. W5 frame adoption, W2 route
registration, W1's final dependency and the shared conflict components must be
integrated and verified before this branch can request publication.

The final copied-state check composes frozen W1 core `f74bea404` and the pure
policy helper/config from `7bff82fdc`. It checks documented legacy ET times
against their recorded instants and verifies offset-ISO output with raw clock
provenance. Date-only policy approval remains a date in the UI; W7 never
invents midnight or guesses a timezone. The candidate IPS source and approval
reference are checked directly against the frozen config.

`apply_concentration` is W1's pure composition function. W7 calls it once only
when the core document has no authoritative class-policy section. A failed
policy read preserves portfolio facts and produces a policy gap. Complete fund
evidence has no accepted production projection yet: all 23 assessed names in
the copy check remain unclassified, with null caps and explicit gaps. The policy
table displays approved values; this is not live classification or R13 gate
acceptance. W7 does not treat a top-holdings sample as complete statistics.

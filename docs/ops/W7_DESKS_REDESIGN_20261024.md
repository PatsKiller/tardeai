# W7 page redesign field trace

Task `DSN-20261024-w7-pages-P1-T1`; approved boards 12–15 and 17. This is the
W7 companion to the desks redesign field trace. Shared financial and CIO facts
are read through `scripts.lib.cio_truth.resolve`; W7 has no fallback aggregate,
broker caller, writer, schedule or order behavior.

| UI element | API field under `/api/v2/cio/pages` | Store / column or key | Writer / owner |
|---|---|---|---|
| Home Do now | `do_now.items`, original order, first seven | CIO ranked projection passed to `cio_truth` | CIO projection, W1 |
| Action title, reason, account, stance, conviction, conflicts | `do_now.items[].{title,reason,account_label,stance,conviction,conflicts}` | Original CIO record/projection evidence | CIO InstrumentRecord writer, W1 |
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
| Policy max, alert level and cash range | `capital.{policy_max_pct,alert_level_pct,cash_band,current_cash_pct,post_plan_cash_pct}` | Confirmed investment policy and plan metadata | Operator policy, W1 |
| Portfolio/account look-through denominator | `lookthrough.portfolio_total_usd`, `by_account[].portfolio_total_usd` | W1 `portfolio.total_usd`, `accounts[].total_usd` | Canonical holdings aggregate, W1 |
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

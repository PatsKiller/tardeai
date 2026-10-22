# Options Desk served fields: accuracy contract

```
Status:      ACTIVE
as_of:       2026-10-22T11:30:00-04:00
Measured at: branch fix/options-desk-accuracy-20261022 (base 82180caba); not measured on a live pin
```

This contract lists every field that the Options Desk accuracy fix (2026-10-22) adds or changes in the API.
The Command Center (`apps/command-center-v3`) and the tooltip glossary read it. The backend computes every
field at **serve time** from data it already holds (the proposal snapshot, the thesis store, the standing
intents, the crontab or lane registry, and `options_pilot_arm.status()`). Nothing here reads a broker,
changes a flag, places an order or writes a store. It is advisory only (`MBI_BEHAVIOR = 0`).

Code: `scripts/lib/options_desk_accuracy.py` (pure functions) is wired into `scripts/api_v2.py`
(`_options_proposals`, `_options_intents`, `_options_overview`, `_options_lifecycle_get`).

Time units: every `*_age_s` is in **seconds**, computed at serve time as `now - timestamp`. Every timestamp
is ISO-8601 with an offset. Sessions use US equity hours in America/New_York: `PRE_MARKET` 04:00-09:30,
`REGULAR` 09:30-16:00, `AFTER_HOURS` 16:00-20:00, `CLOSED` otherwise, and `WEEKEND`. Exchange holidays
are not modelled.

---

## 1. `GET /api/v2/options/proposals`: top level

| field | type | meaning | source | staleness |
|---|---|---|---|---|
| `market_session` | string | **Changed.** The session **now**, when the page was served. Before the fix this was the session when the snapshot was written. | wall clock (ET) | live |
| `market_session_as_of` | ISO | When `market_session` was computed. | serve clock | live |
| `snapshot.generated_at` | ISO | When the proposal snapshot was written. | snapshot `generated_at` | n/a |
| `snapshot.age_s` | number | Age of the snapshot. | serve clock minus `generated_at` | live |
| `snapshot.session_at_generation` | string | The session when the snapshot was written. | `generated_at` | fixed |
| `snapshot.next_scheduled_refresh` | ISO or null | Next time the producer is scheduled to rewrite the snapshot. Null when no active schedule is found. | active crontab lines for `run_options_monitor.sh`; if the crontab cannot be read, `config/lane_registry.json` lane `run-options-monitor` | live |
| `snapshot.refresh_lane` | string | Lane id of the producer (`run-options-monitor`). | constant | n/a |
| `snapshot.refresh_schedule` | string[] | The cron expressions used, in host local time (ET). | as above | live |
| `snapshot.refresh_schedule_source` | string | `crontab`, `crontab_snapshot` or `lane_registry`. If it is `lane_registry`, the crontab was unreadable and the schedule is the registered one, not the observed one. | as above | n/a |
| `snapshot.refresh_paused` | `{since, note}` or null | Present when the producer's crontab line is commented `# PAUSED <date> ...`. | crontab | live |
| `execution_state_text` | string | One plain sentence describing the execution state, for example: "Manual only: you can send an approved option order yourself with per-order 2FA. Nothing trades automatically. 0 of 5 ideas eligible now." | derived from `options_pilot_arm.status()` (`armed_for_execution`) and the cards' `enterprise.live_eligible`. Read only: it never changes a flag. | live |
| `execution_state` | object | Structured form: `{state: "MANUAL_ONLY"\|"OFF"\|"UNKNOWN", armed: bool\|null, automatic_trading: false, per_order_2fa_required: true, eligible_now: int, total: int, text}`. `automatic_trading` is always false: the options desk has no automatic submit path. | as above | live |
| `intent_conflicts` | list | One row per card that works against an active standing intent on the same symbol: `{proposal_id, symbol, account, strategy, directive_id, intent_goals, kind, text}`. `kind` is `HEDGE_VS_ACCUMULATE` (a protective or long put while the intent is to accumulate or earn income) or `ACCUMULATE_VS_HEDGE` (a cash-secured put or long call while the intent is to hedge, reduce or exit). | standing intents (`ticker_watch_directives.spec.options_intent`, status `active`) | live |
| `proposal_groups` | list | Cards that differ only by account, merged: `{group_key, symbol, strategy, contract, account_count, legs: [{proposal_id, account, contracts, shares_held, premium_total}]}`. Only groups with two or more accounts are listed. | the cards | snapshot |
| `coverage.status_counts` | object | **Changed.** Honest counts. When the expanded scan is disabled, inventory symbols the legacy pass never looks at are counted as `NOT_SCANNED_EXPANDED_SCAN_DISABLED` instead of `PENDING`. `PENDING` now means held symbols, which the legacy pass does evaluate, with no result yet. | snapshot coverage rows plus `config/options_scan.json` `enabled` | snapshot |
| `coverage.status_counts_raw` | object | The counts as written by the producer, kept for audit. | snapshot | snapshot |
| `coverage.not_scanned` | `{count, reason}` or null | `reason` = "not scanned (expanded scan disabled)". | as above | snapshot |
| `coverage.pending_evaluation_count` | int | Real pending work only. | as above | snapshot |
| `strategy_overview.avg_pop` | number or null | **Changed.** Null when no card has a populated `pop_pct`. It was previously 0.0. | cards | snapshot |
| `strategy_overview.avg_pop_n` | int | How many cards the average used. | cards | snapshot |
| `strategy_overview.total_edge_avg` | number or null | Null when no card has a scored edge. Withheld edges (see `edge_status`) are excluded. | cards | snapshot |
| `strategy_overview.total_edge_n` | int | How many cards the edge average used. | cards | snapshot |

## 2. `GET /api/v2/options/proposals`: per card (`proposals[]`)

### Quote clock (item 2)

| field | type | meaning | source | staleness |
|---|---|---|---|---|
| `quote_time` | ISO | Unchanged. The provider's quote time for the option contract. On a spread it is the oldest leg. | chain contract `quote_time` | fixed |
| `quote_age_s` | number or null | Age of the option quote. | serve clock minus `quote_time` | live |
| `quote_session` | string or null | **New.** The session the quote was taken in, for example `AFTER_HOURS` for a 16:00:00 closing quote. This replaces the run-start session that was copied onto every card. | `quote_time` | fixed |
| `underlying_price` | number | Unchanged. The spot used for this card. | chain underlying, else technicals or holdings | fixed |
| `underlying_price_source` | string | Where the spot came from, for example `schwab_chain_underlying`. | `price_source.source` | fixed |
| `underlying_price_time` | ISO or null | The provider's underlying quote time when it is recorded. Otherwise the fetch time. | `price_source.quote_time`, else `price_source.as_of` | fixed |
| `underlying_price_time_basis` | string | `provider_quote_time` or `fetch_time`. `fetch_time` means the provider quote time was not recorded, so the age is a lower bound. | as above | n/a |
| `underlying_price_age_s` | number or null | Age of the spot. | serve clock | live |
| `chain_fetched_at` | ISO or null | When the option chain was read. | engine `_chain_fetched_at` | fixed |
| `chain_age_s` | number or null | Age of the chain read. | serve clock | live |
| `quote_stale` | bool | True when `quote_age_s` is unknown or over the desk cap (`hard_quote_max_age_seconds`, default 120 s). | desk config | live |

### Lifecycle and next step (item 3)

| field | type | meaning |
|---|---|---|
| `lifecycle_stage` | string | `CREATED`, `RESEARCH_QUEUED`, `RESEARCH_COMPLETE`, `CIO_REVIEW_QUEUED`, `CIO_REVIEW_FAILED` (below the cap, still retrying), `REVIEW_FAILURE_CAP` (the CIO review stopped after `max_review_failures` failures), `DECISION_ISSUED`, `CIO_FOLLOWUP_RESEARCH`, `FOLLOWUP_COMPLETE`, `EXTERNAL_RESEARCH`, `REOPENED`, `ARCHIVED_ABANDONED`, or `UNKNOWN`. Source: the thesis store timeline on the card (`lifecycle`). |
| `lifecycle_stage_label` | string | Plain words for the stage. |
| `review_failures` | int | Failed CIO review attempts since the last decision or reopen. |
| `review_failure_reason` | string or null | The latest failure reason, for example `POLICY_NOT_ALLOWED`. |
| `review_workflow.next_action` / `.owner` | string | **Changed.** Now based on the lifecycle stage and the current session. `REVIEW_FAILURE_CAP` gives next_action "CIO review stopped after 3 failures (policy refusal POLICY_NOT_ALLOWED) · operator reopen needed" and owner "Operator". A stale quote during `REGULAR` gives "Re-quote now" (owner "Quote validation"). Outside `REGULAR` it gives "Re-quote after the open (market <session>)". |
| `review_workflow.lifecycle_stage` | string | The stage the next step was derived from. |

### Edge (item 4)

| field | type | meaning |
|---|---|---|
| `edge_score` | number or null | **Changed.** The heuristic score minus a liquidity and spread penalty. **Null** when the liquidity gate failed: the score is withheld, not zero. |
| `edge_score_raw` | number | The score before the penalty, kept for audit. |
| `edge_status` | string | `SCORED` or `WITHHELD_LIQUIDITY`. |
| `edge_withheld_reason` | string or null | For example, "liquidity gate failed: spread 18.0% > 12%". |
| `edge_liquidity_penalty` | number | Points subtracted: `min(15, 0.75 x spread%)`, plus 3 if open interest is under twice the floor, plus 2 if volume is 0. |
| `edge_inputs.conviction` / `.conviction_basis` | number / string | For a protective put, conviction is a fixed 0.55 placeholder. It is not a per-symbol signal, and the basis says so. |

### Cash-secured put metrics (item 5)

| field | type | meaning |
|---|---|---|
| `premium_basis` | string | `bid`: a CSP is priced at the bid, which is what a seller receives. |
| `premium_over_collateral_pct` | number | `bid / strike x 100`. The premium for this one trade as a percent of the cash set aside. |
| `simple_annualized_yield_pct` | number | `premium_over_collateral_pct x 365 / DTE`. **Not repeatable and not expected return.** It assumes the same trade could be repeated all year at the same price. |
| `yield_basis` | string | That caveat, in words. |
| `risk_reward` | null | **Changed for CSP.** Not applicable. |
| `not_applicable_metrics` | string[] | `["risk_reward", "max_loss_to_zero"]`. The UI must hide these for CSP. `max_loss` is kept for the risk gates, but it is the loss if the stock goes to zero and is not a useful headline. Show `economics.net_cost_if_assigned_total` instead. |

### Earnings (item 6), on cards with an active standing intent

| field | type | meaning |
|---|---|---|
| `earnings_dates` | object or absent | `{provider_date, provider_source, operator_estimate, operator_source, conflict, conflict_days, effective_date}`. `conflict` is true when both dates exist and differ by more than 3 days. `effective_date` is the **earlier** of the two, which is what "avoid crossing earnings" uses. |

### Conflicts, grouping and holding (items 8 and 9)

| field | type | meaning |
|---|---|---|
| `intent_conflict` | object or null | The same row as in the top-level `intent_conflicts`. |
| `group_key` | string | `SYMBOL|strategy|contract_guid` (falls back to `SYMBOL|strategy|type|strike|expiration`). Cards with the same key are the same idea in different accounts. |
| `group_size` | int | How many accounts carry this idea. |

## 3. `GET /api/v2/options/intents`

| field | type | meaning |
|---|---|---|
| `intents[].held` | bool | True when any account holds shares of the symbol. |
| `intents[].shares_held_total` | number | Total shares across accounts. |
| `intents[].watch_only` | bool | True when nothing is held, as with NFLX. The intent is a watch or entry plan, not a plan on a holding. |
| `intents[].held_source` | string | `match.shares_by_account` or `options_engine_holdings` (the desk's own holdings loader). |
| `intents[].earnings_dates` | object | The same shape as the card `earnings_dates`. |
| `intents[].matches.earnings` | object | **Changed.** It still has `{date, source}`, and `date` is now the effective (earlier) date. It adds `provider_date`, `provider_source`, `operator_estimate`, `operator_source`, `conflict` and `conflict_days`. |
| `intents[].conflicts` | list | Desk cards on this symbol that work against the intent, in the same rows as `intent_conflicts`. |
| CSP rows `matches.plays.cash_secured_put[]` | | **Changed.** `credit_per_contract` = **bid** x 100, `credit_basis` = `"bid"`, `credit_per_contract_at_mid` is kept for comparison, `premium_over_collateral_pct` = bid / strike x 100, `simple_annualized_yield_pct` = that x 365 / DTE (not repeatable), `breakeven` = strike - bid. `return_pct` and `annualized_pct` are kept as **deprecated aliases** of the bid-based values. |

## 4. `GET /api/v2/options/overview`

`proposals.avg_pop` and `proposals.total_edge_avg` follow the same null rule as section 1. `market_session`
and `snapshot` are added with the same meaning as in section 1.

## 5. `GET /api/v2/options/lifecycle` (N1)

| field | type | meaning |
|---|---|---|
| `generated_at` | ISO | Unchanged: when the lifecycle runner wrote the payload. |
| `age_s` | number or null | Serve clock minus `generated_at`. |
| `freshness` | object | `{state: "FRESH"\|"STALE"\|"PAUSED"\|"UNKNOWN", text, producer_lane: "options-lifecycle-run", paused_since, paused_note, next_scheduled_run}`. `PAUSED` comes from a commented crontab line `# PAUSED <date> ...` for `options_lifecycle_run.py`, and the text then reads "PAUSED since <date> (<note>); last payload <age> old". `STALE` means the payload is older than 2x the producer's cadence (20 min) during market hours. |
| `health[check=monitor_freshness]` | object | **Changed.** It is recomputed at serve time from `generated_at`, and the write-time verdict is kept as `detail_at_write`. Before the fix it said "20 min old" forever. |

The `entry_receipts` error `operator does not exist: uuid = text` comes from
`scripts/options_lifecycle_intake.py::reconcile_reviewed_entries`. That code joins `schwab_pilot_orders` to
`broker_order_intents` and then reads broker orders. It is in the broker execution subsystem, so this fix
does **not** change it. See "Not changed" below.

## 6. Behaviour changes that are not new fields

- **Item 1, session per quote.** The engine stamps each card with the session of its **quote time**, not
  the session when the run started. The liquidity deferral ("awaiting live quotes", `liquidity_deferred`)
  follows the quote session, so a quote taken at 09:31 in the regular session is never deferred as
  pre-market. `price_basis` and `economics.market_session` name the quote session.
- **Item 12, approval-queue expiry.** `sync_approval_queue` now also expires **blocked** rows after
  `expires_at`, using the same `rejected` / `system_expiry` bookkeeping as pending rows, with a distinct
  `review_note`. Blocked rows can never be approved, so no order path is affected.
- **Item 13, abandon before liquidity skip.** An idea blocked on liquidity is now still archived after
  `abandon_after_hours` (48h) when its thesis is incomplete. Before the fix, the liquidity skip came first,
  so the idea was never archived.

## Evidence

- **Tests.** `tests/test_options_desk_accuracy_20261022.py` has 24 tests, registered in
  `config/ci_gates/options_desk_accuracy_20261022.json`. On base `82180caba` the file fails to collect,
  because the helper module does not exist yet. With only the new helper module copied onto base, the 10
  tests that exercise changed existing code still fail: the engine liquidity deferral, the
  review-failure-cap and re-quote steps, intent CSP at the bid, engine CSP at the bid, both earnings dates,
  both expiry-sweep tests, the abandon ordering, and the null average POP. On this branch all 24 pass.
  `[VERIFIED]` 2026-10-22, repo `.venv`.
- **Replay.** The captured production payloads of 2026-10-22 10:57 ET were run through the serve-time pass:
  - The SPCX protective put shows `quote_session` AFTER_HOURS, a quote 68,228 s old, and lifecycle stage
    REVIEW_FAILURE_CAP. Its next step is "CIO review stopped after 3 failures (policy refusal
    POLICY_NOT_ALLOWED) · operator reopen needed" (owner Operator). Its edge goes from 68.4 to 62.3, it is
    flagged HEDGE_VS_ACCUMULATE against directive 17, and it is grouped with the taxable-account copy.
  - SCHG, XAR and XLB have their edge withheld because they failed the liquidity gate.
  - Coverage reads EVALUATED 4 and NOT_SCANNED_EXPANDED_SCAN_DISABLED 5,642 (it was PENDING 5,642).
  - The lifecycle tab reads "PAUSED since 2026-10-14 (schwab-app-deactivated (incident SPCX)); last payload
    7.8 days old".
  - For SPCX earnings, the provider date is 2027-02-09 and the operator estimate is 2026-11-03, so
    `conflict` is true and the dates are 98 days apart.

  `[VERIFIED]` replay script output, 2026-10-22.
- **Item 12 dry run** (`expire_stale_queue_rows(cur, apply=False)`, a single SELECT that was then rolled
  back, measured 2026-10-22T15:38:37Z): `would_expire = {"blocked": 3148}`, with no pending rows. Of the
  3,175 open blocked rows, 27 are still inside their 24-hour window. The oldest `expires_at` is
  2026-06-27. **The first desk cycle after this change is released will close 3,148 blocked rows** as
  `rejected` / `system_expiry`. `[VERIFIED]`

## Not changed (operator or grant needed)

- `scripts/options_lifecycle_intake.py:118-124`: the SQL `JOIN broker_order_intents i ON i.intent_id=po.intent_id`
  compares `uuid = text`. The suggested fix is `i.intent_id::text = po.intent_id`, or a cast the other way
  after checking the column types. The file reads broker orders (`schwab_transport.get_orders_raw`), so
  changing it needs an `execution-engineering` grant.
- The per-card `execution_mode: "auto_or_manual"` / `execution_label: "Schwab · auto or manual"` labels
  are legacy profile labels from `options_engine._execution_profile`. The UI should show
  `execution_state_text` instead. Changing the profile itself was out of scope (item 7: do not change the
  flags).
- The protective-put conviction constant (`options_engine.py`, `conviction=0.55`) is unchanged and is now
  labelled. Replacing it with a real per-symbol input is a model change for a later wave.

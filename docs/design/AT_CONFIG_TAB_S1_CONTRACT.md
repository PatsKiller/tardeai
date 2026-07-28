# Active Trader Configuration Tab — S1 API Contract (`/api/v3/active-trader/config`)

Stage: **AT-CFG-S1** · Contract id: `active-trader-at-cfg-s1-read-v1` · **READ-ONLY, GET-only.**

This document is the STABLE shape the React frontend is built against. Backend:
`scripts/active_trader/config_read.py :: config_overview() -> dict`, dispatched at
`scripts/active_trader/read_http.py` (suffix `config` | `config-overview`), reachable through the
existing v3 read plane in `scripts/portfolio_server.py` (`_is_active_trader_read_path`).

## Request

```
GET /api/v3/active-trader/config
```

No query parameters. No request body. Any non-GET method → **HTTP 405** with `{"write": false}`.
The frontend does ONE fetch and receives all eight panels.

## Global rules (guaranteed, testable)

- No mutation surface anywhere. No POST/PUT/PATCH/DELETE handler exists.
- **No secret VALUE is ever emitted** — not masked, not truncated. Credential slots are
  `{name, populated}` only. (`test_no_known_secret_value_in_payload`, `test_no_secret_like_token_patterns`.)
- Unsourced value → `{"value": null, "status": "unknown", "reason": "..."}` (the "unknown object").
  Any field in the contract below MAY take this shape when the underlying source is missing/unreadable.
- Timestamps are ISO-8601 strings (UTC or with offset) or `null`.
- Fail-closed: a panel that errors degrades to `{read_only, authority, status:"unknown", reason:"..."}`.

## Envelope (top level)

| field | type | notes |
|---|---|---|
| `contract` | string | `"active-trader-at-cfg-s1-read-v1"` |
| `stage` | string | `"AT-CFG-S1"` |
| `write` | bool | always `false` |
| `canary` | bool | always `false` |
| `read_only` | bool | always `true` |
| `auto_route` | bool | always `false` |
| `generated_at` | string | ISO-8601 UTC |
| `authority` | object | `{mutation, order, session_authorize, canary, financial_action}` — all `false` |
| `db_available` | bool | whether the DB connection succeeded this call |
| `strategy_registry` | object (panel) | see below |
| `setup_taxonomy` | object (panel) | |
| `criteria_matrix` | object (panel) | |
| `data_sources` | object (panel) | |
| `feed_tier_ladder` | object (panel) | |
| `job_health` | object (panel) | |
| `execution_posture` | object (panel) | |
| `provenance` | object (panel) | |

**Every panel object also carries** `read_only: true` and
`authority: {mutation:false, order:false, financial_action:false}`.

---

## Panel 1 — `strategy_registry`

```
{
  read_only, authority,
  source: string,
  note: string,
  strategies: [ StrategyEntry ]
}
```

`StrategyEntry`:

| field | type | notes |
|---|---|---|
| `key` | string | strategy id (e.g. `momentum_scalp`) |
| `db_present` | bool | row exists in `strategy_registry` |
| `status` | string\|null | e.g. `TESTING`, `UNVALIDATED` |
| `active` | bool\|null | `strategy_registry.active` |
| `state` | string | derived: `enabled` \| `suspended` \| `shadow_candidate` \| `unknown` |
| `last_yaml_sync_at` | string\|null | ISO |
| `config_file` | string \| unknown-object | repo-relative path (momentum_scalp) |
| `git_sha` | string\|null | `git log -1 --format=%h -- <file>` |
| `last_modified` | string\|null | ISO commit date of the file |
| `review_gate` | object \| unknown-object | only fully populated for `momentum_scalp` |
| `drift` | object | see below |

`review_gate` (momentum_scalp):
```
{
  thresholds: {min_closed_validation_trades, min_win_rate, min_profit_factor, min_calendar_months},
  progress_yaml_performance_context: {closed_paper_trades, win_rate, profit_factor, ready_for_review, last_updated},
  progress_db_scorecard: {scorecard_date, closed_count, win_count, loss_count, win_rate, avg_r, sample_quality} | unknown-object,
  gate_met: bool
}
```

`drift` (momentum_scalp — the reconciliation core of the tab):
```
{
  has_drift: true,
  float_ceiling: {
    agree: bool,                       // false live (YAML 20 vs DB 100 vs engine 30)
    values: {
      yaml:  {value, preferred, source},
      db:    {value, source},
      engine:{value, source},
      finviz_running_screen: {value, source}
    },
    note: string
  },
  stop_cap: {
    agree: bool,                       // false live (8% cap vs 15% disqualifier)
    values: {yaml_fallback_cap:{value,source}, yaml_disqualifier:{value,source}, engine_alt:{value,source}},
    note: string
  }
}
```
For non-`momentum_scalp` strategies `drift` is `{has_drift:false, note, db_values:{...}|null}`.

---

## Panel 2 — `setup_taxonomy`

```
{
  read_only, authority,
  source, registry_version, registry_hash,
  setups: [ {
    setup_id, display_label, family,
    strategy: string,
    operating_state,               // SHADOW | MANUAL_PAPER_TEST_ONLY | DISABLED
    required_data_tier,            // T0 | T1 | T2
    defining_criteria: {entry_rule, invalidation_rule, stop_rule, required_inputs}
  } ],
  persisted: {
    table: "scalp_ignition_events",
    by_session_date: [ {session_date, total, primary_setup_id_populated,
                        primary_setup_label_populated, setup_state_populated} ],
    total_rows: int,
    primary_setup_id_populated_total: int,
    primary_setup_id_null_total: int,
    fully_null: bool,              // true live — taxonomy 100% NULL on all rows
    note: string
  }
}
```

---

## Panel 3 — `criteria_matrix`

```
{
  read_only, authority, source, note,
  strategies: {
    momentum_scalp: {
      criteria: [ Criterion ],
      _classifier_guard_evidence: {
        rule: string,
        enforcing_lines: [ {file, lines, quote} ]   // S0.5 guard: social never counts toward GO
      }
    }
  }
}
```

`Criterion`:

| field | type | notes |
|---|---|---|
| `criterion` | string | `float_ceiling`, `min_rvol`, `min_gap_pct`, `price_band`, `min_volume`, `min_score`, `market_cap`, `rsi`, `sma`, `sector`, `yield`, `stop_cap`, `verified_catalyst` |
| `yaml_value` | any \| unknown-object | value from strategy YAML |
| `db_value` | any \| unknown-object | `strategy_registry`; unknown-object when not stored |
| `running_value` | any \| unknown-object | running screen/engine value |
| `agree` | bool\|null | do the three agree? `false` for `float_ceiling` and `stop_cap` (verbatim contradictions) |
| `counts_toward_match_minimum` | bool | S0.5 classifier: real criteria `true`, non-gating `false` |
| `note` | string (optional) | contradictions quoted here |

`price_band` values are `[min, max]` arrays.

---

## Panel 4 — `data_sources`

```
{
  read_only, authority, source,
  sources: [ Source ],
  stale_sources: [ string ]        // names whose freshness.status == "stale"
}
```

`Source`:

| field | type | notes |
|---|---|---|
| `name` | string | e.g. `momentum_scalp_finviz_screen`, `finviz_screeners`, `alpaca_iex_minute_bars`, `scalp_ignition_events`, `monitored:<provider>`, `drive_doc_sync` |
| `consuming_strategies` | array \| unknown-object | |
| `query_definition` | object | **Finviz sources carry the FULL filter string** (`finviz_url` / `finviz_url_filters`), never a friendly name |
| `refresh_cadence` | string \| unknown-object | from crontab / schedule column / max_stale_minutes |
| `cadence_interval_seconds` | int (optional) | |
| `output_table` | string\|null | |
| `last_successful_run` | string\|null | ISO |
| `row_count` | int\|null | |
| `newest_row_age_seconds` | number\|null | |
| `freshness` | object | `{age_seconds, interval_seconds, stale_threshold_seconds, status}` or unknown-object. Computed against THAT source's OWN interval |
| `monitor_status`,`degraded` | (monitored providers) | from `data_source_health` |

`drive_doc_sync` is present but `freshness.status:"unknown"` with a reason — LIVE `data_source_health`
has no `source_key='drive'`, so it is reported honestly, never fabricated.

---

## Panel 5 — `feed_tier_ladder`

```
{
  read_only, authority, source,
  entitlement_matrix: { consumers: {..}, feed_availability: {iex, sip, polygon, moomoo_l2} },
  tier_ladder: [ {tier, label, size_multiplier, assumed_slippage_bps} ],  // ordered by quality_order
  quality_order: ["T2","T1","T0"],   // best data -> worst
  invariant_ok: bool,
  invariant_violations: [ {between:[a,b], field:"size_multiplier"|"assumed_slippage_bps", values:[..], expected} ],
  invariant_definition: string
}
```

Invariant: as quality descends (`quality_order`), `size_multiplier` is **non-increasing** AND
`assumed_slippage_bps` is **non-decreasing**. Live: T2(1.0,8) → T1(0.7,20) → T0(0.4,40), `invariant_ok:true`.

---

## Panel 6 — `job_health`

```
{
  read_only, authority, source,
  volume_profile_coverage: {
    table, symbols, min_sessions_required,
    symbols_below_minimum, symbols_below_minimum_list: [string],
    newest_built_at, newest_built_age_seconds
  },
  scanner: {table, last_run, last_run_age_seconds, cadence},
  nightly_refresh: {job, schedule, last_success_proxy, last_success_age_seconds},
  backfill_rollup: {backfill_days, lookback_sessions, status},
  jobs_behind_schedule: [ {job, age_seconds, expected_interval_seconds} ]
}
```

---

## Panel 7 — `execution_posture`

```
{
  read_only, authority, source,
  flags: {
    ALPACA_MODE: {value, source_of_truth},
    LLM_DISABLE_LIVE_EXECUTION: {value, source_of_truth},
    broker_live_enabled: {value, source_of_truth, last_changed},
    schwab_pilot_standing_unlock: {value, source_of_truth, last_changed},
    pilot_armed_until: {value, source_of_truth, last_changed},
    scalp_signal_engine_enabled: {value, source_of_truth},
    autonomous_live_submit: unknown-object,   // no scalar flag exists
    live_trading_interlock: unknown-object     // composite guard, not a scalar
  },
  standing_db_unlock: {
    unlocked: bool,
    scope: "persistent" | "session_or_dated",
    pilot_armed_until, active_approvals: int,
    routable_accounts: [string], remaining_gate: string, note: string
  },
  broker_accounts: [ {account_key, environment, is_enabled, api_write, api_read, credential_slot_name} ],
  credential_slots: [ {name: string, populated: bool} ],   // NAME + bool ONLY — never a value
  secret_values_present: false,
  note: string
}
```

**`credential_slots` NEVER contains a value, masked value, or prefix.** `credential_slot_name` on
broker accounts is the slot NAME only.

---

## Panel 8 — `provenance`

```
{
  read_only, authority,
  config_commit_sha: string|null,     // git rev-parse --short HEAD
  working_tree_clean: bool,
  config_files: { <key>: {path, git_sha, last_modified} },   // momentum_scalp, scalp_signal_engine,
                                                             // scalp_setup_registry, finviz_momentum_scalp_screen
  fetched_at: string                  // ISO-8601 UTC
}
```

---

## Stability notes for the frontend

- Panel keys and the envelope are STABLE. New fields may be ADDED within panels; existing field
  names/types will not change without a contract-id bump.
- Treat any `{value:null, status:"unknown", reason}` object as "not sourced" and render the reason.
- `agree:false` on `float_ceiling`/`stop_cap` is EXPECTED (intentional live contradictions), not an error.

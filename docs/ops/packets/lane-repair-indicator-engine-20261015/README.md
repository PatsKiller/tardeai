# Lane repair 2026-10-15: build-symbol-profiles, watchlist entry planner, indicator-engine

```
Status:      PACKET (code fix in the PR; the indicator-engine cron line is NOT APPLIED — operator cron grant)
as_of:       2026-10-15
Authority:   operator 2026-10-15 "turn these on and then re-engineer them for n8n"; AGENTS.md §23.11, §23.19, §23.23
Target:      crontab line 262 (indicator-engine) only; no unit, no n8n workflow, no live n8n lane
Live apply:  apply.sh under an active `cron` grant naming this packet; rollback.sh reverses it byte-exact
```

Operator, 2026-10-15: "turn these on and then re-engineer them for n8n". The lane-disposition audit
(`docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.md`, branch `n8n/lane-disposition-wave1-20261015`) found
three broken lanes. This packet records the root causes, the code fix (in the same PR), the dry runs, the n8n shadow
wiring, and the one operator step: the indicator-engine cron line needs a new argument.

The cron line is the only part that needs the operator. The PR changes no crontab line, unit or n8n workflow, and it
does not activate a new live n8n lane. The 2026-10-15 audit froze those; the PR adds shadow wiring only.

## Root causes

| Lane | Symptom | Root cause | Evidence |
|---|---|---|---|
| `build-symbol-profiles-at-0-19`, `build_symbol_profiles_watchlist` | `psycopg2.OperationalError: SSL connection has been closed unexpectedly`, sometimes `LockNotAvailable`, always at the first `upsert_profile` | `run()` opened a transaction with its universe SELECTs and kept it open through `_finviz_map` (6 Finviz views over hundreds of tickers) and the per-symbol yfinance calls. db_adapter sets `idle_in_transaction_session_timeout = 120s`, and the role sets `2min`, so the server killed the session before the first write. The one long write transaction also held every upserted row lock until the final commit, so a concurrent profile writer hit `lock_timeout` (3 s). | `logs/symbol_profiles_watchlist.log` tracebacks 10-11 to 10-15 (`symbol_profiles_writer.py:352 cur.execute`). Receipts `build-symbol-profiles-at-0-19_last.json` and `build_symbol_profiles_watchlist_last.json` show `status failed`, `error OperationalError`, `ok_at null` (10-15 06:40 to 07:06; the stale universe that day was 569 symbols). Server: `SHOW idle_in_transaction_session_timeout` = `2min`. |
| `watchlist-entry-planner-limit`, `watchlist-entry-planner-scope` | `InterfaceError: cursor already closed` at `UPDATE watchlist_entry_plans SET alerted_at=now()` | That UPDATE runs right after `_alert()` returns True, so it is reached only after an alert was actually sent. The send path, `telegram_alert`, ends in comms delivery settlement. `scripts/lib/comms/delivery.py _persist_event_settlement_pg` then called `conn.close()` on `db_adapter._get_conn()`. That is the thread-local connection the planner's cursor was using. As a result `alerted_at` was never stamped, so the 20 h dedup could alert again, and the drain stopped at the first alert. | `logs/entry_planner.log`: every traceback 09-25 to 10-14 is at `watchlist_entry_planner.py:568` after an alert-eligible plan. Receipts `watchlist_entry_planner_last.json` and `..._proposals_last.json` show `error InterfaceError`, `ok_at null`. None of the other comms helpers closes the shared connection. |
| `indicator-engine` | Exit 0 every weekday, but no work is done | The 08:00 line `$PY scripts/indicator_engine.py` runs the module's `__main__` CLI test mode. That is `analyze_confluence('AMD', 'scalp')`, printed to the log: no universe, no write, no reader. | `logs/indicator_engine.log` holds only AMD scalp key levels. Inventory row cron:L260 says "prints AMD 'scalp' confluence". |

## Fixes (code, this PR)

- **build_symbol_profiles.py**
  - The read transaction ends (`conn.rollback()`) before the first provider call.
  - Each symbol is one short transaction, through `_upsert_one`, which gets a fresh connection from `db_adapter._get_conn()` (it pings an idle connection and rebuilds a dropped one).
  - A lock timeout is retried once (`profile_lane.db_lock_retry_sleep_s`, default 2 s). After a second failure the symbol is skipped with the reason `db_lock_timeout`.
  - A dropped connection is rebuilt and retried once. After a second failure the reason is `db_connection_lost`.
  - A yfinance miss for a symbol, such as VIX or ABB (404 every week), is the typed skip `provider_no_profile`. It is no longer a failure that kept `ok_at` from ever advancing.
  - A lost or rejected write, or no rows written when there was work, gives exit 1 and a failed receipt.
- **lib/comms/delivery.py**: the `conn.close()` of the shared thread-local connection is removed at its source.
- **watchlist_entry_planner.py**
  - `run()` is now `plan_run(alerter=_alert)`.
  - The candidate read and the analyst read are committed before the bars and LLM calls.
  - After a send, the connection is checked again with `_live()` before the `alerted_at` UPDATE.
  - The run reports typed skips: `no_bars`, `llm_lane_error`, `llm_unparseable`.
- **watchlist_entry_planner_lane.py (new)** is the n8n entry and only plans.
  - It imports `preview`, `plan_run` and `receipt_name`, but never `_alert`, so `advisory_lane_guard.scan_entry` finds no sender in its reach. The cron entry reaches `send_telegram` and api_v2 order verbs.
  - `--lane` is dropped, because a provider-selecting token is refused on a dispatched argv.
- **indicator_engine.py --universe** (logic in `scripts/lib/indicator_universe_lane.py`)
  - The universe is the selection of `indicator_cache_refresh.py` (the cache's existing producer), and the SQL is identical (a test pins it).
  - Internal fund codes (`holding_proxies`) are excluded.
  - Rows that are missing or older than `universe_lane.stale_after_hours` (6 h) are recomputed, missing ones first, then the oldest.
  - The run is capped at `max_symbols` (400).
  - The upsert is keyed `(symbol, profile)` with profile `swing`, so the lane is idempotent: a second run in the window writes nothing.
  - Config lives in `config/indicator_strategies.yaml` `universe_lane`.
  - The bare line still runs the CLI test mode, so the cron line needs `--universe` (see below).
- **LaneOutput@v1** (`scripts/lib/lane_output.py`): every run carries `produced_count`, `attempted_count`, `skipped_reasons` and `empty_reason`.
  - A real run puts them in the receipt `summary.output`.
  - Every mode prints one bounded `LANE_OUTPUT {...}` line on stderr, which the executor keeps as `stderr_tail` on the RunReceipt. These are the audit's §7 attempt-evidence fields.

## Dry runs (no writes; `dry_run_proof_20261015.json`)

All five ran on READ ONLY sessions against production. Receipts and DB counts were the same before and after
(`symbol_profiles` 3348, `watchlist_entry_plans` 21426, `indicator_confluence_cache` 1930).

| Lane | Command | Result |
|---|---|---|
| indicator-engine | `indicator_engine.py --universe --dry-run` | universe 874, 10 proxy codes excluded, stale 24, `would_compute 24`; LANE_OUTPUT `attempted_count 24` |
| build-symbol-profiles-at-0-19 | `build_symbol_profiles.py --dry-run` | Offline plan (refactor shard 05 contract: no env, no DB); LANE_OUTPUT `empty_reason dry_run_offline` |
| build_symbol_profiles_watchlist | `build_symbol_profiles.py --watchlist-top 300 --dry-run` | 569 stale, `would_fetch 569` (the same 569 the 10-15 07:06 run died on) |
| watchlist-entry-planner-limit | `watchlist_entry_planner_lane.py --limit 60 --buy-rated-cap 400 --dry-run` | 378 candidates; LANE_OUTPUT `attempted_count 378` |
| watchlist-entry-planner-scope | `watchlist_entry_planner_lane.py --scope proposals --dry-run` | 71 candidates; LANE_OUTPUT `attempted_count 71` |

## n8n wiring (shadow only; AGENTS.md §23.11 4.4.0 cron-row shape, §23.19, §23.23)

- **build-symbol-profiles-at-0-19** is in SHADOW, wave `R2-05` (the refactor shard 05 proposal is taken), class
  `ingest`, `dispatch.mode dry_run`.
  - Allowlist: `live_arg null`, lock `/tmp/symbol_profiles.lock` (flock; this is the cron line's lock).
  - Output signal: `data/runtime/build-symbol-profiles-at-0-19_last.json`.
  - The SW4 exclusion is released. Its reason was the shared receipt, and that is gone.
- **indicator-engine** is in SHADOW, wave `LR-W1`, class `ingest`, `dispatch.mode dry_run`.
  - Allowlist command: `$PY scripts/indicator_engine.py --universe`, `live_arg null`.
  - The lock `/tmp/indicator_engine.lock` is PROPOSED, because the cron line has no flock until this packet is
    applied.
  - The registry `output_signal` is now the receipt `data/runtime/indicator-engine_last.json`. **It stays stale until
    this packet is applied, and that is the truth:** the lane does no work today. The old signal was the cron log's
    mtime, which proves only that cron opened a file.
- **watchlist-entry-planner-limit / -scope** are STAGED (`r1_pending`, shadow, class `llm`).
  - The R1 llm class needs `llm_route` via `cio-governed-bridge` with a routed process.
    `watchlist_entry_planner` is registered in `config/llm_process_registry.json`, but
    `scripts/lib/governed_process_routes.py` has no route for it. The executor would refuse
    `llm_process_route_not_registered`.
  - Adding that route is a bridge-server change and an operator decision. Activating the lane after that is one
    registry-train PR.
  - Allowlist entries: the plan-only lane entry, `live_arg null`, cron locks. Effect keys are staged
    (`effects: append`, `cron_claim false`, `n8n_claim false`), because every live run INSERTs plan rows.
- **Health contracts** for all four rows are `REVIEWED` (agent-reviewed; awaiting the operator's REVIEW pass). Each
  carries an `N8nExpectedOutput@v1` block, so zero output is a failure:

  | Lane | Rule | Allowed empty reason | Fatal skip reasons |
  |---|---|---|---|
  | symbol profiles | `min_produced 1` | `no_stale_symbols` | `db_*`, `writer_rejected` |
  | indicator-engine | `empty_allowed` | `no_stale_symbols` only | `no_universe`, `provider_rate_limited`, `db_*`, `config_unloaded` |
  | planners | `min_produced 1` | `no_candidates` | `llm_lane_error`, `db_connection_lost` |

  `failed[]` gains `empty_output` and `healthy[]` gains `output_produced`.
- The remediation catalogue is not regenerated here. Main's catalogue is already 7 lanes behind the contracts, and
  `tests/test_n8n_onboarding_standard_20261010.py` pins it at 119. Each contract records `catalogue_entry false`, so
  the diagnoser skips these lanes until a catalogue PR regenerates it with `build_remediation_catalogue.py --write`.
- Gates run on the branch: `check_lane_registry --fail-on-new --state-drift --no-exemptions` is clean, and
  `check_n8n_health_contracts` is clean.

## Operator step: indicator-engine cron line (needs a `cron` grant)

Order:

1. Merge and serve the PR.
2. Run `bash dry_run.sh`. It writes only under `~/.local/state/lane-repair/`, prints the one-line diff and the READ
   ONLY `--universe --dry-run`.
3. Get a `cron` grant whose reason names this packet and the PR sha.
4. Run `bash apply.sh`. It works from the live crontab with an exact one-line replacement and refuses unless exactly
   one line matches. It installs with `crontab -`, reads the crontab back byte-exact, runs the line once as cron
   would (flock + `--universe`), and prints the receipt's `produced_count`, `attempted_count` and `skipped_reasons`.
5. Proof is the receipt `data/runtime/indicator-engine_last.json` with `status ok`, plus fresh
   `indicator_confluence_cache` rows with `computed_at` after the run. Exit 0 is not evidence.
6. Rollback: `bash rollback.sh`, which is the exact reverse edit on the live crontab. Alternatively, restore the
   backup taken by `apply.sh`.

Candidate diff (`crontab.diff`):

```
-0 8 * * 1-5 cd $PROJ && $PY scripts/indicator_engine.py >> logs/indicator_engine.log 2>&1
+0 8 * * 1-5 cd $PROJ && flock -n /tmp/indicator_engine.lock $PY scripts/indicator_engine.py --universe >> logs/indicator_engine.log 2>&1  # lane indicator-engine: ...
```

After the apply, a registry-train PR should update `indicator-engine` `scheduler.command_text` to the new line. That
makes the allowlist lock real, which canary needs.

The other two lanes need no cron change. Their fix takes effect at the next served release:

- `build_symbol_profiles`: the 06:40 premarket pipeline step, the 06:45 watchlist line and the Sunday 19:00 line.
- The planner: 17:35 and 17:45.

Each first natural run writes its receipt with `summary.output`. Watch for the first `ok_at` that is not null.

## Interactions to resolve in the train

- PR #1761's retire packet (`lane-retire-wave1-20261015`) lists `indicator-engine` as RETIRE because of the demo
  line. With this repair the operator directive turns it on instead, so drop it from that packet before installing.
- Both PRs touch `config/lane_registry.json`. Because of the one-registry-PR-at-a-time rule (§23.11), this PR goes
  after #1761 in the registry train.
- The run-from-release cohort 1 packet prefixes the two `build_symbol_profiles` lines. The registry `command_text`
  recorded here is the pre-cohort line. Update it in the same follow-up PR if cohort 1 is applied first.

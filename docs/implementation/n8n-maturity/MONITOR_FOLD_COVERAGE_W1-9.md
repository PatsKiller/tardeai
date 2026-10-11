# Monitor fold coverage (W1-9): freshness contracts, input starvation and design notes for the rest

Status:      BUILT (gaps 1, 3, 6 below) + DESIGN NOTES (the rest). Detect and record only. Nothing has been retired.
             Rulings R1 and R11 DECIDED 2026-10-11 (operator: "R1 yes, R11 yes"); the fan-in severity (R11) and the
             parallel-run compare are built (branch `n8nmat/monitor-fold-rulings`); the retirement waits for the run.
as_of:       2026-10-11
Measured at: branch `n8nmat/monitor-coverage-gaps` on top of `26cf80f60`. Live state was read read-only on ms01-openclaw
             (a `--dry-run` of the detector, plus the monitors' own logs and receipts).
Input:       `~/n8n-maturity-verification/packets/consolidation-retire-wave1/MONITOR_FOLD_COVERAGE.md` (Agent LL, analysis)
             and `evidence/D_monitor_coverage_evidence.txt`. Operator approval 2026-10-11: build gaps 1–8, starting with
             job-coverage-monitor.

The health plane (`supervisor_breach_detector`, a systemd timer every 2 min, `--write`) can only replace a monitor once
it checks the same things. This change adds two checks to the detector:

1. **STALE_OUTPUT.** The registry's new top-level `freshness_contracts` list holds the store-level checks of three
   monitors. Each contract is a `db_max`, `file_mtime` or `json_key` signal with a `max_age_hours`. When the store
   is older than that age, the detector raises STALE_OUTPUT.
2. **INPUT_STARVATION.** The detector raises it from `scripts/lib/pipeline_liveness.py`, the checks that
   pipeline-liveness-report runs.

Both kinds are in `RECORD_ONLY_KINDS`. They are written to `supervisor_breaches.jsonl` and nothing else happens:

- They never reach L1/L2 self-heal or L3 escalation.
- They never reach the L4/L5 ladder, not even its shadow receipts.
- The fan-in reads them like any other ledger row. Until ruling R11 it filed both at its default, **P3**. Since
  R11 (2026-10-11, `n8n_incident_fanin.breach_severity`): STALE_OUTPUT takes the contract's own `severity` and
  INPUT_STARVATION is P2 for STARVED, P3 otherwise. See "Rulings R1 and R11" below.

Both are "slow checks". `SLOW_CHECK_EVERY_S` limits each to one run every 30 min, which matches how often today's
monitors run. The time of the last run is kept in `data/runtime/supervisor_slow_checks_last.json`, written only
under `--write`. `--slow-checks always|never` overrides the limit.

## What was built

### Gap 6 / D-6 — job-coverage-monitor (cron L389)

**Finding (it contradicts the packet):** `aegis_overnight.py` already **has** a registry row. It is lane
`aegis-overnight` (`scheduler.kind = systemd`, `aegis-overnight.timer`), and its `exec_start` runs
`scripts/aegis_overnight.py`. The packet's scan compared job names against `scheduler` fields only, so it missed
the row. **38 of 38** job-coverage jobs have an ACTIVE lane.

**Second finding:** job-coverage-monitor reports `aegis_overnight NOT_SCHEDULED` at its 08:30 run. The cause is its
own probe, `systemctl --user is-active aegis-overnight.timer`, which run from cron has no user bus. The timer is
active (`list-timers`: last run Sat 2026-10-10 20:00), and the brief table is fresh (`aegis_portfolio_briefs`
max `observed_at` 2026-10-10 20:05). This is one of the 14 fires per week, and it is false.

The 12 DB-timestamp checks, now registry contracts (`jcm.*`, `basis: lane_due`, `max_age_hours` = the monitor's
`cadence_h`, severity P2):

| Contract | Producer lane | Signal (table.column [where]) | Max age (h) | Source |
|---|---|---|---:|---|
| jcm.holdings_llm_refresh | holdings-llm-refresh | watchlist_items.holdings_llm_at [source='portfolio'] | 30 | job_coverage_monitor.py:47 |
| jcm.catalyst_momentum_engine | catalyst-momentum-engine-overnight | hermes_research_intelligence.created_at [research_type='momentum_catalyst'] | 30 | :49 |
| jcm.process_watchlist_agent_jobs | run-watchlist-agent-jobs-offpeak | watchlist_agent_jobs.created_at [status='completed'] | 3 | :60 |
| jcm.aegis_overnight | aegis-overnight | aegis_portfolio_briefs.observed_at | 30 | :62 |
| jcm.news_ingestion | news-ingestion | news_articles.created_at | 12 | :70 |
| jcm.rag_embeddings | rag-indexer | content_embeddings.created_at | 72 | :72 |
| jcm.transcript_discovery | aegis-transcript-discovery | youtube_transcripts.ingested_at | 240 | :74 |
| jcm.options_iv_snapshot | options-iv-snapshot | options_iv_history.captured_at | 30 | :86 |
| jcm.research_watchlist_discovery | research-watchlist-discovery | data_source_health.last_success_at [source_key='research_discovery'] | 80 | :126 |
| jcm.sync_social_to_intelligence | sync-social-to-intelligence | data_source_health.last_success_at [source_key='social'] | 80 | :130 |
| jcm.hermes_social_sentiment | hermes-social-sentiment | data_source_health.last_success_at [source_key='hermes_social'] | 80 | :134 |
| jcm.candidate_discovery_orchestrator | candidate-discovery-orchestrator | data_source_health.last_success_at [4 source_keys, as OR] | 80 | :138 |

How `lane_due` works:

- It reproduces job-coverage-monitor's rule: `allowed = max(cadence, hours since last due fire + min(cadence, 1 h))`.
  A market-hours job is therefore not judged overnight.
- On a systemd lane (aegis) the rule falls back to the max age alone. That is also what job-coverage does, because a
  timer job has no cron expression, so its idle time is 0.

**Parity, measured 2026-10-11 ~09:30 ET.**

- job-coverage-monitor's 08:30 run flagged two DB jobs STALE: `catalyst_momentum_engine` and
  `process_watchlist_agent_jobs`. The detector's dry run raises STALE_OUTPUT for exactly those two contracts and no
  others.
- Its other two fails are:
  - `hermes_analyst_signal_discovery`: a log check. The lane's registry NO_OUTPUT covers it.
  - `aegis_overnight NOT_SCHEDULED`: false, as described above.

**What the plane does not take over:** SCHEDULED? (is the script on a live crontab line). A removed line shows up as
NO_OUTPUT after 3× cadence, or as UNDECLARED / ORPHANED in `check_lane_registry --state-drift`. The module stays in
any case, because `cron_self_heal.py:70` imports its REGISTRY.

### Gap 1 — DB-output freshness for the two freshness monitors

`pfm.*` covers the 8 pipeline-freshness-monitor targets that no registry signal named. The other 2,
`hermes_canonical` and `rotation_summary`, were already covered. For these 8:

- `basis: trading_days` replaces the monitor's market-closure grace.
- `max_age_hours` is the monitor's threshold in days × 24.

| Contract | Signal | Max age | Source |
|---|---|---:|---|
| pfm.ticker_snapshot_daily | ticker_snapshot_daily.snapshot_date | 48 h | pipeline_freshness_monitor.py:31 |
| pfm.setup_advisory | candidate_setup_advisory.snapshot_date | 72 h | :32 |
| pfm.paper_trade_stats | file `data/paper_trading/paper_trade_statistics_latest.json` | 24 h | :36 |
| pfm.morning_synthesis | llm_intelligence_cache.generated_at [section='morning_synthesis'] | 48 h | :40 |
| pfm.strategy_backtest_results | strategy_backtest_results.created_at | 72 h | :45 |
| pfm.proposal_backtest_snapshots | proposal_backtest_snapshots.created_at | 72 h | :46 |
| pfm.trade_closed | trade_closed.close_date (journal table, read-only max) | 168 h | :47 |
| pfm.journal_trade_reviews | journal_trade_reviews.updated_at | 336 h | :48 |

`sfm.*` covers 8 of the 9 `fresh` table checks of system-freshness-monitor. Each keeps its severity.
`weekday_only` becomes `trading_days`.

| Contract | Signal | Max age | Severity | Source |
|---|---|---:|---|---|
| sfm.news_articles | news_articles.created_at | 24 h | P1 | system_freshness_monitor.py:52 |
| sfm.catalyst_events | catalyst_events.created_at | 24 h | P1 | :53 |
| sfm.sentiment_observations | sentiment_observations.created_at | 24 h | P2 | :55 |
| sfm.fused_signals | fused_signals.created_at (weekday_only) | 30 h | P1 | :56 |
| sfm.research_insights | research_insights.created_at | 26 h | P2 | :58 |
| sfm.hermes_research_intel | hermes_research_intelligence.created_at | 12 h | P2 | :60 |
| sfm.ticker_prices | ticker_prices.created_at (weekday_only) | 26 h | P1 | :61 |
| sfm.cio_decisions | cio_decisions.created_at (weekday_only) | 30 h | P2 | :62 |

How `trading_days` works: the window gets 24 h added for every non-trading day it reaches into, using the calendar in
`market_session.is_trading_day`. For example, 26 h on a Monday at 06:00 becomes 74 h. This is at least as lenient as
either monitor's weekend rule. The fold can report later than today's monitors (up to about half a Monday), never
earlier.

**Parity, measured 2026-10-11 ~09:30 ET.**

- pipeline-freshness-monitor 08:20: "10 fresh · 0 STALE"; contracts `pfm.*`: 0 stale.
- system-freshness-monitor 09:20: one issue, `topic_ingestion`, which no contract covers (below); contracts
  `sfm.*`: 0 stale.

Coverage after this change:

- pipeline-freshness-monitor: **10/10** targets have a registry signal.
- system-freshness-monitor: **9/13** (was 1/13). Still missing:
  - 2 `empty_vs_input` checks (design note 4)
  - `topic_monitor` (agg = min, ruling R2)
  - `drive-sync.log` needle (ruling R3)

### Gap 3 — input starvation (pipeline-liveness-report)

`INPUT_STARVATION` is one breach kind. `evidence.status` says which case it is:

| Status | Meaning |
|---|---|
| STARVED | work entered and nothing came out. Level 2. |
| NO_ELIGIBLE_INPUT | work arrived, but none of it was eligible to produce this output. Level 1. |
| UNKNOWN | the source could not be read. Level 1. |

There is one row per liveness lane × status × day. The breach's lane_id is `liveness:<lane>`.

The detector runs `pipeline_liveness.default_lanes()` against its own state root. It does this at most every 30 min,
because the probes fold about 210 MB of CIO JSONL (`cio_workflow_lineage.jsonl` 156 MB, `cio_runs.jsonl` 56 MB).

Measured dry run 2026-10-11: 0 breaches, which matches the report's own log (3 lanes `ok`).

### Validation

- `lane_registry.validate_freshness_contracts` is run by `validate_registry`, so `check_lane_registry` enforces it.
- Every contract needs:
  - a safe identifier (key)
  - a signal of an allowed kind
  - `max_age_hours > 0`
  - a valid `basis`
  - severity P1–P3
  - `source` (file:line)
  - `replaces`, naming the monitor(s)
- A `lane_id` must be a registry lane, and a contract on a lane that is not ACTIVE is not judged.
- Tests: `tests/test_monitor_fold_coverage_20261011.py` (gate `monitor_fold_coverage_20261011`). They pin every
  contract to its source line and to the monitor's own REGISTRY entry (table, column, where, threshold, severity),
  so the two cannot drift silently.

### Caveat (pre-existing, every `db_max` signal)

`lane_registry.observe_signal` reads a naive timestamp as UTC. A `timestamp without time zone` column that stores
Eastern time therefore reads 4–5 h older than it is, so the error can only make a store look stale, never fresh. The
columns checked on 2026-10-11 return aware values (for example, `holdings_llm_at`), but not all 28 were verified.

## Design notes (not built)

### 4. `empty_vs_input` (system-freshness-monitor: catalyst_events vs news_articles 24 h, fused_signals vs catalyst_events 30 h)

- **What it checks:** whether the output table got 0 rows in the window while the input table got more than 0. This
  is the catalyst bug: a green job that silently writes nothing.
- **Why a contract can't hold it:** a freshness contract cannot express it, because it compares two counts. The
  window is `created_at > now - window_h` on both tables.
- **Proposal:** a contract field `input_signal: {kind: db_count, table, column, window_hours}` plus
  `kind: "empty_vs_input"`. The detector raises STALE_OUTPUT with `note: "empty while input > 0"` when the output
  count is 0 and the input count is greater than 0.
- **Cost:** `count(*)` with a `created_at` predicate over 24–30 h. It needs an index on `created_at` in both pairs.
  Verify this with `EXPLAIN` before building; until then it must stay behind the 30-minute limit.
- **Weekday rule:** the fused_signals pair keeps `trading_days`.
- **Rulings:**
  - **R4:** is a new signal kind (`db_count`) acceptable in the registry schema?
  - **R5:** should a breach here also carry the auto-fix key (note 5)?

### 5. Auto-fix reruns (system-freshness-monitor `SAFE_REMEDIATION`: news_to_catalyst, hermes_news_bridge, research_insight_extractor)

- **What exists today:** the monitor reruns an idempotent, DB-only classifier through `subprocess`, at most 2 times a
  day. The breach ladder has no successor for this. L1 only restarts a lane's own `--user` unit, and it is not
  executed (`--heal` is off).
- **Proposal:**
  - The contract carries `remediation: {lane_id: <the classifier's registry lane>, max_per_day: 2}`.
  - The detector writes a `Recovery@v1` row with `executed=false` (shadow). The row names the lane run through the
    existing n8n run path (§23.3 / allowlist `r1_pending`), never a raw `subprocess`.
  - The remediation lane must be an allowlisted, dispatcher-eligible lane with its own dry run (§6) and health
    contract (§23.19).
- **Ruling R6:** the operator's go for a detector that triggers runs at all. Today it is detect-and-record only by
  design (Wave 1). Until then, system-freshness-monitor's `--auto-fix` is the only remediation, and it is one reason
  that monitor **cannot fold yet**.

### 6. Audit runner / daily audit stage (D-7) for D3/D4

- **Scope:** the 7 hourly or half-hourly audits (D3) and 6 daily audits (D4) are separate timers.
- **Proposal:** a host-side `audit_runner.py` with a checked-in plan (`config/audit_runner_plan.json`), where each
  audit has an argv, a timeout, a cadence and a receipt name. It would:
  - run due audits one after another, each under its own timeout
  - keep each audit's current receipt file name (`*_last_run.json`), because the fan-in reads `expected_services`,
    `data_source_health`, `served_copy_split`, `data_plausibility` and `gap_resolution` by those names
  - write `audit_runner_last.json` with per-audit `ok_at`
- **Scheduler:** it runs from one host timer, not n8n. §24.1 says P1 must not depend on n8n, and `expected_services`
  and `served_copy_split` are P1 inputs.
- **Registry:** one lane row with `json_key ok_at`. Each folded audit's row becomes RETIRED with
  `superseded_by: audit-runner`.
- **Rulings:**
  - **R7:** approve the runner. It is a new systemd unit, operator-only under §17.
  - **R8:** decide the order of the fold: D3 first (the fan-in inputs), D4 after.

### 7. `tradeai-maturity-feeds` has `output_signal: none`

- **Finding:**
  - The unit runs `scripts/hermes_maturity_gates.py --snapshot` (WorkingDirectory CURRENT).
  - `--snapshot` inserts one `hermes_maturity_history` row per day (`hermes_maturity_gates.py:270`, `snapshot_date
    DATE PRIMARY KEY`).
  - `systemctl --user show`: `Result=success`, last exit 2026-10-11 07:20 ET.
- **Proposal:**
  - Set `output_signal` to `{kind: db_max, table: hermes_maturity_history, column: snapshot_date}`, with `cadence 24`
    and `due 07:20`.
  - The column is a DATE, which reads as midnight UTC. The breach detector's 3× cadence rule absorbs that.
  - Alternatively, use `systemd_result` on `tradeai-maturity-feeds.service`, which is weaker because it proves an
    exit, not a row.
- **Why it is not done here:** the operator listed it as a design note. It is a one-line registry change once
  accepted (R9).

### 8. `finviz-view-contracts` is scheduled twice

- **Finding:**
  - The systemd timer `tradeai-finviz-view-contracts.timer` (Mon–Fri 06:05) is ACTIVE in the registry
    (`finviz-view-contracts`, `file_mtime data/runtime/finviz_view_contracts_last_run.json`).
  - The n8n workflow `finviz-view-contracts-shadow` is active (`active_workflows_snapshot.json:22`).
  - `config/n8n_run_allowlist.json:138` holds the same lane, with the note "no lock in unit, canary requires
    operator lock equivalence".
- **Risk:** both fire `scripts/check_finviz_view_contracts.py`. The unit takes no lock and the n8n path takes
  `safe_flock /tmp/tradeai_finviz_view_contracts.lock`, so the two can overlap. Both write the same `_last_run.json`
  receipt, which then proves nothing about which scheduler ran.
- **Proposal:** the shadow workflow must run with the script's `--dry-run` (or `dry_run_arg`) only, and must write
  its own receipt. Before any fold or cutover:
  - add the same lock to the unit (a unit edit, operator-only), or
  - deactivate the shadow workflow (an n8n change, operator-only).
- **Ruling R10:** which of the two schedulers stays.

### Not in this change (packet gaps 4 and 5)

- **A dead-man for the plane itself.** It would be host-side: `tradeai-heartbeat-watcher` is inactive, and n8n must
  not watch n8n. Until it exists, freshness-watchdog-heartbeat (D1-4) stays.
- **Fan-in closure.** 0 of 94 incidents have been recovered. That is Pilot A, which this change does not touch.

## Rulings needed

| # | Question | Status |
|---|---|---|
| R1 | Accept STALE_OUTPUT in place of job-coverage-monitor's PRODUCING? check (the 12 contracts) and NO_OUTPUT + registry drift in place of SCHEDULED?. This is D-6, retiring cron L389, which the operator approves under §17. | **DECIDED 2026-10-11** — operator: "R1 yes, R11 yes". Yes, after a one-trading-week parallel run with matching results (procedure below). The cron change itself still needs a cron grant. |
| R2 | `topic_monitor` oldest-item check (agg = min, 72 h): add `agg: min` to `db_max`, or drop it. It has been firing P2 continuously (1,518 h on 2026-10-11) and nobody acts on it. | open |
| R3 | `drive-sync.log` "sync done" needle check: accept `file_mtime` of the log (weaker), or move to the `drive-syncs-hourly` lane's own signal. | open |
| R4–R10 | As in design notes 4–8 above. | open |
| R11 | Fan-in severity for STALE_OUTPUT (the contract's `severity`) and INPUT_STARVATION (STARVED = P2?). | **DECIDED 2026-10-11** — operator: "R1 yes, R11 yes". STALE_OUTPUT = the contract's `severity`; INPUT_STARVATION STARVED = P2, NO_ELIGIBLE_INPUT and UNKNOWN = P3. Built (below). |

## What can fold after this merges and is released

- **job-coverage-monitor (D-6, cron L389): yes, once R1 is given.**
  - Its 12 DB checks now run in the plane, at its own thresholds.
  - Its 26 log checks were already covered by the lanes' NO_OUTPUT.
  - Its only aegis fire is a false NOT_SCHEDULED.
  - Before retiring it, run the detector with `--write` for at least one trading week and compare the ledger
    against the monitor's log (the parallel run, below).
- **pipeline-freshness-monitor (D1-1): the coverage gap is closed (10/10).** It still sends a `system_health`
  alert_event and Telegram; the plane now files STALE_OUTPUT at the contract's severity (R11). It folds after the
  same parallel run.
- **pipeline-liveness-report (D1-3): the coverage gap is closed.** R11 is decided; it folds after the parallel run.
  Its `--fail-on-finding` health-tick step can then go.
- **system-freshness-monitor (D1-2): not yet.** Three things still block it:
  - empty_vs_input (note 4)
  - auto-fix (note 5, R6)
  - topic_monitor and drive-sync (R2, R3)
- **freshness-watchdog-heartbeat (D1-4): not yet.** It is tied to D1-2 and to the plane's missing dead-man.
- **D2, D3, D4: unchanged.** They wait on D-7 (note 6), R9 and R10.

## Rulings R1 and R11 (decided 2026-10-11) — what was built and the parallel run

Operator, 2026-10-11: **"R1 yes, R11 yes"**. R1: the plane's STALE_OUTPUT (the 12 `jcm.*` contracts) plus NO_OUTPUT and
registry drift replace job-coverage-monitor (cron L389) after a one-trading-week parallel run with matching results.
R11: the fan-in severity of STALE_OUTPUT is the freshness contract's own `severity`; INPUT_STARVATION is P2 for STARVED.

### R11 — fan-in severity (built)

`scripts/n8n_incident_fanin.py` `breach_severity()`:

| Kind | Fan-in severity | Basis on the finding (`severity_basis`) |
|---|---|---|
| STALE_OUTPUT | the contract `severity` (`evidence.severity`, which the detector already records): P1 → P1, P2 → P2, P3 → P3, P0 → P1 | `contract:<sev>` |
| STALE_OUTPUT without a readable severity | P2 (the level both monitors alert at today; never muted to the P3 default) | `contract:missing->P2` |
| INPUT_STARVATION STARVED | P2 | `liveness:STARVED` |
| INPUT_STARVATION NO_ELIGIBLE_INPUT, UNKNOWN | P3 | `liveness:<status>` |
| every other kind | unchanged (`SEV`) | `kind:<KIND>` |

- **Why NO_ELIGIBLE_INPUT and UNKNOWN stay P3** (the ruling allowed arguing otherwise; this doc does not): neither
  shows a lane that is down. NO_ELIGIBLE_INPUT is work that could not produce this output. UNKNOWN is a source the
  probe could not read. pipeline-liveness-report treats them as findings, but not as outages.
- **One finding per contract, one per status.** Before, the fan-in kept one open finding per `lane:kind`. The items
  are now `<lane>/<contract>:STALE_OUTPUT` for a lane-tied contract (separate from the producer lane's own NO_OUTPUT),
  `freshness:<contract>:STALE_OUTPUT` for a lane-less one, and `liveness:<lane>/<status>:INPUT_STARVATION`. They still
  split on the last colon into (lane, kind), so `n8n_siem_bridge.lane_kind` reads them unchanged. Other kinds keep
  their items and idempotency keys.
- **Consequence to watch (finding):** once this is released, the `sfm.*` contracts (P1 for news_articles,
  catalyst_events, fused_signals, ticker_prices) reach the incident notifier at P1 while system-freshness-monitor,
  which is not folding, still sends its own alert. The same holds for `pfm.*` versus pipeline-freshness-monitor during
  the parallel run. The notifier dedupes per `source|item`, so the two are separate notifications. This is what R11
  says; it is listed so the operator is not surprised by it.
- Tests: `tests/test_n8n_incident_fanin_monitor_fold_20261011.py` (real detector rows from
  `detect_freshness` / `detect_input_starvation`; fixture ledgers under `tmp_path`).

### The parallel run (R1) — procedure

**Start:** the first trading day that runs, from its 00:00 ET, on a release that contains #1694 (W1-9) and this
change. The detector timer already runs with `--write`, so nothing new is scheduled. The live release on 2026-10-11 is
`464524b1b`, which has neither.

**Daily, for at least 5 trading days:** after job-coverage-monitor's 20:30 ET run (for example at 21:00 ET), run the
read-only compare once:

```bash
~/n8n-maturity-verification/packets/fold-job-coverage-monitor/run_parity.sh
# = $PY $CURRENT/scripts/monitor_fold_parity.py --root $CURRENT --out <packet>/parity
```

`scripts/monitor_fold_parity.py` reads the ledger rows of the last 24 h, the monitors' last ~24 h of runs (job
coverage: 2 runs; pipeline-freshness: 6; pipeline-liveness: 48), the release's registry and job_coverage_monitor's
REGISTRY. It writes nothing but `parity/parity-<UTC date>.json` (MonitorFoldParity@v1), and refuses an `--out` under
the release. Per monitor:

| Monitor | MATCH means |
|---|---|
| job-coverage-monitor | its STALE DB jobs == the `jcm.*` STALE_OUTPUT contracts (both ways); each STALE log job has a NO_OUTPUT row on the ACTIVE lane that runs it; no STALE job is uncovered. NOT_SCHEDULED is listed, not compared (the plane covers it with NO_OUTPUT after 3× cadence and `check_lane_registry --state-drift`; the aegis one is false). |
| pipeline-freshness-monitor | its STALE / MISSING targets == the `pfm.*` STALE_OUTPUT contracts (both ways); hermes_canonical and rotation_summary are listed, not compared (a lane output_signal covers them) |
| pipeline-liveness-report | its (lane, STARVED / NO-INPUT / UNKNOWN) set == the INPUT_STARVATION (lane, status) set (both ways) |

Exit 0 = all MATCH, 3 = a MISMATCH, 2 = an input could not be read. A MISMATCH is not automatically a defect:
`trading_days` can report up to about half a Monday later than the monitors, never earlier, and the log windows count
runs rather than clock time. Each MISMATCH needs a written explanation in `parity/parity-<date>.explained.txt` (what
differed and why) or a fix, before the run can conclude. Tests: `tests/test_monitor_fold_parity_20261011.py`.

**Conclusion:** `parity_gate.py --monitor <monitor>` passes when at least 5 distinct trading days (ET) are MATCH or
explained and no day is an unexplained MISMATCH or UNREADABLE. If the release lands before Monday 2026-10-12 08:30 ET,
the run covers Mon 10-12 to Fri 10-16 and can conclude after the Friday 21:00 ET compare. If it lands later, add one
trading day per day missed (a release during Monday makes the earliest conclusion Mon 10-19).

### Retirement, once the gate passes (prepared, not installed)

All three retirements are operator-only (§17) and wait for the gate. Nothing below has been run beyond its dry run.

1. **job-coverage-monitor (cron L389)** — packet `~/n8n-maturity-verification/packets/fold-job-coverage-monitor/`:
   - `build_candidate.py --crontab <(crontab -l) --date <install date>` matches L389 by its exact text (not by line
     number) and comments it with the convention marker `# RETIRED <date> lane=job-coverage-monitor
     reason=folded-into-health-plane-W1-9-R1 owner=operator review_by=<date+30d> <original>`. Nothing is deleted.
   - `install.sh` is a dry run by default. `--apply` needs the parity gate to pass, `CRON_GRANT_ID` set, and the live
     table byte-identical to the snapshot. It backs up the table, and restores it if the re-read differs.
   - `rollback.sh` (dry run by default) uncomments exactly the tagged line and refuses a double schedule.
   - Companion in the same window: a registry PR setting lane `job-coverage-monitor` to `state: RETIRED`. Otherwise
     the detector raises NO_OUTPUT on it. `scripts/job_coverage_monitor.py` stays, because `cron_self_heal.py:70`
     imports its REGISTRY.
2. **pipeline-freshness-monitor and pipeline-liveness-report** — these are health-tick steps
   (`config/health_tick_steps.json`, release config, §9.3), not cron lines. The vehicle is a repo PR plus a release.
   `build_health_tick_candidate.py` in the same packet matches each step by exact `step_id` and `command`, and moves
   it (it does not delete it) from `steps` to a top-level `retired_steps` list with a `retired` block (date, reason,
   replaced_by, owner, review_by). `health_tick.load_table` reads `steps` only. Each step folds when its own
   `parity_gate.py --monitor` passes (`--only <step_id>`). Rollback is the PR's revert.

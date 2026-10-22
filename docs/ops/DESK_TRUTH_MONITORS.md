# Desk truth monitors and the options quote refresh — n8n first

```
Status:      PROPOSED (branch feat/n8n-desk-truth-20261022; lanes not yet in the registry — see §5)
as_of:       2026-10-22T11:40:00-04:00
Owner:       platform (monitors), options desk (quote refresh), execution (holdings writer)
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0
Runbook-Id:  desk-truth-monitors
Tests:       tests/test_n8n_desk_truth_20261022.py (gate n8n_desk_truth_20261022),
             tests/test_registry_runtime_truth_20261018.py (gate registry_runtime_truth_20261018)
```

**Current release gate (2026-10-22 integration review): HOLD.** The repository-wide data-source authority check
reports `scripts/desk_truth_monitor.py` as an `UNAPPROVED_READER` of `positions_current`. This monitor's direct
store access is not covered by the Watch-only reader grant described below. No reader grant or measured-reader
exception has been added. Do not schedule or activate this monitor until it uses an already approved domain reader,
or an operator approves a compliant reader/projection design and its scope is recorded. The existing full-repository
authority gate must pass before release.

**Why.** Operator 2026-10-22: *"fix all of these n8n first for scheduling and monitoring"*. On that day:

- the scheduled holdings writer (`scripts/schwab_position_sync.py --apply`, crontab line 501) had been commented out
  since 2026-10-15 (`# PAUSED 2026-10-15 schwab-app-deactivated (incident SPCX, grant 0f9de907)`), the registry still
  said ACTIVE, and holdings.json drifted (NAVN missing, SCHD/SCHG 2,000 short each, cash +$153,920 against
  positions_current) with nothing saying so;
- the options desk snapshot (`data/portfolios/state/options_proposals.json`) kept its 09:30 quotes until noon,
  because the full build runs `*/10 12-15` to stay out of the morning GPU window;
- options CIO reviews of the SPCX protective-put ideas failed 3 times each (`POLICY_NOT_ALLOWED` →
  `REVIEW_FAILURE_CAP`).

"n8n first" here means: schedule and watch through n8n dispatcher lanes (relay → gateway `coordination/run` →
host executor, allowlist, registry row, health contract), shadow stage first. The host keeps every credential and
every authority. No crontab line is added or re-enabled by these PRs. The holdings writer's own cron line is
resumed separately by the operator's cron resume packet, because broker read-only lanes on n8n wait for
AGENTS.md 18.0.0 (§5).

## 1. The three monitors — `scripts/desk_truth_monitor.py`

| check | lane | reads (read-only) | finding codes | intent route (DIGEST → P2) |
|---|---|---|---|---|
| `holdings-drift` | `holdings-drift-monitor` | holdings.json via `lib.portfolio_positions.load_store`; `positions_current` | `MISSING_IN_HOLDINGS`, `PHANTOM_IN_HOLDINGS`, `QTY_DRIFT`, `CASH_DRIFT`, `HOLDINGS_STALE`, `POSITIONS_CURRENT_STALE` | `positions/holdings_drift_finding` |
| `options-desk-staleness` | `options-desk-staleness-monitor` | options_proposals.json | `DESK_STALE` | `data/options_desk_stale` |
| `held-exit-coverage` | `held-exit-coverage-monitor` | `positions_current`; `stop_lifecycle` (the snapshot `scripts/stop_lifecycle_monitor.py` writes) | `UNCOVERED`, `SNAPSHOT_STALE` | `stops/held_exit_coverage_gap` |

```bash
python3 scripts/desk_truth_monitor.py --check holdings-drift            # dry run: print, write nothing
python3 scripts/desk_truth_monitor.py --check held-exit-coverage --json
python3 scripts/desk_truth_monitor.py --check options-desk-staleness --apply   # receipt + alert state + ≤1 intent
```

- **Thresholds** are in `config/desk_truth_monitors.json` (tolerances, freshness bounds, session window, paper
  accounts, value floor, exemptions). A change there is a reviewed config change.
- **Alerting.** `--apply` queues one host comms intent only when the check's alertable finding set *gained* a key
  since the last apply (state `data/runtime/<lane>_alert_state.json`), on top of the store's own dedupe. The
  comms-intent consumer and `scripts/incident_notifier.py` deliver it. The monitor never sends.
- **Needs action.** `GET /api/v2/needs-action` source `desk_truth` reads the three receipts: an alerted finding is
  P2; a failed or stale (26 h) receipt is P2; a finding the check did not alert on is folded into one P3; no receipt
  yet (shadow) is one P3.
- **Stop coverage honesty.** A `stop_lifecycle` snapshot older than 2 h in session makes the verdict `NOT_MEASURED`:
  uncovered positions are listed but not alerted. Paper-account stop rows (`tradeai_automated`, `alpaca_paper`) are
  counted and tagged `PAPER`; paper positions are not read, because that would be a broker call. The lane id avoids
  the dispatcher's forbidden word `stop`, which exists to keep stop *writers* off n8n. This lane writes no stop and
  its import closure reaches no broker, order or stop-write module (test
  `test_monitor_closure_reaches_no_db_adapter_sender_broker_or_order`).
- **Database.** The monitor opens its own psycopg2 session with `set_session(readonly=True)` and does not use
  `db_adapter`, whose closure reaches the broker transport. `positions_current` and `stop_lifecycle` have no
  data-broker projection (`config/data_source_authority.json` `positions_store` `"projection": null`). These are two
  new direct store reads by a lane script, counted here as AGENTS.md §24.3 requires.

First read-only runs against the host, 2026-10-22 ~11:27 ET (dry run):

- `holdings-drift`: 0 findings. holdings.json was confirmed by the broker at 11:10 ET and positions_current
  0.04 h old, so the drift described above had been repaired by a sync earlier that day.
- `options-desk-staleness`: `DESK_STALE`, 116.5 min since `generated_at` 09:30 ET.
- `held-exit-coverage`: 27 held, 4 covered, 23 without a WORKING stop. With the $1,000 value floor now in the
  config, 14 of them are fractional remainders below the floor. SCHD 6,000, SCHG 4,000, SPCX 600 + 200, XAR 100 and
  AMANX remain.

## 2. Registry truth — `scripts/check_registry_runtime_truth.py` (existing lane `registry-runtime-truth`)

Rather than build a second checker, the existing measure-only lane gained two rules:

- `ACTIVE_CRON_LINE_ABSENT`: a kind-cron row declared ACTIVE, with no active crontab line running its
  `scheduler.match`. This is the shape that hid the paused holdings writer.
- `DECLARED_OFF_CRON_LINE_ACTIVE`: a kind-cron row declared NEVER_SCHEDULED, RETIRED or PAUSED, with an active
  crontab line running it.

The existing `ACTIVE_N8N_WORKFLOW_INACTIVE` and `CUTOVER_CRON_LINE_ACTIVE` rules already cover the n8n side. On
2026-10-22 the host dry run reported 17 `ACTIVE_CRON_LINE_ABSENT` and 2 `DECLARED_OFF_CRON_LINE_ACTIVE`. Each one is a
registry row to correct by its owner; this PR corrects only `schwab-position-sync`.

## 3. Options desk quote refresh — `scripts/options_desk_quote_refresh.py`

This is a quote-only re-quote of the cards already on the desk. It never rebuilds, re-ranks or re-prices them, and
never queues an ensemble job, calls an LLM or uses the GPU.

- For each `(symbol, expiration)` group of cards it makes one read-only, expiration-pinned option-chain read
  (`schwab_transport.get_option_chain`, all strikes of that expiration, one side when the group has one).
- It writes a `live_quote` block per card (bid / ask / mid / spread / quote_time / OCC symbol / underlying spot /
  `market_session`; a spread gets one entry per leg). At the top level it writes `quote_refresh {at, market_session,
  requests, request_budget, cards_requoted, cards_skipped}`.
- **Unchanged:** the card's economics and `generated_at` belong to the build that reviewed them.
- **Request budget.** On 2026-10-22 the desk held 5 cards in 4 `(symbol, expiration)` groups, so 4 reads per run. At
  10 runs per morning (09:35–11:50 every 15 min) that is about 40 reads. The cadence is one expression,
  `5,20,35,50 9-11 * * 1-5` ET. Its 09:05 and 09:20 fires, and any fire outside NYSE regular hours (holiday, DST),
  read nothing (`outside_session`). Host dry run, 2026-10-22: `cards 5  groups 4  requests planned 4/25`. The per-run cap is `--max-requests` (default
  25, ceiling 60), and groups over the cap keep their old quotes (`request_budget_exhausted`). For comparison, the
  full build makes on the order of hundreds of chain reads per tick.
- **GPU-window rationale.** The full build moved to noon on 2026-07-17 because its ensemble queue fed the local
  GPU during the 09:30–11:00 momentum-scalp window (crontab comment; `scripts/llm_priority_guard.sh` defers tier-3
  LLM work 06:00–11:59 ET). A quote-only refresh touches neither, so it may run in that window.
- **Access mode.** It runs only while `config/schwab_access_mode.yaml` resolves to exactly `read_only`; `normal` and
  `forbidden` refuse the run. It never sets `TRADEAI_SCHWAB_ACCESS_MODE`, which would override an operator
  `forbidden`.
- **Writes.** The write is atomic, and only if the file did not change since it was read, so a concurrent full
  build wins (`snapshot_changed_during_refresh`).
- **Dry run** (the default) is offline. It plans the reads and never imports the broker transport.

## 4. Options CIO review routing

`scripts/lib/options_cio_review.py` called the router with task `cio_synthesis`, so it ran as Steph's process
`watchlist_steph_flash_narrative`. Thesis text containing "reconcile" escalates the policy to FAST_THINK
(`agent_flash_governance.should_escalate_fast_think`). That process's `allowed_lanes` exclude `fast_think`, so
`llm_consumption.should_call` refused it with `POLICY_NOT_ALLOWED`. The store shows 28 ideas refused between
2026-10-05 and 2026-10-22 (26 SPCX, 2 SCHG).

Under AGENTS.md §9.2 every caller names itself, so the review now has its own task (`options_thesis_review`) and its
own process `options_thesis_cio_review`:

- **Lanes and policies:** `deepseek-flash`, `fast`, `fast_think`, `grok`, `chatgpt`; FAST/FAST_THINK, no PRO.
- **Caps:** 40 calls and $0.40 a day.
- **Mode and output:** `automated`; `max_output_tokens` 3200.
- **Routing:** a routing-policy row and bridge maps (`advisory_desk` / `options_thesis_cio_review`), plus a
  `sync_cio_process_caps.py` entry (now with `--dry-run`).

Steph's shared row is unchanged. After merge, the operator runs:

```bash
python3 scripts/sync_cio_process_caps.py --dry-run && python3 scripts/sync_cio_process_caps.py
systemctl --user restart cio-governed-bridge.service   # §9.2 bridge restart
```

**Reopening the two capped SPCX ideas.** `options_thesis_reopen.py` used to skip any idea that was not archived. It
gains `--review-cap`, which appends one `OPTIONS_THESIS_REOPENED` (`reopened_from: review_failure_cap`) to an idea at
`max_review_failures`; the lifecycle counts failures only after the last reopen. Dry run first:

```bash
python3 scripts/options_thesis_reopen.py --guid 19e3db3f-ea61-59a7-9091-a369ee6e58d9 --review-cap --reason "routing fixed: options_thesis_cio_review allows FAST_THINK (2026-10-22)"
python3 scripts/options_thesis_reopen.py --guid f327c7ac-a016-59d6-9bc0-d6740e00a103 --review-cap --reason "routing fixed: options_thesis_cio_review allows FAST_THINK (2026-10-22)"
# then the same two lines with --apply, only after the fix is served
```

## 5. What schedules what (n8n first), and what is still the operator's

| lane | stage in this branch | why |
|---|---|---|
| `holdings-drift-monitor`, `options-desk-staleness-monitor`, `held-exit-coverage-monitor` | registry row + allowlist + DRAFT contract in the follow-up registry PR | a new lane's contract must be REVIEWED by its owner (`check_n8n_health_contracts` fails a DRAFT that is not grandfathered) |
| `options-desk-quote-refresh` | staged inert (scheduler kind none) in the registry PR, **gated on AGENTS.md 18.0.0 ACTIVE** | its reach is the Schwab transport: the broker-module reach gates refuse it (§23.14 / §23.20 (a)) |
| `schwab-position-sync` | registry row PAUSED (truth) + `f09_staged` record, **gated on AGENTS.md 18.0.0 ACTIVE** | `schwab` and `schwab_position_sync.py` are forbidden tokens, and broker-read lanes are on the §23 n8n never-list |

**Broker READ-ONLY lanes wait for AGENTS.md 18.0.0.** The operator directed an amendment on 2026-10-22 (coordinator
context), and it is not yet ratified. It would let n8n schedule broker read-only lanes under read_only mode, the
trading lock LOCKED, and a read-only allowlist. Until 18.0.0 is ACTIVE:

- The holdings writer stays a host cron line. The operator's cron resume packet re-enables line 501 and flips the
  registry row back to ACTIVE in the same change (§9.3). This PR does neither.
- Both staged lanes stay inert.
- Nothing here weakens the forbidden-token check: `pipeline_manifest.FORBIDDEN_COMMAND_TOKENS` and
  `lane_dispatch.EXTRA_FORBIDDEN_WORDS` are unchanged. `test_holdings_writer_n8n_lane_is_gated_on_18_0_0_and_still_refused`
  pins that a dispatch block on the row is still refused.

After 18.0.0, the n8n lane follows §23.21 / §23.12:

1. Shadow and canary run with the resumed cron line live, under the shared lock `/tmp/schwab_pos_sync.lock`.
2. Then a cutover under a cron grant comments the line.

The monitors call no broker and are n8n lanes now.

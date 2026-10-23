# n8n promotion readiness — 2026-10-22

**Status: PROPOSAL. Nothing in this file has been applied.** Every promotion below is an operator decision (AGENTS.md
§17; a reviewed registry PR per §23.11; one `cron` grant per cutover wave naming every lane, §23.12). This report is
read-only evidence.

**Source.** `GET /api/v2/ops/controls/state` → `n8n`, computed by `scripts/lib/ops_controls_n8n_outcomes.py` (this PR)
on the host at **2026-10-23 02:13Z (22:13 ET, 2026-10-22)**. It read:

- the n8n coordination ledger `~/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite`
  (sqlite `mode=ro` + `PRAGMA query_only`; `run_outcomes`, `runs`, `dead_letters`, `breakers`);
- `config/lane_registry.json`, `config/n8n_run_allowlist.json`, `config/n8n_health_contracts.json`,
  `config/lane_cutover_policy.json`, `config/n8n_effect_keys.json`,
  `docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv` at this branch's head;
- the relay live list `~/.config/tradeai/n8n-live-lanes.env` (only `TRADEAI_N8N_RELAY_LIVE_LANES`) and `crontab -l`.

**Criteria — the documented ones only.** No threshold here is new.

| Step | Conditions checked | Source |
|---|---|---|
| shadow → canary | REVIEWED health contract with no UNKNOWN field; run-allowlist entry; the latest n8n `dry_run` fire is RUN_DONE, so any earlier failure has a clean fire after it (no number of shadow days); for a cron row, the cron line's `flock -n` lock equals the allowlist lock; the cutover factory can derive `live_arg` from the cron line; a sender's cron line is wrapped with `effect_claim_cron.sh` | `N8N_ONBOARDING_STANDARD.md` steps 3, 5, 8, 9, rule 5, §2 rule 4; AGENTS.md §23.12, §23.21 (2), §23.25; `n8n_cutover_wave.plan_lane` |
| canary → cutover | (1) defect fixed: the latest live run is not FAILED or TIMEOUT; (2) the latest `dry_run` fire is RUN_DONE; (3) the lane's regression tests pass under `TRADE_AI_CI=1`, which is **owed in the cutover PR** and cannot be measured here; (4) at least one live n8n RUN_DONE whose `output_signal` advanced, on the relay live list, with the allowlist lock equal to the cron line's lock and the cron line still present. RUN_SKIPPED_LOCK does not count. No soak. | AGENTS.md §23.21 (16.0.0, ACTIVE), §23.12 |
| BLOCKED | registry not ACTIVE; operator hold (`lane_cutover_policy.json`); held lane (`cutover_lane_facts.HELD`); F07 or registry_systemd; never-list (`lane_dispatch.dispatch_eligible`); allowlist `blocked_reasons`; no allowlist entry; health contract missing, not REVIEWED, or with UNKNOWN fields | AGENTS.md §23.14, §23.25; onboarding rule 5 |

**Risk tier.** The cutover factory's own classifier (`cutover_lane_facts.tier_of`): 1 read/overwrite < 2 append <
3 send < 4 llm < 5 watchdog < 6 broker. Append, send and llm lanes need their effect key armed at cutover, with the
fenced single-owner switch (§23.23 (4)).

## Answer to "When is everything going live?"

There are 120 registry rows with an n8n scheduler or a dispatch block:

| | Lanes | What it means |
|---|---|---|
| Live & healthy | **62** | n8n's fires are real runs today, and the last one succeeded. This includes 13 lanes fully cut over and canary lanes where the cron line is still present as a fallback. |
| Live & failing | **1** | `registry-runtime-truth`: RUN_FAILED `output_unverifiable` on both live runs (2026-10-21 and 2026-10-22, 11:20Z). |
| Rehearsing (dry run) | **47** | 46 shadow lanes plus `trade-ai-scalp-live`, which is at canary but not on the live list. The cron line still does the real work. |
| Ready to promote | **32** | 25 canary → cutover and 7 shadow → canary. |
| Never ran | **4** | `pattern-extractor` and `disk-hygiene` are on the live list at canary with no run in the ledger. `macro-calendar-refresh` and `validate-expense-ratios` are at shadow with no dry run. |
| Off | 8 | Retired, NEVER_SCHEDULED or `mode: off` (including the four `release-train-request-*` rows). |

**Readiness by stage:**

| Stage | Ready | Not ready | Blocked | Done |
|---|---|---|---|---|
| canary | 25 ready for cutover | 24 | 4 | — |
| shadow | 7 ready for canary | 18 | 22 | — |
| cutover | — | — | — | 13 |

The **22 blocked shadow lanes** are blocked for these reasons:

- 19 have a DRAFT health contract. Each needs its owner's REVIEW, which is an owner or operator action. One of them,
  `audit-enrichment-coverage`, is also an unwrapped sender.
- `aegis-nightly-ingestion` is held as the reference workflow's inert lane.
- `source-litmus-vs-yahoo` is on registry_systemd and stays on the host.
- `hermes-learning-outcome-feedback-agent` is NEVER_SCHEDULED.

So "everything live" depends on three kinds of work:

1. Approving the batches below.
2. Contract reviews for the 19 DRAFT lanes.
3. Small fixes:
   - `flock` edits on 5 cron lines;
   - the factory's argv parser: 6 lanes with the effect-claim wrapper, and 6 lanes with other argv mismatches;
   - 4 canary rows whose cron line is commented while the registry still says canary;
   - one forced `dry_run` fire for each canary lane in item 6 of the unblocking list below.

None of it is a waiting period.

## Failing lanes now

| Lane | Health | Evidence |
|---|---|---|
| `registry-runtime-truth` | FAILING | RUN_FAILED `output_unverifiable` 2026-10-21 11:20Z and 2026-10-22 11:20Z. It has had no successful live run yet. It is on the live list at canary. |
| `watchlist-enrichment-sweep` | OK (last run succeeded) | RUN_TIMEOUT `timeout_exit_124` at 2026-10-22 13:15Z, and RUN_TIMEOUT `executor_lost` at 15:13Z. The second is in the window of today's portfolio-server OOM incident (#1963); the server-side cause is not established here. The lane counts as READY_FOR_CUTOVER by the letter of §23.21, but it is held below. |
| `n8n-incident-fanin` | OK | RUN_FAILED `exit_1` 2026-10-17 16:00Z and 2026-10-22 02:10Z; every run since has been clean (2015 live runs in 7 days). |
| `identity-sweep-stage0` | OK | RUN_FAILED `exit_1` 2026-10-21 04:30Z, clean since. The lane is cut over. |
| `daily-incubator-refresh`, `instrument-belief-writer` | OK | One RUN_FAILED `exit_1` each, on 2026-10-16; clean since. |

## Proposed promotion batch for 2026-10-23 — operator approval list

Reply with the letters you approve, for example "approve A, B, C". Each approved letter becomes its own registry PR. A
cron-retiring letter also needs one `cron` grant whose reason names every lane in it. Nothing moves without that.
Before each step: the dry run quoted, the lane regression tests under `TRADE_AI_CI=1` quoted (§23.21 (3)), and a forced
or natural fire proven by a ledger row dated after the trigger (§8.1).

The letters are ordered from lowest to highest risk.

**A. Registry stage label only. Tier 1, no runtime change. 4 lanes:** `active-trader-motion-watchdog`,
`disk-usage-monitor`, `n8n-data-plausibility-audit`, `n8n-gap-resolution-audit`.

- **Today:** each is already a `kind: n8n` / `expression: dispatcher` row (its cron line is gone) at `stage: canary`,
  live, clean over 7 days.
- **Change:** `scheduler.stage` canary → cutover, plus the cron-inventory change-log row (step 13). There is no cron
  line to retire, so no `cron` grant is needed.
- **Rollback:** revert the PR.

**B. Retire the cron line. Tier 1, read/overwrite. 2 lanes:** `job-coverage-monitor` (next run Fri 08:30 ET) and
`classify-instruments` (weekly, Sat 06:30 ET).

- **Change:** `_cutover.py --lane <id>` under one `cron` grant naming both lanes. The line is commented as
  `# RETIRED 2026-10-23 n8n-cutover …`, the row flips to the §23.11 dispatcher shape, and a `CutoverReceipt@v1` is
  written per lane.
- **Rollback:** `_cutover.py rollback --lane`.

**C. Retire the cron line. Tier 2, append, 0 failures in 7 days. 13 lanes:**

- `agent-outcome-linker`
- `aegis-social-sentiment`
- `aegis-transcript-discovery`
- `commitment-outcome-sweep`
- `feedback-loop-processor`
- `finviz-proactive-research`
- `finviz-screener-runner`
- `hermes-social-sentiment`
- `journal-tilt-morning-hook`
- `proposal-backtest-engine`
- `sec-data-ingest`
- `update-agent-performance`
- `weekly-incubator-builder` (Sundays)

**Change:** as B, with each lane's effect key armed and its owner switched by `effect_claim.py set-owner`, the fenced
single-owner switch (§23.23 (4)). One `cron` grant names all 13 lanes. If you want a smaller first wave, approve
**C1** (the first 7 lanes) and **C2** (the other 6) separately.

**D. Same as C, but each lane had an earlier failure. 2 lanes:** `daily-incubator-refresh` and
`instrument-belief-writer`. Each had one `exit_1` on 2026-10-16 and has been clean since.

- **§23.21 (1):** this condition wants the defect *fixed*, not just followed by successes. Approve D only if you accept
  those failures as transient. Otherwise the agent first names the fixing PR.

**E. Shadow → canary. Tier 1. 3 lanes:** `watch-goods-consistency` (cron row), `advisory-maturity-evidence`,
`cio-portfolio-thesis`. The last two are n8n-native W5 rows whose contracts the operator REVIEWED on 2026-10-21.

- **Change:** a registry PR sets `dispatch.mode live` and the allowlist `live_arg`. Then add each lane to the live list
  from Ops → Controls (passkey).
- **Lock proof:** the cron row's lock already matches. The n8n-native rows have no cron twin, so their first live fire
  is the proof.

**F. Shadow → canary. Tier 2, append or learn. 2 lanes:** `indicator-engine` and
`hermes-discovery-yield-on-learning`. Same as E, with the effect key staged at canary.

**Not proposed for 2026-10-23** (listed so you can see why):

- **Ready, held back:**
  - `watchlist-enrichment-sweep`: two timeouts today.
  - `heartbeat-watch`: tier 2, append. It is the platform's own stale-output watcher, so move it in a later wave
    after A–C show clean natural fires.
  - `data-gap-resolver-at-0-10-16` and `hermes-entity-spike-discovery`: tier 4, llm. Next wave.
  - `momentum-cache-reconcile` and `momentum-lifecycle-monitor`: the momentum catalyst work is gated by the operator's
    Gate decisions.
- **Never proposed by an agent:**
  - `trade-ai-scalp-live`: tier 6, broker. Its live proof only comes from n8n's own schedule (§23.21), and adding it
    to the live list is your call.

## Unblocking work, not promotions (for the record)

1. **Owner REVIEW of 19 DRAFT health contracts:**
   - `agent-calibration-engine`
   - `agent-number-grounding-slo`
   - `audit-enrichment-coverage`
   - `catalyst-momentum-engine-overnight`
   - `classifier-health-check`
   - `crawl-v3-dashboard`
   - `data-gap-resolver-pre`
   - `data-gap-resolver-weekly`
   - `enterprise-backtester`
   - `fee-efficiency-analyzer`
   - `finviz-health-check`
   - `hermes-pipeline-health`
   - `hermes-topic-monitor-bridge`
   - `maturity-remeasure`
   - `sector-rs-daily`
   - `setup-quality-prior`
   - `signal-fusion-active`
   - `signal-fusion-full`
   - `write-state-freshness-history`
2. **The cron line needs a `flock -n` lock before canary** (a crontab edit under a `cron` grant). These lines use
   `safe_flock.sh` or no lock:
   - `goal-gate-bridge`
   - `trade-backtest-engine`
   - `hermes-scope-governor`
   - `hermes-score-event-feeder`
   - `resolve-due-checkpoints`
3. **The cutover factory cannot read its own effect-claim wrapper.** `n8n_cutover_wave.parse_lane_argv` reports
   `unmapped_wrapper:env…/scripts/effect_claim_cron.sh` for cron lines that already carry the wrapper that §23.25
   *requires* for a sender. That holds these lanes:
   - `social-ingest-all`
   - `trade-thesis-review-engine`
   - `update-lockup-earnings-dates`
   - `hermes-research-agenda-at-45-7`
   - `hermes-research-worker-pool`
   - `news-to-catalyst`

   It also makes `n8n_cutover_wave.py plan` print SKIP for every current canary lane that carries the wrapper. This is
   a factory defect; the fix is its own PR.
4. **Other factory argv findings:**
   - `aegis-evening-packet` (`env:PYTHONPATH`);
   - `finviz-enrichment-scalp-hot` and `scalp-hot-list` (`env:SCALP_HOT_TIER`);
   - `finviz-market-movers`, `investment-costs` and `validate-expense-ratios`: `script_not_on_cron_line`, meaning the
     allowlist command does not match the cron line.
5. **Canary rows whose cron line is commented while the registry says canary.** §23.21 (4) needs the line present, so
   reconcile each row (to cutover, or restore the line):
   - `hermes-watchlist-scorer`
   - `materialize-watchlist-strategy-cards`
   - `sync-social-to-intelligence`
   - `hermes-discovery-scorecard`
6. **Canary lanes with no n8n `dry_run` RUN_DONE in the ledger** (§23.21 (2)). One forced `dry_run` fire through
   `coordination/run` closes the gap:
   - `agent-outcome-scorer`
   - `build-symbol-profiles-at-0-19`
   - `etf-analyst-enrich`
   - `etf-performance-enrich`
   - `incubator-rolloff-engine`
   - `opening-intelligence-render`
   - `n8n-comms-intent-consumer`
   - `tmp-hygiene`
   - the five `hermes-learning-*` fabric steps. Four of them also have a last live RunReceipt that does not record
     whether `output_signal` advanced.

   `hermes-discovery-scorecard` (item 5) has no dry run either.
7. **Canary lanes whose only live runs are RUN_SKIPPED_LOCK.** The cron line wins the lock every slot:
   - `finviz-enrichment`
   - `finviz-sector-research`
   - `pr-hygiene-audit`

   A live proof needs one n8n-won slot (§23.21 (4), "where the live run comes from").

## Every shadow and canary lane

The "Evidence or what is missing" column is the server's own text. Timestamps are UTC.

### Canary lanes (target: cutover, AGENTS.md §23.21) — 53 lanes

| Lane | Tier | Live list | 7 d runs (live · dry) | Last run | Fails 24 h / 7 d | Verdict | Evidence or what is missing |
|---|---|---|---|---|---|---|---|
| `active-trader-motion-watchdog` | 1 read/overwrite | yes | 724 · 13 | SUCCESS live 2026-10-23 02:10Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-20 13:55Z; live RUN_DONE 2026-10-23 02:10Z; output_signal advanced on that run |
| `classify-instruments` | 1 read/overwrite | yes | 1 · 0 | SUCCESS live 2026-10-17 10:34Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-11 14:24Z; live RUN_DONE 2026-10-17 10:34Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `disk-usage-monitor` | 1 read/overwrite | yes | 242 · 5 | SUCCESS live 2026-10-23 02:00Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-20 13:45Z; live RUN_DONE 2026-10-23 02:00Z; output_signal advanced on that run |
| `job-coverage-monitor` | 1 read/overwrite | yes | 3 · 11 | SUCCESS live 2026-10-23 00:30Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-21 12:30Z; live RUN_DONE 2026-10-23 00:30Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `n8n-data-plausibility-audit` | 1 read/overwrite | yes | 1 · 1 | SUCCESS live 2026-10-22 10:20Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-21 10:20Z; live RUN_DONE 2026-10-22 10:20Z; output_signal advanced on that run |
| `n8n-gap-resolution-audit` | 1 read/overwrite | yes | 70 · 55 | SUCCESS live 2026-10-23 02:07Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-21 15:37Z; live RUN_DONE 2026-10-23 02:07Z; output_signal advanced on that run |
| `aegis-social-sentiment` | 2 append | yes | 10 · 0 | SUCCESS live 2026-10-22 19:00Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-15 19:00Z; live RUN_DONE 2026-10-22 19:00Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `aegis-transcript-discovery` | 2 append | yes | 5 · 0 | SUCCESS live 2026-10-22 13:00Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-15 13:00Z; live RUN_DONE 2026-10-22 13:00Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `agent-outcome-linker` | 2 append | yes | 5 · 0 | SUCCESS live 2026-10-22 15:00Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-15 15:00Z; live RUN_DONE 2026-10-22 15:00Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `commitment-outcome-sweep` | 2 append | yes | 7 · 0 | SUCCESS live 2026-10-22 22:20Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-15 22:20Z; live RUN_DONE 2026-10-22 22:20Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `daily-incubator-refresh` | 2 append | yes | 5 · 0 | SKIPPED live 2026-10-22 12:15Z (flock_held) | 0 / 1 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-15 12:15Z; live RUN_DONE 2026-10-21 12:23Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `feedback-loop-processor` | 2 append | yes | 5 · 0 | SUCCESS live 2026-10-23 00:30Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-16 00:30Z; live RUN_DONE 2026-10-23 00:30Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `finviz-proactive-research` | 2 append | yes | 20 · 0 | SUCCESS live 2026-10-22 19:30Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-15 19:30Z; live RUN_DONE 2026-10-22 19:30Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `finviz-screener-runner` | 2 append | yes | 5 · 0 | SUCCESS live 2026-10-22 14:19Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-15 14:00Z; live RUN_DONE 2026-10-22 14:19Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `heartbeat-watch` | 2 append | yes | 2016 · 0 | SUCCESS live 2026-10-23 02:10Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-11 22:20Z; live RUN_DONE 2026-10-23 02:10Z; output_signal advanced on that run |
| `hermes-social-sentiment` | 2 append | yes | 10 · 0 | SUCCESS live 2026-10-22 19:17Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-15 19:15Z; live RUN_DONE 2026-10-22 19:17Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `instrument-belief-writer` | 2 append | yes | 7 · 0 | SUCCESS live 2026-10-22 22:50Z | 0 / 1 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-15 22:50Z; live RUN_DONE 2026-10-22 22:50Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `journal-tilt-morning-hook` | 2 append | yes | 5 · 0 | SUCCESS live 2026-10-22 16:00Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-15 16:00Z; live RUN_DONE 2026-10-22 16:00Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `proposal-backtest-engine` | 2 append | yes | 15 · 0 | SUCCESS live 2026-10-22 18:05Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-15 18:05Z; live RUN_DONE 2026-10-22 18:05Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `sec-data-ingest` | 2 append | yes | 5 · 0 | SUCCESS live 2026-10-23 00:00Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-16 00:00Z; live RUN_DONE 2026-10-23 00:00Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `update-agent-performance` | 2 append | yes | 5 · 0 | SUCCESS live 2026-10-23 00:00Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-16 00:00Z; live RUN_DONE 2026-10-23 00:00Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `watchlist-enrichment-sweep` | 2 append | yes | 80 · 0 | SUCCESS live 2026-10-22 20:36Z | 2 / 3 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-15 20:30Z; live RUN_DONE 2026-10-22 20:36Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `weekly-incubator-builder` | 2 append | yes | 1 · 0 | SUCCESS live 2026-10-18 23:00Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-11 23:00Z; live RUN_DONE 2026-10-18 23:00Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `data-gap-resolver-at-0-10-16` | 4 llm | yes | 12 · 24 | SKIPPED live 2026-10-22 20:00Z (flock_held) | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-21 16:00Z; live RUN_DONE 2026-10-21 20:00Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `hermes-entity-spike-discovery` | 4 llm | yes | 12 · 44 | SUCCESS live 2026-10-23 01:15Z | 0 / 0 | **READY_FOR_CUTOVER** | latest dry_run fire RUN_DONE 2026-10-21 13:15Z; live RUN_DONE 2026-10-23 01:15Z; output_signal advanced on that run; shared lock: canary_on_cron |
| `disk-hygiene` | 1 read/overwrite | yes | 0 · 0 | never | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)); no successful live n8n run yet — RUN_SKIPPED_LOCK does not count (§23.21 (4), §23.12) |
| `finviz-enrichment` | 1 read/overwrite | yes | 5 · 0 | SKIPPED live 2026-10-22 17:00Z (flock_held) | 0 / 0 | **NOT_READY** | no successful live n8n run yet — RUN_SKIPPED_LOCK does not count (§23.21 (4), §23.12) |
| `finviz-sector-research` | 1 read/overwrite | yes | 10 · 0 | SKIPPED live 2026-10-22 20:15Z (flock_held) | 0 / 0 | **NOT_READY** | no successful live n8n run yet — RUN_SKIPPED_LOCK does not count (§23.21 (4), §23.12) |
| `hermes-discovery-scorecard` | 1 read/overwrite | yes | 7 · 0 | SUCCESS live 2026-10-22 09:30Z | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)); no_live_cron_line_for_match:'scripts/hermes_discovery_scorecard.py' — §23.21 (4) needs the live run with the cron line present |
| `materialize-watchlist-strategy-cards` | 1 read/overwrite | yes | 110 · 0 | SUCCESS live 2026-10-22 20:30Z | 0 / 0 | **NOT_READY** | no_live_cron_line_for_match:'scripts/materialize_watchlist_strategy_cards.py' — §23.21 (4) needs the live run with the cron line present |
| `n8n-comms-intent-consumer` | 1 read/overwrite | yes | 1292 · 0 | SUCCESS live 2026-10-23 02:10Z | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)) |
| `opening-intelligence-render` | 1 read/overwrite | yes | 5 · 0 | SUCCESS live 2026-10-22 13:15Z | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)) |
| `pr-hygiene-audit` | 1 read/overwrite | yes | 0 · 1 | SUCCESS dry_run 2026-10-22 10:31Z | 0 / 0 | **NOT_READY** | no successful live n8n run yet — RUN_SKIPPED_LOCK does not count (§23.21 (4), §23.12) |
| `registry-runtime-truth` | 1 read/overwrite | yes | 2 · 0 | FAILED live 2026-10-22 11:20Z (output_unverifiable) | 1 / 2 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)); no successful live n8n run yet — RUN_SKIPPED_LOCK does not count (§23.21 (4), §23.12); latest live run FAILED (output_unverifiable)… |
| `sync-social-to-intelligence` | 1 read/overwrite | yes | 10 · 0 | SUCCESS live 2026-10-22 19:30Z | 0 / 0 | **NOT_READY** | no_live_cron_line_for_match:'scripts/sync_social_to_intelligence.py' — §23.21 (4) needs the live run with the cron line present |
| `tmp-hygiene` | 1 read/overwrite | yes | 2 · 0 | SUCCESS live 2026-10-22 09:00Z | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)) |
| `agent-outcome-scorer` | 2 append | yes | 1 · 0 | SUCCESS live 2026-10-18 15:00Z | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)) |
| `build-symbol-profiles-at-0-19` | 2 append | yes | 1 · 0 | SUCCESS live 2026-10-18 23:15Z | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)) |
| `etf-analyst-enrich` | 2 append | yes | 1 · 0 | SUCCESS live 2026-10-17 11:02Z | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)) |
| `etf-performance-enrich` | 2 append | yes | 1 · 0 | SUCCESS live 2026-10-17 11:20Z | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)) |
| `hermes-learning-autonomous-self-tune` | 2 append | yes | 7 · 0 | SUCCESS live 2026-10-22 21:00Z | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)); output_signal advance of the last live RUN_DONE not recorded in its RunReceipt |
| `hermes-learning-config-governor` | 2 append | yes | 7 · 0 | SUCCESS live 2026-10-22 14:50Z | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)) |
| `hermes-learning-outcome-grader` | 2 append | yes | 7 · 0 | SUCCESS live 2026-10-22 14:50Z | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)); output_signal advance of the last live RUN_DONE not recorded in its RunReceipt |
| `hermes-learning-outcome-learning` | 2 append | yes | 7 · 0 | SUCCESS live 2026-10-22 14:50Z | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)); output_signal advance of the last live RUN_DONE not recorded in its RunReceipt |
| `incubator-rolloff-engine` | 2 append | yes | 5 · 0 | SUCCESS live 2026-10-22 14:00Z | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)) |
| `pattern-extractor` | 2 append | yes | 0 · 0 | never | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)); no successful live n8n run yet — RUN_SKIPPED_LOCK does not count (§23.21 (4), §23.12) |
| `hermes-learning-tag-engine` | 4 llm | yes | 7 · 0 | SUCCESS live 2026-10-22 14:50Z | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)); output_signal advance of the last live RUN_DONE not recorded in its RunReceipt |
| `hermes-watchlist-scorer` | 4 llm | yes | 122 · 13 | SUCCESS live 2026-10-23 02:00Z | 0 / 0 | **NOT_READY** | no_live_cron_line_for_match:'scripts/hermes_watchlist_scorer.py' — §23.21 (4) needs the live run with the cron line present |
| `trade-ai-scalp-live` | 6 broker | no | 0 · 420 | SUCCESS dry_run 2026-10-22 19:55Z | 0 / 0 | **NOT_READY** | not on the relay live list, so its canary slots are posted as dry_run: no live proof yet (§23.21 (4)); no successful live n8n run yet — RUN_SKIPPED_LOCK does not count (§23.21 (4), §23.12) |
| `release-train-request-0000` | 1 read/overwrite | yes | 0 · 0 | never | 0 / 0 | **BLOCKED** | registry state NEVER_SCHEDULED; no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)); no successful live n8n run yet — RUN_SKIPPED_LOCK does not count (§23.21 (4), §23.12) |
| `release-train-request-0600` | 1 read/overwrite | yes | 0 · 0 | never | 0 / 0 | **BLOCKED** | registry state NEVER_SCHEDULED; no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)); no successful live n8n run yet — RUN_SKIPPED_LOCK does not count (§23.21 (4), §23.12) |
| `release-train-request-0800` | 1 read/overwrite | yes | 0 · 0 | never | 0 / 0 | **BLOCKED** | registry state NEVER_SCHEDULED; no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)); no successful live n8n run yet — RUN_SKIPPED_LOCK does not count (§23.21 (4), §23.12) |
| `release-train-request-1800` | 1 read/overwrite | yes | 0 · 0 | never | 0 / 0 | **BLOCKED** | registry state NEVER_SCHEDULED; no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)); no successful live n8n run yet — RUN_SKIPPED_LOCK does not count (§23.21 (4), §23.12) |

### Shadow lanes (target: canary, onboarding steps 3/5/8/9, rule 5) — 47 lanes

| Lane | Tier | Live list | 7 d runs (live · dry) | Last run | Fails 24 h / 7 d | Verdict | Evidence or what is missing |
|---|---|---|---|---|---|---|---|
| `advisory-maturity-evidence` | 1 read/overwrite | no | 0 · 1 | SUCCESS dry_run 2026-10-22 10:17Z | 0 / 0 | **READY_FOR_CANARY** | latest dry_run fire RUN_DONE 2026-10-22 10:17Z |
| `cio-portfolio-thesis` | 1 read/overwrite | no | 0 · 1 | SUCCESS dry_run 2026-10-22 21:47Z | 0 / 0 | **READY_FOR_CANARY** | latest dry_run fire RUN_DONE 2026-10-22 21:47Z |
| `momentum-cache-reconcile` | 1 read/overwrite | no | 0 · 2016 | SUCCESS dry_run 2026-10-23 02:10Z | 0 / 0 | **READY_FOR_CANARY** | latest dry_run fire RUN_DONE 2026-10-23 02:10Z |
| `momentum-lifecycle-monitor` | 1 read/overwrite | no | 0 · 2016 | SUCCESS dry_run 2026-10-23 02:10Z | 0 / 0 | **READY_FOR_CANARY** | latest dry_run fire RUN_DONE 2026-10-23 02:10Z |
| `watch-goods-consistency` | 1 read/overwrite | no | 0 · 15 | SUCCESS dry_run 2026-10-22 20:40Z | 0 / 0 | **READY_FOR_CANARY** | latest dry_run fire RUN_DONE 2026-10-22 20:40Z; cron line flock lock /tmp/watch_goods_consistency.lock == allowlist lock |
| `hermes-discovery-yield-on-learning` | 2 append | no | 0 · 6 | SUCCESS dry_run 2026-10-22 06:20Z | 0 / 0 | **READY_FOR_CANARY** | latest dry_run fire RUN_DONE 2026-10-22 06:20Z |
| `indicator-engine` | 2 append | no | 0 · 5 | SUCCESS dry_run 2026-10-22 12:00Z | 0 / 0 | **READY_FOR_CANARY** | latest dry_run fire RUN_DONE 2026-10-22 12:00Z; cron line flock lock /tmp/indicator_engine.lock == allowlist lock |
| `goal-gate-bridge` | 1 read/overwrite | no | 0 · 168 | SUCCESS dry_run 2026-10-23 01:35Z | 0 / 0 | **NOT_READY** | the cron line has no `flock -n <lock>` (safe_flock.sh is not enough): a crontab edit must add one before canary (§23.12); the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wa… |
| `trade-backtest-engine` | 1 read/overwrite | no | 0 · 5 | SUCCESS dry_run 2026-10-22 22:30Z | 0 / 0 | **NOT_READY** | the cron line has no `flock -n <lock>` (safe_flock.sh is not enough): a crontab edit must add one before canary (§23.12); the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wa… |
| `aegis-evening-packet` | 2 append | no | 0 · 7 | SUCCESS dry_run 2026-10-22 23:45Z | 0 / 0 | **NOT_READY** | the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wave parse_lane_argv): unmapped_wrapper:env:PYTHONPATH |
| `finviz-enrichment-scalp-hot` | 2 append | no | 0 · 600 | SUCCESS dry_run 2026-10-22 19:55Z | 0 / 0 | **NOT_READY** | the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wave parse_lane_argv): unmapped_wrapper:env:SCALP_HOT_TIER |
| `finviz-market-movers` | 2 append | no | 0 · 220 | SUCCESS dry_run 2026-10-22 20:45Z | 0 / 0 | **NOT_READY** | the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wave parse_lane_argv): script_not_on_cron_line:scripts/finviz_market_movers.py |
| `hermes-scope-governor` | 2 append | no | 0 · 336 | SUCCESS dry_run 2026-10-23 02:07Z | 0 / 0 | **NOT_READY** | the cron line has no `flock -n <lock>` (safe_flock.sh is not enough): a crontab edit must add one before canary (§23.12); the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wa… |
| `hermes-score-event-feeder` | 2 append | no | 0 · 2016 | SUCCESS dry_run 2026-10-23 02:10Z | 0 / 0 | **NOT_READY** | the cron line has no `flock -n <lock>` (safe_flock.sh is not enough): a crontab edit must add one before canary (§23.12); the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wa… |
| `investment-costs` | 2 append | no | 0 · 5 | SUCCESS dry_run 2026-10-22 21:05Z | 0 / 0 | **NOT_READY** | the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wave parse_lane_argv): script_not_on_cron_line:scripts/investment_costs.py |
| `macro-calendar-refresh` | 2 append | no | 0 · 0 | never | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)) |
| `resolve-due-checkpoints` | 2 append | no | 0 · 168 | SUCCESS dry_run 2026-10-23 01:20Z | 0 / 0 | **NOT_READY** | the cron line has no `flock -n <lock>` (safe_flock.sh is not enough): a crontab edit must add one before canary (§23.12); the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wa… |
| `scalp-hot-list` | 2 append | no | 0 · 600 | SUCCESS dry_run 2026-10-22 13:58Z | 0 / 0 | **NOT_READY** | the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wave parse_lane_argv): unmapped_wrapper:env:MOMENTUM_SCALP_OUTER_DEADLINE_S; unmapped_wrapper:env:SCALP_HOT_TIER |
| `social-ingest-all` | 2 append | no | 0 · 5 | SUCCESS dry_run 2026-10-22 10:00Z | 0 / 0 | **NOT_READY** | the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wave parse_lane_argv): unmapped_wrapper:env; unmapped_wrapper:env:TRADEAI_EFFECT_CLAIM; unmapped_wrapper:scripts/effect_clai… |
| `trade-thesis-review-engine` | 2 append | no | 0 · 5 | SUCCESS dry_run 2026-10-22 22:40Z | 0 / 0 | **NOT_READY** | the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wave parse_lane_argv): unmapped_wrapper:env; unmapped_wrapper:env:TRADEAI_EFFECT_CLAIM; unmapped_wrapper:scripts/effect_clai… |
| `validate-expense-ratios` | 2 append | no | 0 · 0 | never | 0 / 0 | **NOT_READY** | no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)); the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wave parse_lane_argv): script_not_on_cron_line:scripts/v… |
| `update-lockup-earnings-dates` | 3 send | no | 0 · 7 | SUCCESS dry_run 2026-10-22 12:18Z | 0 / 0 | **NOT_READY** | the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wave parse_lane_argv): unmapped_wrapper:env; unmapped_wrapper:env:TRADEAI_EFFECT_CLAIM; unmapped_wrapper:scripts/effect_clai… |
| `hermes-research-agenda-at-45-7` | 4 llm | no | 0 · 7 | SUCCESS dry_run 2026-10-22 11:45Z | 0 / 0 | **NOT_READY** | the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wave parse_lane_argv): allowlist_command_args_not_on_cron_line:['--json'] vs ['--apply', '--json']; unmapped_wrapper:env; un… |
| `hermes-research-worker-pool` | 4 llm | no | 0 · 168 | SUCCESS dry_run 2026-10-23 02:05Z | 0 / 0 | **NOT_READY** | the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wave parse_lane_argv): unmapped_wrapper:env; unmapped_wrapper:env:TRADEAI_EFFECT_CLAIM; unmapped_wrapper:hermes-research-wor… |
| `news-to-catalyst` | 4 llm | no | 0 · 56 | SUCCESS dry_run 2026-10-23 02:05Z | 0 / 0 | **NOT_READY** | the cutover factory cannot derive live_arg from the cron line (n8n_cutover_wave parse_lane_argv): unmapped_wrapper:env; unmapped_wrapper:env:TRADEAI_EFFECT_CLAIM; unmapped_wrapper:news-to-catalyst; u… |
| `agent-number-grounding-slo` | 1 read/overwrite | no | 0 · 7 | SUCCESS dry_run 2026-10-22 22:40Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5) |
| `classifier-health-check` | 1 read/overwrite | no | 0 · 5 | SUCCESS dry_run 2026-10-22 11:55Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5) |
| `enterprise-backtester` | 1 read/overwrite | no | 0 · 1 | SUCCESS dry_run 2026-10-19 02:00Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5); the cutover factory cannot derive live_arg from the cron line (n8… |
| `fee-efficiency-analyzer` | 1 read/overwrite | no | 0 · 1 | SUCCESS dry_run 2026-10-19 11:25Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5); the cutover factory cannot derive live_arg from the cron line (n8… |
| `finviz-health-check` | 1 read/overwrite | no | 0 · 25 | SUCCESS dry_run 2026-10-22 22:25Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5) |
| `sector-rs-daily` | 1 read/overwrite | no | 0 · 5 | SUCCESS dry_run 2026-10-22 21:20Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5) |
| `setup-quality-prior` | 1 read/overwrite | no | 0 · 7 | SUCCESS dry_run 2026-10-23 02:00Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5); the cutover factory cannot derive live_arg from the cron line (n8… |
| `source-litmus-vs-yahoo` | 1 read/overwrite | no | 0 · 5 | SUCCESS dry_run 2026-10-22 11:45Z | 0 / 0 | **BLOCKED** | deferred by directive (F07 / registry_systemd stays on the host) |
| `aegis-nightly-ingestion` | 2 append | no | 0 · 7 | SUCCESS dry_run 2026-10-22 23:00Z | 0 / 0 | **BLOCKED** | held: the n8n reference workflow's inert lane (scripts/build_n8n_reference_workflow.py LANE; its allowlist live_arg must stay null and its effect key unarmed); the cutover factory cannot derive live_… |
| `agent-calibration-engine` | 2 append | no | 0 · 1 | SUCCESS dry_run 2026-10-18 16:00Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5); the cutover factory cannot derive live_arg from the cron line (n8… |
| `catalyst-momentum-engine-overnight` | 2 append | no | 0 · 14 | SUCCESS dry_run 2026-10-23 02:00Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5); the cutover factory cannot derive live_arg from the cron line (n8… |
| `hermes-learning-outcome-feedback-agent` | 2 append | no | 0 · 0 | never | 0 / 0 | **BLOCKED** | registry state NEVER_SCHEDULED; no n8n dry_run fire in the ledger (onboarding step 8 / §23.21 (2)) |
| `maturity-remeasure` | 2 append | yes | 0 · 1 | SUCCESS dry_run 2026-10-19 10:40Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5) |
| `signal-fusion-active` | 2 append | no | 0 · 229 | SUCCESS dry_run 2026-10-22 20:30Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5) |
| `signal-fusion-full` | 2 append | no | 0 · 10 | SUCCESS dry_run 2026-10-22 17:00Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5); the cutover factory cannot derive live_arg from the cron line (n8… |
| `write-state-freshness-history` | 2 append | no | 0 · 5 | SUCCESS dry_run 2026-10-22 11:15Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5); the cutover factory cannot derive live_arg from the cron line (n8… |
| `audit-enrichment-coverage` | 3 send | no | 0 · 5 | SUCCESS dry_run 2026-10-22 20:45Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5); sender lane: wrap the cron line with scripts/effect_claim_cron.sh… |
| `crawl-v3-dashboard` | 3 send | no | 0 · 7 | SUCCESS dry_run 2026-10-22 10:57Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5); sender lane: wrap the cron line with scripts/effect_claim_cron.sh… |
| `hermes-pipeline-health` | 3 send | no | 0 · 14 | SUCCESS dry_run 2026-10-22 19:45Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5); the cutover factory cannot derive live_arg from the cron line (n8… |
| `data-gap-resolver-pre` | 4 llm | no | 0 · 5 | SUCCESS dry_run 2026-10-22 22:00Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5); the cutover factory cannot derive live_arg from the cron line (n8… |
| `data-gap-resolver-weekly` | 4 llm | no | 0 · 1 | SUCCESS dry_run 2026-10-18 12:00Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5); the cutover factory cannot derive live_arg from the cron line (n8… |
| `hermes-topic-monitor-bridge` | 4 llm | no | 0 · 7 | SUCCESS dry_run 2026-10-22 11:30Z | 0 / 0 | **BLOCKED** | health contract DRAFT: the owner's REVIEW is owed — a workflow without a REVIEWED contract does not leave shadow (onboarding rule 5); the cutover factory cannot derive live_arg from the cron line (n8… |

---

Regenerate: open Ops → Controls → n8n lanes (the same computation), or call `n8n_view` on the host. The
tables above were rendered from that output; the proposal letters are this report's, not the server's.

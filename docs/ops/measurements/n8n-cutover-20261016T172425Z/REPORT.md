# n8n cutover outcomes — 2026-10-16T17:24:25+00:00

Schema `N8nCutoverOutcomes@v1` · authority `READ_ONLY_ADVISORY` · generator `scripts/report_n8n_cutover_outcomes.py` (read-only).

## 1. Header

| item | value |
|---|---|
| served SHA | `b120849ed435c20f443f36c2ddc2c9c597e92855` (b120849ed-main-exact-phase2-20261016-123446) |
| measurement window (UTC) | 2026-10-15T04:00:00+00:00 → 2026-10-16T17:24:25+00:00 |
| notifications window (today, ET midnight) | 2026-10-16T04:00:00+00:00 |
| sha256(crontab -l) | `c63ed64d7a182ff20d32e0835a8307634c13edaacf5e7863fd4e6b7c7163349d` |


### Counting definitions

- **disposition_row** — One row of LANE_DISPOSITION_20261015.csv: one active crontab line at build time (source=crontab) or one registry lane with no crontab line (source=registry_*). The 267 MIGRATE_N8N rows are 267 rows, not 267 jobs: several rows can name one lane, and one lane can be a family slot runner for many rows.
- **active_cron_line** — An uncommented, non-assignment line of the CURRENT `crontab -l` (same rule as lane_registry.discover_cron). A commented line is not a job.
- **unique_lane** — A distinct lane_id (config/lane_registry.json, plus relay live-list names). A crontab line is attributed to the single best-ranked registry match (n8n_lane_disposition.match_rows); lines with no match are UNMAPPED.
- **business_process** — Two levels, reported separately: (a) a WS2 family (disposition family_id, e.g. F44) = one business function implemented by one or more lanes; (b) a fabric process (config/n8n_fabric_processes.json, e.g. hermes-learning) = an ordered set of step lanes run as one n8n workflow.
- **n8n_primary** — The lane is on the relay live list (or is a registry scheduler.kind=n8n ACTIVE lane) AND it has no active cron line. MIGRATED_PROVEN additionally needs a commented cron line tagged `RETIRED <date> n8n-cutover` or `N8N-ONLY TEST` (or a native n8n row) AND >=1 live RUN_DONE receipt in the window.
- **parallel** — Relay-live AND >=1 live n8n receipt in the window AND an active cron line still fires the same lane. LIVE_LISTED_IDLE = relay-live + active cron line but ZERO live n8n receipts in the window (n8n is permitted, not firing: cron is the only primary that ran).
- **useful_live_output** — A live RUN_DONE receipt whose output_verdict.verdict == 'produced'.
- **verified_empty** — A live RUN_DONE receipt whose output_verdict.verdict == 'empty_allowed' (declared, reasoned empty).
- **unverified_ok** — A live RUN_DONE receipt with exit 0 but no evaluated output verdict (missing, no_rule or declared_not_enforced). Exit 0 is NOT evidence of work (AGENTS §0 rule 8); counted, never called useful.
- **failure** — A receipt in RUN_FAILED or RUN_TIMEOUT, or a live RUN_DONE with output verdict empty_violation/unverifiable.
- **refusal** — A relay_log.jsonl row with state REFUSED for the lane (the run never started).
- **lock_skip** — A receipt in RUN_SKIPPED_LOCK (another holder had the lane's flock).
- **ambiguous_effect** — An effect_claims row in CLAIMED or UNKNOWN (the effect may or may not have happened).
- **worker_seconds** — Sum of receipt duration_s.
- **incident_episode** — A distinct (lane, failure class) with >=1 event in the window, failure class = breach kind / diagnosis event_type (NO_OUTPUT, UNGOVERNED, STALE_2X, ...) or run:<reason> for failed receipts. Every further event of the same episode is a DUPLICATE event.
- **verified_recovery** — The OUTPUT condition recovered: a CLEARED breach row after the last OPEN one, or the lane's declared output signal (file mtime / JSON key) is now newer than the last breach's detection, or (run failures) a later receipt of the same lane+mode is RUN_DONE with output verdict produced/empty_allowed (dry_run: RUN_DONE). A REQUESTED / shadow remediation row is NOT a heal; a lower alert count is NOT recovery.
- **provenance** — Scheduler + lane named by the Telegram provenance footer `· via <n8n|cron|systemd> <lane>` (PR #1817) or run_id / source_job on the communication_events row. Anything else is UNKNOWN, never guessed.
- **deployed** — The PR's merge commit is an ancestor of the served SHA (git merge-base --is-ancestor).
- **proven** — A qualifying LIVE receipt exists: for a lane associated with the PR (a changed script is the lane's registry match, or the PR changed the lane's row in lane_registry/n8n_effect_keys/n8n_run_allowlist), a live RUN_DONE whose code_sha contains the merge commit and whose output verdict is produced/empty_allowed. PR #1817 is proven by a communication_events row carrying an `· via n8n` footer.

Disposition table: **534 rows** ({'crontab': 394, 'registry_none': 3, 'registry_systemd': 101, 'registry_cron_no_line': 23, 'registry_event': 5, 'registry_n8n': 8}), **519 unique lanes**. Rows by disposition {'CONSOLIDATE': 153, 'MIGRATE_N8N': 267, 'RETIRE': 11, 'STAY_HOST': 103}; unique lanes by disposition {'CONSOLIDATE': 145, 'MIGRATE_N8N': 264, 'RETIRE': 11, 'STAY_HOST': 103}. So 267 MIGRATE_N8N rows = 264 unique lanes, not jobs.

## 2. Migration state

| measure | n |
|---|---|
| active cron lines (now) | 336 |
|   … attributed to a lane | 336 |
|   … unmapped (no registry match) | 0 |
| unique lanes with ≥1 active cron line (remaining cron primaries) | 316 |
| commented cron lines by tag | {'RETIRED_OTHER': 34, 'CONSOLIDATED': 65, 'N8N_CUTOVER': 16, 'N8N_ONLY_TEST': 1} |
| relay live list (lanes n8n may run LIVE) | 52 |


Unique lanes by status (each lane exactly once):

| status | lanes |
|---|---|
| MIGRATED_PROVEN | 17 |
| N8N_NATIVE | 1 |
| N8N_PRIMARY_UNPROVEN | 6 |
| PARALLEL | 17 |
| LIVE_LISTED_IDLE | 13 |
| CRON_PRIMARY | 283 |
| CONSOLIDATED | 60 |
| RETIRED | 52 |
| HELD | 4 |
| RETAINED_F07 | 21 |
| RETAINED_SYSTEMD | 125 |
| OTHER | 42 |


**Migrated (proven)** (17): catalyst-graph, catalyst-symbol-impact, crontab-snapshot-for-health-agent, document-mentions-backfill, hermes-analyst-signal-discovery, hermes-governance-api, hermes-momentum-catalyst-scalp, hermes-news-bridge, identity-sweep-stage0, material-change-detector-stage1, n8n-incident-fanin, n8n-pilot-dispatch, n8n-research-intake-consumer, record-decision-outcome, research-insight-extractor, source-attribution-monitor, wire-advisory-lessons


**n8n-native** (1): heartbeat-watch


**PARALLEL — cron + n8n live both firing** (17): aegis-social-sentiment, aegis-transcript-discovery, agent-outcome-linker, daily-incubator-refresh, finviz-enrichment, finviz-proactive-research, finviz-screener-runner, finviz-sector-research, hermes-discovery-scorecard, hermes-social-sentiment, incubator-rolloff-engine, journal-tilt-morning-hook, materialize-watchlist-strategy-cards, opening-intelligence-render, proposal-backtest-engine, sync-social-to-intelligence, watchlist-enrichment-sweep


**LIVE_LISTED_IDLE — relay-live, cron line active, 0 live n8n runs in window** (13): agent-outcome-scorer, build-symbol-profiles-at-0-19, classify-instruments, commitment-outcome-sweep, etf-analyst-enrich, etf-performance-enrich, feedback-loop-processor, instrument-belief-writer, maturity-remeasure, pattern-extractor, sec-data-ingest, update-agent-performance, weekly-incubator-builder


**n8n primary but UNPROVEN** (6):

| lane_id | unproven_reason | n8n_cutover_tags | live_run_done | refusals |
|---|---|---|---|---|
| hermes-learning-config-governor | no live RUN_DONE in window |  | 0 | 0 |
| hermes-learning-outcome-grader | no live RUN_DONE in window |  | 0 | 1 |
| hermes-learning-outcome-learning | no live RUN_DONE in window |  | 0 | 0 |
| hermes-learning-tag-engine | no live RUN_DONE in window |  | 0 | 0 |
| momentum-cache-reconcile | no live RUN_DONE in window |  | 0 | 0 |
| momentum-lifecycle-monitor | no live RUN_DONE in window |  | 0 | 0 |


**Consolidated on host (stage runner, still cron)** (60) — listed in lanes.csv.


### Retained exceptions

F07 lanes: 21; registry_systemd ACTIVE lanes: 84; holds: 4 (full list in retained.csv).

| lane_id | reason | owner |
|---|---|---|
| coder-dispatch | operator_hold_20261016: disposition RETIRE; cron already commented | operator |
| defense-execution | operator_hold_20261016: cron paused for the SPCX incident (Schwab deactivated); reads broker credentials | operator |
| n8n-workflow-drift-check | operator_hold_20261016: registry state PAUSED, no cron line | operator |
| options-lifecycle-run | operator_hold_20261016: cron paused for the SPCX incident (Schwab deactivated); reads broker credentials | operator |


Independent P1 / dead-man backstops (must stay independent of n8n):

| lane_id | owner | purpose | registry_state | scheduler | status | relay_live |
|---|---|---|---|---|---|---|
| incident-notifier | platform | On-host P1 path: sends every fan-in P1 at once (uncapped, through quiet hours). | ACTIVE | cron:*/5 * * * * | CRON_PRIMARY | False |
| autonomy-watchdog | platform | Host watchdog: autonomy loop liveness (own systemd timer). | ACTIVE | systemd:tradeai-autonomy-watchdog.timer | RETAINED_SYSTEMD | False |
| portfolio-server-watchdog | platform | Restarts the :7777 API when it stops answering (F07). | ACTIVE | cron:*/2 * * * * | RETAINED_F07 | False |
| postgres-main-watchdog | platform | Detects/recovers postgres-main down (installed after the 09-18 ENOSPC crash). | ACTIVE | systemd:tradeai-postgres-main-watchdog.timer | RETAINED_F07 | False |
| n8n-lab-watchdog | platform | Host-side probe of the n8n lab /healthz every 5 min: watches the watcher. | ACTIVE | systemd:tradeai-n8n-lab-watchdog.timer (5m) | RETAINED_SYSTEMD | False |
| supervisor-breach-detector | platform | Writes supervisor_breaches.jsonl (NO_OUTPUT/STALE) independent of n8n. | ACTIVE | systemd:tradeai-supervisor-breach-detector.timer | RETAINED_SYSTEMD | False |
| health-tick | platform | One systemd 5-min timer running the host health/monitor cadence table (F07). | ACTIVE | systemd:tradeai-health-tick.timer (*:0/5) | RETAINED_F07 | False |
| process-reaper | platform | Kills hung / piled-up batch jobs (F07). | ACTIVE | cron:*/3 * * * * | RETAINED_F07 | False |
| offbox-deadman | operator | DD12 outside dead-man (scripts/offbox_deadman.py): built, NOT activated (operator packet). | UNREGISTERED | -: | UNREGISTERED | False |


## 3. Business processes fully owned by n8n

WS2 families fully n8n-owned: **1 of 53** (F49). Families with some n8n but not all (top 15 by lanes):

| family_id | lanes | status_counts | cron_or_parallel |
|---|---|---|---|
| F36 | 41 | {'CRON_PRIMARY': 21, 'LIVE_LISTED_IDLE': 1, 'OTHER': 1, 'RETAINED_SYSTEMD': 18} | 22 |
| F39 | 30 | {'CRON_PRIMARY': 20, 'MIGRATED_PROVEN': 3, 'N8N_PRIMARY_UNPROVEN': 2, 'PARALLEL': 1, 'RETAINED_SYSTEMD': 4} | 21 |
| F50 | 22 | {'CRON_PRIMARY': 11, 'LIVE_LISTED_IDLE': 5, 'MIGRATED_PROVEN': 3, 'PARALLEL': 3} | 19 |
| F44 | 21 | {'CRON_PRIMARY': 11, 'LIVE_LISTED_IDLE': 1, 'MIGRATED_PROVEN': 5, 'PARALLEL': 4} | 16 |
| F51 | 16 | {'CRON_PRIMARY': 9, 'LIVE_LISTED_IDLE': 1, 'PARALLEL': 1, 'RETAINED_SYSTEMD': 5} | 11 |
| F43 | 11 | {'CRON_PRIMARY': 7, 'PARALLEL': 4} | 11 |
| F45 | 11 | {'CRON_PRIMARY': 7, 'LIVE_LISTED_IDLE': 1, 'PARALLEL': 3} | 11 |
| F47 | 8 | {'CRON_PRIMARY': 6, 'MIGRATED_PROVEN': 2} | 6 |
| F42 | 7 | {'CRON_PRIMARY': 3, 'LIVE_LISTED_IDLE': 4} | 7 |
| F35 | 4 | {'CRON_PRIMARY': 3, 'PARALLEL': 1} | 4 |
| F52 | 2 | {'CRON_PRIMARY': 1, 'N8N_NATIVE': 1} | 1 |


Fabric processes:

| process | workflow_id | mode | fully_n8n_owned | why_not |
|---|---|---|---|---|
| hermes-learning | tradeai-fabric-hermes-learning | live | False | cron stage runner still active: hermes-learning-pipeline-learn, hermes-learning-pipeline-tune; step(s) without a live run in window: outcome_grader, tag_engine, outcome_feedback_agent, outcome_learning, config_governor, autonomous_self_tune |


## 4. Run outcomes (window)

| measure | n |
|---|---|
| receipts_in_window | 4153 |
| lanes_with_receipts | 82 |
| lanes_with_live_receipts | 35 |
| live_runs | 1508 |
| dry_runs | 2645 |
| useful_live_output | 108 |
| verified_empty | 31 |
| unverified_ok | 1333 |
| failures | 1 |
| lock_skips | 35 |
| refusals | 504 |
| ambiguous_effects | 0 |
| live_worker_s | 13387.5 |
| dry_worker_s | 2860.4 |


Refusals by reason: {'momentum_monitor_admission_unproven': 449, 'run_idempotency_conflict': 34, 'run_slot_not_due': 15, 'relay_lane_not_allowlisted': 4, 'relay_live_not_enabled': 2}

Effect claims by state: {'DONE': 72, 'RELEASED': 19, 'FAILED': 1}


Ledger cross-check (runs table, same window): [{'state': 'RUN_DONE', 'mode': 'dry_run', 'n': 2645}, {'state': 'RUN_DONE', 'mode': 'live', 'n': 1472}, {'state': 'RUN_FAILED', 'mode': 'live', 'n': 1}, {'state': 'RUN_SKIPPED_LOCK', 'mode': 'live', 'n': 35}]


Per lane with live runs:

| lane_id | status | live_runs | useful_live_output | verified_empty | unverified_ok | failures | lock_skips | refusals | ambiguous_effects | live_worker_s | dry_runs |
|---|---|---|---|---|---|---|---|---|---|---|---|
| heartbeat-watch | N8N_NATIVE | 449 | 0 | 0 | 449 | 0 | 0 | 49 | 0 | 79.4 | 0 |
| n8n-incident-fanin | MIGRATED_PROVEN | 449 | 0 | 0 | 449 | 0 | 0 | 0 | 0 | 10757.7 | 0 |
| n8n-pilot-dispatch | MIGRATED_PROVEN | 150 | 0 | 0 | 150 | 0 | 0 | 0 | 0 | 134.2 | 0 |
| n8n-research-intake-consumer | MIGRATED_PROVEN | 150 | 0 | 0 | 150 | 0 | 0 | 0 | 0 | 65.0 | 0 |
| crontab-snapshot-for-health-agent | MIGRATED_PROVEN | 113 | 0 | 0 | 113 | 0 | 0 | 0 | 0 | 33.0 | 0 |
| hermes-governance-api | MIGRATED_PROVEN | 46 | 45 | 0 | 1 | 0 | 0 | 0 | 0 | 111.4 | 90 |
| identity-sweep-stage0 | MIGRATED_PROVEN | 33 | 18 | 9 | 6 | 0 | 0 | 0 | 0 | 48.2 | 43 |
| material-change-detector-stage1 | MIGRATED_PROVEN | 33 | 13 | 14 | 6 | 0 | 0 | 0 | 0 | 24.6 | 43 |
| document-mentions-backfill | MIGRATED_PROVEN | 16 | 11 | 2 | 3 | 0 | 0 | 0 | 0 | 628.6 | 21 |
| materialize-watchlist-strategy-cards | PARALLEL | 15 | 3 | 0 | 0 | 0 | 12 | 0 | 0 | 26.7 | 22 |
| watchlist-enrichment-sweep | PARALLEL | 9 | 0 | 0 | 0 | 0 | 9 | 0 | 0 | 0.2 | 16 |
| hermes-momentum-catalyst-scalp | MIGRATED_PROVEN | 7 | 2 | 0 | 0 | 0 | 5 | 0 | 0 | 78.4 | 10 |
| hermes-analyst-signal-discovery | MIGRATED_PROVEN | 6 | 5 | 0 | 1 | 0 | 0 | 0 | 0 | 4.3 | 7 |
| research-insight-extractor | MIGRATED_PROVEN | 5 | 0 | 0 | 5 | 0 | 0 | 0 | 0 | 24.9 | 0 |
| wire-advisory-lessons | MIGRATED_PROVEN | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 4.3 | 1 |
| catalyst-symbol-impact | MIGRATED_PROVEN | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 1.1 | 3 |
| finviz-proactive-research | PARALLEL | 2 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 8.3 | 4 |
| hermes-news-bridge | MIGRATED_PROVEN | 2 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0.5 | 3 |
| proposal-backtest-engine | PARALLEL | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 1.2 | 3 |
| aegis-social-sentiment | PARALLEL | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.2 | 2 |
| aegis-transcript-discovery | PARALLEL | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.0 | 1 |
| agent-outcome-linker | PARALLEL | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.0 | 1 |
| catalyst-graph | MIGRATED_PROVEN | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1.0 | 1 |
| daily-incubator-refresh | PARALLEL | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 251.3 | 1 |
| finviz-enrichment | PARALLEL | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.0 | 1 |
| finviz-screener-runner | PARALLEL | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1100.8 | 1 |
| finviz-sector-research | PARALLEL | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.0 | 2 |
| hermes-discovery-scorecard | PARALLEL | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.0 | 0 |
| hermes-social-sentiment | PARALLEL | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.0 | 2 |
| incubator-rolloff-engine | PARALLEL | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0.8 | 0 |
| journal-tilt-morning-hook | PARALLEL | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0.3 | 1 |
| opening-intelligence-render | PARALLEL | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.0 | 0 |
| record-decision-outcome | MIGRATED_PROVEN | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0.2 | 1 |
| source-attribution-monitor | MIGRATED_PROVEN | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0.3 | 3 |
| sync-social-to-intelligence | PARALLEL | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0.6 | 2 |


## 5. Incidents (window)

| measure | n |
|---|---|
| distinct episodes (lane × failure class) | 87 |
| events | 1906 |
| duplicate events | 1819 |
| episodes by recovery verdict | {'UNRESOLVED': 66, 'VERIFIED_RECOVERED': 21} |
| episodes by class | {'UNGOVERNED': 16, 'NO_OUTPUT': 64, 'RUN_FAILED': 3, 'run_receipt_failure': 1, 'SILENT': 1, 'STALE_OUTPUT': 2} |
| remediation rows (REQUESTED / shadow — NOT heals) | {'supervisor_recoveries_in_window': 3787, 'executed_true': 0, 'modes': {'shadow': 3787}, 'diagnoses_with_remediation_run_id': 0} |
| diagnoses by outcome | {'no_diagnosis': 1767, 'diagnosed': 39} |
| failure-diagnosis state | {'diagnosed_in_window': 39, 'diagnosed_by_action': {'suggest_only': 39}, 'pending': 0, 'lane_last_remediation': 0} |
| unreleased dead letters in window | 1 |


Verified recoveries (21):

| lane_id | failure_class | events | last_at | recovery_evidence |
|---|---|---|---|---|
| build-hermes-canonical-status | NO_OUTPUT | 82 | 2026-10-16T12:18:02+00:00 | output signal now 2026-10-16T16:15:06+00:00 > last breach detection 2026-10-16T10:30:16+00:00 |
| cio-entry-state | NO_OUTPUT | 1 | 2026-10-15T14:25:33+00:00 | output signal now 2026-10-16T17:20:02+00:00 > last breach detection 2026-10-15T14:25:33+00:00 |
| directive-keyword-enhancer | NO_OUTPUT | 2 | 2026-10-16T10:40:18+00:00 | output signal now 2026-10-16T16:55:01+00:00 > last breach detection 2026-10-16T10:40:18+00:00 |
| external-market-data-ingest | NO_OUTPUT | 2 | 2026-10-16T11:31:45+00:00 | output signal now 2026-10-16T17:15:01+00:00 > last breach detection 2026-10-16T11:31:45+00:00 |
| finviz-screener-runner | NO_OUTPUT | 13 | 2026-10-16T17:18:01+00:00 | output signal now 2026-10-16T15:55:12+00:00 > last breach detection 2026-10-16T14:15:14+00:00 |
| goal-gate-bridge | NO_OUTPUT | 1 | 2026-10-15T20:32:04+00:00 | output signal now 2026-10-16T16:35:04+00:00 > last breach detection 2026-10-15T20:32:04+00:00 |
| hermes-coordinator | NO_OUTPUT | 2 | 2026-10-16T10:16:14+00:00 | output signal now 2026-10-16T17:17:47+00:00 > last breach detection 2026-10-16T10:16:14+00:00 |
| hermes-directive-discovery | NO_OUTPUT | 2 | 2026-10-16T10:16:14+00:00 | output signal now 2026-10-16T17:01:23+00:00 > last breach detection 2026-10-16T10:16:14+00:00 |
| hermes-score-alerts | NO_OUTPUT | 2 | 2026-10-16T10:30:16+00:00 | output signal now 2026-10-16T17:15:05+00:00 > last breach detection 2026-10-16T10:30:16+00:00 |
| hermes-subject-enhance-dispatch | NO_OUTPUT | 2 | 2026-10-16T13:16:24+00:00 | output signal now 2026-10-16T17:20:01+00:00 > last breach detection 2026-10-16T13:16:24+00:00 |
| incubator-rolloff-engine | NO_OUTPUT | 2 | 2026-10-16T00:00:35+00:00 | output signal now 2026-10-16T14:00:23+00:00 > last breach detection 2026-10-16T00:00:35+00:00 |
| indicator-engine | NO_OUTPUT | 1 | 2026-10-15T18:38:29+00:00 | output signal now 2026-10-16T12:00:14+00:00 > last breach detection 2026-10-15T18:38:29+00:00 |
| premarket-data-pipeline | NO_OUTPUT | 1 | 2026-10-16T10:00:03+00:00 | output signal now 2026-10-16T10:12:15+00:00 > last breach detection 2026-10-16T10:00:03+00:00 |
| proposal-llm-review-worker | NO_OUTPUT | 2 | 2026-10-16T10:16:14+00:00 | output signal now 2026-10-16T17:00:37+00:00 > last breach detection 2026-10-16T10:16:14+00:00 |
| rag-indexer | NO_OUTPUT | 2 | 2026-10-16T12:17:03+00:00 | output signal now 2026-10-16T16:02:01+00:00 > last breach detection 2026-10-16T12:17:03+00:00 |
| run-research-intelligence-overnight | NO_OUTPUT | 2 | 2026-10-16T00:00:35+00:00 | output signal now 2026-10-16T05:06:53+00:00 > last breach detection 2026-10-16T00:00:35+00:00 |
| send-telegram-proposal-alert | NO_OUTPUT | 2 | 2026-10-16T13:16:24+00:00 | output signal now 2026-10-16T17:24:06+00:00 > last breach detection 2026-10-16T13:16:24+00:00 |
| source-litmus-vs-yahoo | NO_OUTPUT | 2 | 2026-10-16T00:00:35+00:00 | output signal now 2026-10-16T11:46:20+00:00 > last breach detection 2026-10-16T00:00:35+00:00 |
| topic-ingestion | NO_OUTPUT | 1 | 2026-10-16T00:00:35+00:00 | output signal now 2026-10-16T05:06:52+00:00 > last breach detection 2026-10-16T00:00:35+00:00 |
| watch-directives-service | NO_OUTPUT | 2 | 2026-10-16T13:16:24+00:00 | output signal now 2026-10-16T17:01:23+00:00 > last breach detection 2026-10-16T13:16:24+00:00 |
| watchlist-enrichment-sweep | NO_OUTPUT | 89 | 2026-10-16T12:18:02+00:00 | output signal now 2026-10-16T17:07:57+00:00 > last breach detection 2026-10-15T13:16:44+00:00 |


Unresolved episodes are listed in episodes.csv.


## 6. Notifications (today, ET)

| stage | counts |
|---|---|
| n8n comms intents (coordination ledger) | {'DIGEST/QUEUED': 1} |
| router decisions (notification_intent_receipts) | {'DELIVER': 60, 'HELD_QUIET_HOURS': 9, 'DIGEST': 108, 'DEDUPED': 2} |
| communication_events OUTBOUND | 279 |
| scheduler × delivery status | {'UNKNOWN/LEGACY_DELIVERED': 35, 'UNKNOWN/SENT': 68, 'UNKNOWN/SUPPRESSED': 162, 'cron/LEGACY_DELIVERED': 1, 'cron/SENT': 2, 'cron/SUPPRESSED': 7, 'systemd/LEGACY_DELIVERED': 1, 'systemd/SUPPRESSED': 3} |
| attribution | {'attributed': 14, 'UNKNOWN': 265} |
| telegram idempotency keys today (by prefix) | {} |
| telegram daily send budget today | UNKNOWN |


Attribution by source: {'UNKNOWN': 265, 'systemd:claude-escalation-handler': 2, 'cron:hermes-score-alerts': 2, 'cron:claude-escalation-handler': 2, 'cron:scalp-shadow-logger': 1, 'cron:process-reaper': 1, 'cron:incident-notifier': 1, 'cron:inference-layer-engine': 1, 'systemd:system-health-agent': 1, 'systemd:autonomy-watchdog': 1, 'cron:cio-entry-state-runner': 1, 'cron:stop-health-check': 1}

No shared key joins a router receipt to a communication_events row (router rows carry producer + decision, events carry one generic chokepoint producer name); the chain is reported as per-stage counts. Per-message intent->delivery linkage is UNKNOWN except where the provenance footer names the lane.


## 7. Effect protection (qualified)

Keys in config/n8n_effect_keys.json: 69; by protection level: {'STAGED': 33, 'N8N_SIDE_ONLY': 22, 'SINGLE_OWNER_CLAIMING': 9, 'OWNER_ROW_ONLY': 5}. SINGLE_OWNER_CLAIMING = owner row is n8n, the executor claimed DONE keys in the window and no active cron line fires the lane. That is the ONLY class where "cannot run twice" is supported, and only for runs through the n8n executor (a manual run outside it is not fenced); a refused duplicate claim is not itself recorded (refused claims write no row). Relay-level duplicate refusals (run_idempotency_conflict) are in lanes.csv refusal_reasons. N8N_SIDE_ONLY = the cron copy is not wrapped (no effect_claim_cron.sh / TRADEAI_EFFECT_CLAIM on the line; PR #1823 open), so a cron run and an n8n run of the same slot CAN both take effect. late_write_fenced is false for every key (no lane calls assert_fence yet; PR #1821 open).

| lane_id | owner | epoch | n8n_claim | active_cron_lines | active_cron_lines_wrapped | claims_done | claims_ambiguous | late_write_fenced | protection |
|---|---|---|---|---|---|---|---|---|---|
| aegis-social-sentiment | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| aegis-transcript-discovery | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| agent-outcome-linker | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| agent-outcome-scorer | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| build-symbol-profiles-at-0-19 | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| catalyst-symbol-impact | n8n | 1 | True | 0 | 0 | 2 | 0 | False | SINGLE_OWNER_CLAIMING |
| commitment-outcome-sweep | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| daily-incubator-refresh | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| document-mentions-backfill | n8n | 1 | True | 0 | 0 | 16 | 0 | False | SINGLE_OWNER_CLAIMING |
| etf-analyst-enrich | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| etf-performance-enrich | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| feedback-loop-processor | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| finviz-proactive-research | n8n | 1 | True | 1 | 0 | 1 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| finviz-screener-runner | n8n | 1 | True | 1 | 0 | 1 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| hermes-analyst-signal-discovery | n8n | 1 | True | 0 | 0 | 6 | 0 | False | SINGLE_OWNER_CLAIMING |
| hermes-learning-config-governor | n8n | 2 | False | 0 | 0 | 0 | 0 | False | OWNER_ROW_ONLY |
| hermes-learning-outcome-feedback-agent | cron | 1 | False | 0 | 0 | 0 | 0 | False | OWNER_ROW_ONLY |
| hermes-learning-outcome-grader | n8n | 2 | False | 0 | 0 | 0 | 0 | False | OWNER_ROW_ONLY |
| hermes-learning-outcome-learning | n8n | 2 | False | 0 | 0 | 0 | 0 | False | OWNER_ROW_ONLY |
| hermes-learning-tag-engine | n8n | 2 | False | 0 | 0 | 0 | 0 | False | OWNER_ROW_ONLY |
| hermes-momentum-catalyst-scalp | n8n | 1 | True | 0 | 0 | 2 | 0 | False | SINGLE_OWNER_CLAIMING |
| hermes-news-bridge | n8n | 1 | True | 0 | 0 | 2 | 0 | False | SINGLE_OWNER_CLAIMING |
| hermes-social-sentiment | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| incubator-rolloff-engine | n8n | 1 | True | 1 | 0 | 1 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| instrument-belief-writer | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| journal-tilt-morning-hook | n8n | 1 | True | 1 | 0 | 1 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| material-change-detector-stage1 | n8n | 1 | True | 0 | 0 | 33 | 0 | False | SINGLE_OWNER_CLAIMING |
| pattern-extractor | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| proposal-backtest-engine | n8n | 1 | True | 1 | 0 | 2 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| record-decision-outcome | n8n | 1 | True | 0 | 0 | 1 | 0 | False | SINGLE_OWNER_CLAIMING |
| sec-data-ingest | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| source-attribution-monitor | n8n | 1 | True | 0 | 0 | 1 | 0 | False | SINGLE_OWNER_CLAIMING |
| update-agent-performance | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| watchlist-enrichment-sweep | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| weekly-incubator-builder | n8n | 1 | True | 1 | 0 | 0 | 0 | False | N8N_SIDE_ONLY (active cron line not wrapped: cron copy can still run the effect) |
| wire-advisory-lessons | n8n | 1 | True | 0 | 0 | 3 | 0 | False | SINGLE_OWNER_CLAIMING |


## 8. Next cohorts and burn-down

| cohort | lanes | owner |
|---|---|---|
| C1_parallel_retire_cron_copy | 17 | operator (crontab edit under config-write grant; cutover packet by Agent A) |
| C2_live_listed_unproven | 19 | Agent A (relay-live but no live RUN_DONE in window: find why; fix or delist) |
| C3_shadow_proven_ready_for_live | 37 | Agent A (canary packet + effect key) -> operator (relay live list + crontab) |
| C4a_allowlisted_no_shadow_run | 8 | Agent A (dispatch block / shadow wave so a dry run exists) |
| C4b_not_onboarded | 223 | Agent A (allowlist + health contract PR per lane) |
| C5_p1_last | 14 | operator (policy p1_last: last cohort, cron kept one trading day after proof) |
| C6_operator_hold | 4 | operator (holds in config/lane_cutover_policy.json) |
| C7_retire_pending | 1 | operator (disposition RETIRE but the cron line is still active: retire packet) |


Remaining (excl. holds): **319** lanes. Observed tagged migrations by date: {'2026-10-09': 4, '2026-10-13': 1, '2026-10-16': 12}. Rate 5.67 lanes/trading day → projected completion **2027-01-03**.

Assumptions:

- rate = mean of n8n-cutover/N8N-ONLY tagged cron retirements over the last 3 dates that had any (a calendar date with zero retirements is not in the denominator), so the rate is optimistic
- one migrating lane needs: allowlist + dry run + live canary + effect key/owner + cron retirement
- trading days only (5 of 7); holds, F07 and registry_systemd are excluded (retained by directive)
- no new lanes are added; open PRs #1818-#1823 merge and deploy without rework

Open PRs carrying blockers: see section 9 (state OPEN).


## 9. PRs #1808–#1823: merged / deployed / proven

| pr | state | merged | deployed | proven | evidence | title |
|---|---|---|---|---|---|---|
| 1808 | MERGED | True | True | PARTIAL | 3/8 lanes proven; missing: agent-outcome-linker, classify-instruments, etf-analyst-enrich, etf-performance-enrich, feedback-loop-processor | n8n CW1 batch 1: 8 lanes write produced_count + opt into output verdict |
| 1809 | MERGED | True | True | PARTIAL | 6/9 lanes proven; missing: finviz-enrichment, finviz-enrichment-scalp-hot, finviz-sector-research | n8n CW1 batch 2: finviz x4 + hermes x4 write produced_count + opt into output verdict |
| 1810 | MERGED | True | True | PARTIAL | 6/8 lanes proven; missing: sec-data-ingest, update-agent-performance | n8n CW1 batch 3: 8 lanes write produced_count + opt into output verdict |
| 1811 | MERGED | True | True | UNPROVEN | 0/8 lanes have a live produced/empty_allowed receipt at a SHA containing the merge | n8n CW1/CW2 batch 4: 8 lanes write produced_count + opt into output verdict |
| 1812 | MERGED | True | True | PARTIAL | 4/9 lanes proven; missing: build-symbol-profiles-at-0-19, hermes-discovery-scorecard, opening-intelligence-render, pattern-extractor, weekly-incubator-builder | n8n CW2/CW3 batch 5: 9 lanes write produced_count + opt into output verdict |
| 1813 | MERGED | True | True | PROVEN | 5/5 lanes have a qualifying live receipt | n8n cutover: 5 CW1 lanes canary -> cutover (cron retired 2026-10-16) |
| 1814 | MERGED | True | False | UNPROVEN | NOT DEPLOYED (merge commit not in served SHA); no lane associated with the PR's changes | §23.25 gate alignment: lift cron markers + soft tokens for approved families; 4 holds; P1 last |
| 1815 | MERGED | True | True | UNPROVEN | 0/9 lanes have a live produced/empty_allowed receipt at a SHA containing the merge | hermes-learning cutover PR-2: 4 learn steps live at canary (feedback agent held), same-morning packe |
| 1816 | MERGED | True | True | UNPROVEN | 0/9 lanes have a live produced/empty_allowed receipt at a SHA containing the merge | hermes-learning: one-day live_manual_slots (until 2026-10-16 23:59 ET) + guarded manual fallback |
| 1817 | MERGED | True | True | PARTIAL | 14 outbound rows today carry a footer, 0 name n8n | comms: Telegram provenance footer (n8n/cron lane) + explicit catalyst line on Active Trader alerts |
| 1818 | MERGED | True | False | UNPROVEN | NOT DEPLOYED (merge commit not in served SHA); 0/8 lanes have a live produced/empty_allowed receipt at a SHA containing the merge | n8n/comms follow-ups: AT catalyst research + persistent store, n8n-today CC tab, premarket dedupe, n |
| 1819 | OPEN | False | False | UNPROVEN | not merged | n8n self-healing: dedupe by signature, deterministic closes, gated live heal, P1-once / P2-digest (+ |
| 1820 | OPEN | False | False | UNPROVEN | not merged | n8n self-healing follow-ups (stacked on #1819): slot-bound live retry, P2 digest, catalogue approval |
| 1821 | OPEN | False | False | UNPROVEN | not merged | assert_fence wave 1 (stacked on #1820): social sentiment x2 + finviz screener runner; market movers  |
| 1822 | MERGED | True | False | UNPROVEN | NOT DEPLOYED (merge commit not in served SHA); no lane associated with the PR's changes | n8n: dry-run load measured (0 parallel dry runs on live lanes); pin invariant + read-only report |
| 1823 | MERGED | True | False | UNPROVEN | NOT DEPLOYED (merge commit not in served SHA); no lane associated with the PR's changes | ops: cron copy respects effect ownership (effect_claim_cron wrap packet) |


## Not measured / caveats

- config/lane_cutover_policy.json is read from this checkout (main); the served release does not contain it, so its holds / p1_last are merged policy, not yet the enforced dispatch gate
- Lane attribution of a crontab line is a substring match against registry rows; a line no row matches is counted UNMAPPED, never guessed.
- Receipts carry no output verdict until a lane emits produced_count and opts in (output_receipt v2); those live runs are `unverified_ok`, not useful output.

Files: summary.json, lanes.csv, families.csv, retained.csv, episodes.csv, effect_protection.csv, prs.csv, notifications.json, burn_down.json.


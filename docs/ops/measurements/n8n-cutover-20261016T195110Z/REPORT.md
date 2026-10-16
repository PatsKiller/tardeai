# n8n cutover outcomes — 2026-10-16T19:51:10+00:00

**Status:** MEASUREMENT (read-only snapshot; a later packet supersedes it)  
**Date:** 2026-10-16T19:51:10+00:00  
**Authority:** READ_ONLY_ADVISORY

Schema `N8nCutoverOutcomes@v1` · authority `READ_ONLY_ADVISORY` · generator `scripts/report_n8n_cutover_outcomes.py` (read-only).

## 1. Header

| item | value |
|---|---|
| served SHA | `290fce36f85e3421ca586b840b83ca7cc3aea9ac` (290fce36f-main-exact-phase2-20261016-151300) |
| config / registry read from checkout | `22890d36df6b68399de66251efdf093c001c74fa` (not the served release) |
| measurement window (UTC) | 2026-10-15T04:00:00+00:00 → 2026-10-16T19:51:10+00:00 |
| notifications window (today, ET midnight) | 2026-10-16T04:00:00+00:00 |
| sha256(crontab -l) | `b78bbb101f1d1f718f20912333bf0a1bff61983108217b8490c871565e2d99d8` |
| captured at | 2026-10-16T19:51:10+00:00 (2026-10-16 15:51:10 EDT) |
| served effect-claim wrapper | FAIL-OPEN on an unreadable ledger (`/home/johnclaw/trade-ai-releases/portfolio-server/290fce36f-main-exact-phase2-20261016-151300/scripts/effect_claim_cron.sh`) |
| wrapper events (window) | {'run_unclaimed_cron_claim_false': 10, 'completed_unclaimed': 10, 'skipped_effect': 27}; first event 2026-10-16T19:20:02+00:00, last 2026-10-16T19:50:02+00:00 |
| handover manifest | ABSENT (0 processes) `/home/johnclaw/trade-ai-releases/persistent-state/data/governance/n8n_handover_manifest.json` |
| coordination ledger readable at capture | True |

- Context (operator-supplied): Served release 290fce36f, CURRENT is 290fce36f-main-exact-phase2-20261016-151300
- Context (operator-supplied): The cron effect-claim wrapper, PR 1823, was installed on the live crontab at 15:18 ET 2026-10-16; the first wrapper event is 15:20 ET
- Context (operator-supplied): The served wrapper is the 1823 fail-open version; the fail-closed policy of the architect review PR 1 is NOT deployed, so no lane can be protected fail-closed in this packet

### Counting definitions

- **disposition_row** — One row of LANE_DISPOSITION_20261015.csv: one active crontab line at build time (source=crontab) or one registry lane with no crontab line (source=registry_*). The 267 MIGRATE_N8N rows are 267 rows, not 267 jobs: several rows can name one lane, and one lane can be a family slot runner for many rows.
- **active_cron_line** — An uncommented, non-assignment line of the CURRENT `crontab -l` (same rule as lane_registry.discover_cron). A commented line is not a job.
- **unique_lane** — A distinct lane_id (config/lane_registry.json, plus relay live-list names). A crontab line is attributed to the single best-ranked registry match (n8n_lane_disposition.match_rows); lines with no match are UNMAPPED.
- **business_process** — Two levels, reported separately: (a) a WS2 family (disposition family_id, e.g. F44) = one business function implemented by one or more lanes; (b) a fabric process (config/n8n_fabric_processes.json, e.g. hermes-learning) = an ordered set of step lanes run as one n8n workflow.
- **n8n_primary** — The lane is on the relay live list (or is a registry scheduler.kind=n8n ACTIVE lane) AND no active cron line RUNS it (no active line, or every active line is effect-claim wrapped and stood down).
- **scheduler_ownership (S)** — n8n primary AND the cron copy is gone: either no active cron line plus a commented line tagged `RETIRED <date> n8n-cutover` / `N8N-ONLY TEST` (or a native n8n row), or EVERY active cron line runs scripts/effect_claim_cron.sh switched on for the lane (TRADEAI_EFFECT_CLAIM=<lane>) and the wrapper's LAST event for it in the window is skipped_effect / skipped_ownership_unknown (logs/effect_claim_events.jsonl: the cron copy fired and ran nothing). A wrapped line with no event yet, or whose last event ran the command, is NOT ownership.
- **execution (E)** — >=1 live RUN_DONE receipt for the lane in the window.
- **useful_output (U)** — >=1 live RUN_DONE whose output verdict is produced or empty_allowed.
- **MIGRATED_PROVEN** — S AND E AND U (2026-10-16 architect review: a completed live run alone is not proof). N8N_NATIVE is the same bar for a lane with no cron history (registry kind n8n, no retirement tag, no cron line); a native row WITH a retirement tag is a migration. n8n-live lanes are also reported by S/E/U combination (e.g. S1E1U0 = owns + ran, output unverified). A skip on a scheduled fire of the line is told apart from an off-schedule (manual / install verification) skip.
- **parallel** — Relay-live AND >=1 live n8n receipt in the window AND an active cron line still RUNS the lane (unwrapped, or wrapped but its last wrapper event ran the command / no event yet). LIVE_LISTED_IDLE = the same with ZERO live n8n receipts in the window (n8n is permitted, not firing).
- **protection_mode** — Effect protection qualified by ledger health and wrapper policy. FAIL_CLOSED = handover manifest names n8n, every active cron line is wrapped, and the SERVED wrapper fails closed (knows skipped_ownership_unknown): the cron copy cannot take effect even with the ledger unreadable. LEDGER_HEALTHY_ONLY = owner n8n and every line wrapped, but the served wrapper fails OPEN on an unreadable ledger (or the manifest lacks the process): protected only while the ledger answers. NO_CRON_COPY = handed over, no active cron line. UNPROTECTED_CRON_UNWRAPPED = handed over, >=1 active line unwrapped. NOT_HANDED_OVER = neither store says n8n. A manifest/ledger disagreement is reported, never reconciled (AGENTS §0 rule 5).
- **cron_stood_down** — A skipped_effect (owner n8n) or skipped_ownership_unknown (fail-closed) event in logs/effect_claim_events.jsonl: the wrapped cron line fired and ran nothing.
- **event_trigger_state** — Per config/lane_registry.json dispatch.triggers entry: LIVE_FIRING (>=1 live `e:` receipt in window), LIVE_ARMED_NOT_FIRED, SHADOW_FIRING (dispatch dry_run, >=1 dry `e:` receipt), SHADOW_NOT_FIRED, INACTIVE. clock_fallback = every clock that still fires the lane (dispatch.cron d: slots, active crontab lines).
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
| N8N_NATIVE | 0 |
| N8N_PRIMARY_UNPROVEN | 29 |
| PARALLEL | 6 |
| LIVE_LISTED_IDLE | 2 |
| CRON_PRIMARY | 283 |
| CONSOLIDATED | 60 |
| RETIRED | 52 |
| HELD | 4 |
| RETAINED_F07 | 21 |
| RETAINED_SYSTEMD | 125 |
| OTHER | 44 |


### Three separate measures (n8n-live lanes)

S = scheduler ownership, E = execution (live RUN_DONE), U = useful output (produced / empty_allowed). Proven = S and E and U.

| measure | lanes |
|---|---|
| n8n_live_lanes_measured | 54 |
| scheduler_ownership_n8n | 42 |
|   via_cron_retired_tag | 17 |
|   via_cron_wrapped_skipping | 22 |
|   via_n8n_native_row | 3 |
| execution_live_run_done | 25 |
| useful_output | 19 |
| proven_S_E_U | 17 |
| owned_but_no_live_run_S1E0 | 19 |


Wrapped active cron lines: 46; of those, last wrapper event is a skip (stood down): 22. Skip events on a scheduled fire of the line: 2; off-schedule (manual / install verification, not a slot): 25. S1E0 lanes (n8n owns the schedule, no live n8n RUN_DONE in the window): 19. For these the wrapped cron copy stands down at its next slot, so the effect now depends on n8n firing it, and there is no live n8n RUN_DONE in the window yet to show that it does.


Lanes by combination:

| combo | meaning | lanes | lane_ids |
|---|---|---|---|
| S1E1U1 | PROVEN: n8n owns the schedule, ran live, produced useful output | 17 | catalyst-graph, catalyst-symbol-impact, document-mentions-backfill, finviz-proactive-research, finviz-screener-runner, hermes-analyst-signal-discovery, hermes-governance-api, hermes-momentum-catalyst-scalp, hermes-news-bridge, identity-sweep-stage0, incubator-rolloff-engine, journal-tilt-morning-hook, material-change-detector-stage1, proposal-backtest-engine, record-decision-outcome, source-attribution-monitor, wire-advisory-lessons |
| S1E1U0 | n8n owns + ran live, output unverified (exit 0 is not evidence) | 6 | crontab-snapshot-for-health-agent, heartbeat-watch, n8n-incident-fanin, n8n-pilot-dispatch, n8n-research-intake-consumer, research-insight-extractor |
| S1E0U0 | n8n owns the schedule, no live RUN_DONE in window | 19 | aegis-social-sentiment, aegis-transcript-discovery, agent-outcome-linker, agent-outcome-scorer, build-symbol-profiles-at-0-19, commitment-outcome-sweep, daily-incubator-refresh, etf-analyst-enrich, etf-performance-enrich, feedback-loop-processor, hermes-social-sentiment, instrument-belief-writer, momentum-cache-reconcile, momentum-lifecycle-monitor, pattern-extractor, sec-data-ingest, update-agent-performance, watchlist-enrichment-sweep, weekly-incubator-builder |
| S0E1U1 | ran live with useful output, but the cron copy still runs / is not retired | 2 | materialize-watchlist-strategy-cards, sync-social-to-intelligence |
| S0E0U0 | relay-live only: no ownership evidence, no live run | 10 | classify-instruments, finviz-enrichment, finviz-sector-research, hermes-discovery-scorecard, hermes-learning-config-governor, hermes-learning-outcome-grader, hermes-learning-outcome-learning, hermes-learning-tag-engine, maturity-remeasure, opening-intelligence-render |


**Migrated (proven: S+E+U)** (17): catalyst-graph, catalyst-symbol-impact, document-mentions-backfill, finviz-proactive-research, finviz-screener-runner, hermes-analyst-signal-discovery, hermes-governance-api, hermes-momentum-catalyst-scalp, hermes-news-bridge, identity-sweep-stage0, incubator-rolloff-engine, journal-tilt-morning-hook, material-change-detector-stage1, proposal-backtest-engine, record-decision-outcome, source-attribution-monitor, wire-advisory-lessons


**n8n-native** (0): —


**PARALLEL — cron + n8n live both firing** (6): finviz-enrichment, finviz-sector-research, hermes-discovery-scorecard, materialize-watchlist-strategy-cards, opening-intelligence-render, sync-social-to-intelligence


**LIVE_LISTED_IDLE — relay-live, cron line active, 0 live n8n runs in window** (2): classify-instruments, maturity-remeasure


**n8n primary but UNPROVEN** (29):

| lane_id | measure_combo | unproven_reason | sched_evidence | n8n_cutover_tags | wrapper_scheduled_skips | wrapper_offschedule_skips | live_run_done | live_useful_or_empty | refusals |
|---|---|---|---|---|---|---|---|---|---|
| aegis-social-sentiment | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 1 | 0 | 0 | 0 |
| aegis-transcript-discovery | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 1 | 0 | 0 | 0 |
| agent-outcome-linker | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 1 | 0 | 0 | 0 |
| agent-outcome-scorer | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 1 | 0 | 0 | 0 |
| build-symbol-profiles-at-0-19 | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 1 | 0 | 0 | 0 |
| commitment-outcome-sweep | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 2 | 0 | 0 | 0 |
| crontab-snapshot-for-health-agent | S1E1U0 | live RUN_DONE but no useful output verdict (produced / empty_allowed) | cron_retired_tag | N8N_CUTOVER@2026-10-09:L1009 | 0 | 0 | 120 | 0 | 0 |
| daily-incubator-refresh | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 1 | 0 | 0 | 0 |
| etf-analyst-enrich | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 1 | 0 | 0 | 0 |
| etf-performance-enrich | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 1 | 0 | 0 | 0 |
| feedback-loop-processor | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 1 | 0 | 0 | 0 |
| heartbeat-watch | S1E1U0 | live RUN_DONE but no useful output verdict (produced / empty_allowed) | n8n_native_row |  | 0 | 0 | 479 | 0 | 49 |
| hermes-learning-config-governor | S0E0U0 | no scheduler-ownership evidence (no n8n-cutover / N8N-ONLY tag and no wrapped cron line that stood down); no live RUN_DONE in window |  |  | 0 | 0 | 0 | 0 | 0 |
| hermes-learning-outcome-grader | S0E0U0 | no scheduler-ownership evidence (no n8n-cutover / N8N-ONLY tag and no wrapped cron line that stood down); no live RUN_DONE in window |  |  | 0 | 0 | 0 | 0 | 1 |
| hermes-learning-outcome-learning | S0E0U0 | no scheduler-ownership evidence (no n8n-cutover / N8N-ONLY tag and no wrapped cron line that stood down); no live RUN_DONE in window |  |  | 0 | 0 | 0 | 0 | 0 |
| hermes-learning-tag-engine | S0E0U0 | no scheduler-ownership evidence (no n8n-cutover / N8N-ONLY tag and no wrapped cron line that stood down); no live RUN_DONE in window |  |  | 0 | 0 | 0 | 0 | 0 |
| hermes-social-sentiment | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 2 | 0 | 0 | 0 |
| instrument-belief-writer | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 2 | 0 | 0 | 0 |
| momentum-cache-reconcile | S1E0U0 | no live RUN_DONE in window | n8n_native_row |  | 0 | 0 | 0 | 0 | 0 |
| momentum-lifecycle-monitor | S1E0U0 | no live RUN_DONE in window | n8n_native_row |  | 0 | 0 | 0 | 0 | 0 |
| n8n-incident-fanin | S1E1U0 | live RUN_DONE but no useful output verdict (produced / empty_allowed) | cron_retired_tag | N8N_CUTOVER@2026-10-09:L1041 | 0 | 0 | 479 | 0 | 0 |
| n8n-pilot-dispatch | S1E1U0 | live RUN_DONE but no useful output verdict (produced / empty_allowed) | cron_retired_tag | N8N_CUTOVER@2026-10-09:L1040 | 0 | 0 | 160 | 0 | 0 |
| n8n-research-intake-consumer | S1E1U0 | live RUN_DONE but no useful output verdict (produced / empty_allowed) | cron_retired_tag | N8N_CUTOVER@2026-10-09:L1061 | 0 | 0 | 160 | 0 | 0 |
| pattern-extractor | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 1 | 0 | 0 | 0 |
| research-insight-extractor | S1E1U0 | live RUN_DONE but no useful output verdict (produced / empty_allowed) | cron_retired_tag | N8N_CUTOVER@2026-10-13:L420 | 0 | 0 | 5 | 0 | 0 |
| sec-data-ingest | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 1 | 0 | 0 | 0 |
| update-agent-performance | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 1 | 0 | 0 | 0 |
| watchlist-enrichment-sweep | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 1 | 1 | 0 | 0 | 0 |
| weekly-incubator-builder | S1E0U0 | no live RUN_DONE in window | cron_wrapped_skipping |  | 0 | 1 | 0 | 0 | 0 |


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

WS2 families fully n8n-owned: **0 of 53** (none). Families with some n8n but not all (top 15 by lanes):

| family_id | lanes | status_counts | cron_or_parallel |
|---|---|---|---|
| F36 | 41 | {'CRON_PRIMARY': 21, 'LIVE_LISTED_IDLE': 1, 'OTHER': 1, 'RETAINED_SYSTEMD': 18} | 22 |
| F39 | 30 | {'CRON_PRIMARY': 20, 'MIGRATED_PROVEN': 2, 'N8N_PRIMARY_UNPROVEN': 4, 'RETAINED_SYSTEMD': 4} | 20 |
| F50 | 22 | {'CRON_PRIMARY': 11, 'MIGRATED_PROVEN': 4, 'N8N_PRIMARY_UNPROVEN': 6, 'PARALLEL': 1} | 12 |
| F44 | 21 | {'CRON_PRIMARY': 11, 'MIGRATED_PROVEN': 5, 'N8N_PRIMARY_UNPROVEN': 4, 'PARALLEL': 1} | 12 |
| F51 | 16 | {'CRON_PRIMARY': 9, 'N8N_PRIMARY_UNPROVEN': 1, 'PARALLEL': 1, 'RETAINED_SYSTEMD': 5} | 10 |
| F43 | 11 | {'CRON_PRIMARY': 7, 'MIGRATED_PROVEN': 2, 'PARALLEL': 2} | 9 |
| F45 | 11 | {'CRON_PRIMARY': 7, 'MIGRATED_PROVEN': 2, 'N8N_PRIMARY_UNPROVEN': 2} | 7 |
| F47 | 8 | {'CRON_PRIMARY': 6, 'MIGRATED_PROVEN': 2} | 6 |
| F42 | 7 | {'CRON_PRIMARY': 3, 'LIVE_LISTED_IDLE': 1, 'N8N_PRIMARY_UNPROVEN': 3} | 4 |
| F35 | 4 | {'CRON_PRIMARY': 3, 'PARALLEL': 1} | 4 |
| F49 | 4 | {'N8N_PRIMARY_UNPROVEN': 4} | 0 |
| F52 | 2 | {'CRON_PRIMARY': 1, 'N8N_PRIMARY_UNPROVEN': 1} | 1 |


Fabric processes:

| process | workflow_id | mode | fully_n8n_owned | why_not |
|---|---|---|---|---|
| hermes-learning | tradeai-fabric-hermes-learning | live | False | cron stage runner still active: hermes-learning-pipeline-learn, hermes-learning-pipeline-tune; step(s) without a live run in window: outcome_grader, tag_engine, outcome_feedback_agent, outcome_learning, config_governor, autonomous_self_tune |


## 4. Run outcomes (window)

| measure | n |
|---|---|
| receipts_in_window | 4474 |
| lanes_with_receipts | 82 |
| lanes_with_live_receipts | 35 |
| live_runs | 1643 |
| dry_runs | 2831 |
| useful_live_output | 143 |
| verified_empty | 33 |
| unverified_ok | 1420 |
| failures | 2 |
| lock_skips | 45 |
| refusals | 534 |
| ambiguous_effects | 1 |
| live_worker_s | 15581.0 |
| dry_worker_s | 2983.7 |


Refusals by reason: {'momentum_monitor_admission_unproven': 479, 'run_idempotency_conflict': 34, 'run_slot_not_due': 15, 'relay_lane_not_allowlisted': 4, 'relay_live_not_enabled': 2}

Effect claims by state: {'DONE': 85, 'RELEASED': 27, 'FAILED': 1, 'UNKNOWN': 1}


Ledger cross-check (runs table, same window): [{'state': 'RUN_DONE', 'mode': 'dry_run', 'n': 2831}, {'state': 'RUN_DONE', 'mode': 'live', 'n': 1596}, {'state': 'RUN_FAILED', 'mode': 'live', 'n': 1}, {'state': 'RUN_SKIPPED_LOCK', 'mode': 'live', 'n': 45}, {'state': 'RUN_TIMEOUT', 'mode': 'live', 'n': 1}]


Per lane with live runs:

| lane_id | status | live_runs | useful_live_output | verified_empty | unverified_ok | failures | lock_skips | refusals | ambiguous_effects | live_worker_s | dry_runs |
|---|---|---|---|---|---|---|---|---|---|---|---|
| heartbeat-watch | N8N_PRIMARY_UNPROVEN | 479 | 0 | 0 | 479 | 0 | 0 | 49 | 0 | 85.5 | 0 |
| n8n-incident-fanin | N8N_PRIMARY_UNPROVEN | 479 | 0 | 0 | 479 | 0 | 0 | 0 | 0 | 11517.1 | 0 |
| n8n-pilot-dispatch | N8N_PRIMARY_UNPROVEN | 160 | 0 | 0 | 160 | 0 | 0 | 0 | 0 | 142.5 | 0 |
| n8n-research-intake-consumer | N8N_PRIMARY_UNPROVEN | 160 | 0 | 0 | 160 | 0 | 0 | 0 | 0 | 70.5 | 0 |
| crontab-snapshot-for-health-agent | N8N_PRIMARY_UNPROVEN | 120 | 0 | 0 | 120 | 0 | 0 | 0 | 0 | 35.8 | 0 |
| hermes-governance-api | MIGRATED_PROVEN | 61 | 60 | 0 | 1 | 0 | 0 | 0 | 0 | 155.5 | 90 |
| identity-sweep-stage0 | MIGRATED_PROVEN | 38 | 23 | 9 | 6 | 0 | 0 | 0 | 0 | 60.0 | 43 |
| material-change-detector-stage1 | MIGRATED_PROVEN | 38 | 16 | 16 | 6 | 0 | 0 | 0 | 0 | 30.2 | 43 |
| materialize-watchlist-strategy-cards | PARALLEL | 20 | 6 | 0 | 0 | 0 | 14 | 0 | 0 | 45.6 | 22 |
| document-mentions-backfill | MIGRATED_PROVEN | 19 | 14 | 2 | 3 | 0 | 0 | 0 | 0 | 813.3 | 21 |
| watchlist-enrichment-sweep | N8N_PRIMARY_UNPROVEN | 14 | 0 | 0 | 0 | 1 | 13 | 0 | 1 | 900.6 | 16 |
| hermes-momentum-catalyst-scalp | MIGRATED_PROVEN | 10 | 5 | 0 | 0 | 0 | 5 | 0 | 0 | 273.5 | 10 |
| hermes-analyst-signal-discovery | MIGRATED_PROVEN | 7 | 6 | 0 | 1 | 0 | 0 | 0 | 0 | 6.4 | 7 |
| research-insight-extractor | N8N_PRIMARY_UNPROVEN | 5 | 0 | 0 | 5 | 0 | 0 | 0 | 0 | 24.9 | 0 |
| finviz-proactive-research | MIGRATED_PROVEN | 4 | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 56.6 | 4 |
| proposal-backtest-engine | MIGRATED_PROVEN | 3 | 2 | 0 | 0 | 0 | 1 | 0 | 0 | 1.2 | 3 |
| wire-advisory-lessons | MIGRATED_PROVEN | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 4.3 | 1 |
| aegis-social-sentiment | N8N_PRIMARY_UNPROVEN | 2 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0.2 | 2 |
| catalyst-symbol-impact | MIGRATED_PROVEN | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 1.1 | 3 |
| hermes-news-bridge | MIGRATED_PROVEN | 2 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0.5 | 3 |
| hermes-social-sentiment | N8N_PRIMARY_UNPROVEN | 2 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0.0 | 2 |
| sync-social-to-intelligence | PARALLEL | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 1.0 | 2 |
| aegis-transcript-discovery | N8N_PRIMARY_UNPROVEN | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.0 | 1 |
| agent-outcome-linker | N8N_PRIMARY_UNPROVEN | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.0 | 1 |
| catalyst-graph | MIGRATED_PROVEN | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1.0 | 1 |
| daily-incubator-refresh | N8N_PRIMARY_UNPROVEN | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 251.3 | 1 |
| finviz-enrichment | PARALLEL | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.0 | 1 |
| finviz-screener-runner | MIGRATED_PROVEN | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1100.8 | 1 |
| finviz-sector-research | PARALLEL | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.0 | 2 |
| hermes-discovery-scorecard | PARALLEL | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.0 | 0 |
| incubator-rolloff-engine | MIGRATED_PROVEN | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0.8 | 0 |
| journal-tilt-morning-hook | MIGRATED_PROVEN | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0.3 | 1 |
| opening-intelligence-render | PARALLEL | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.0 | 0 |
| record-decision-outcome | MIGRATED_PROVEN | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0.2 | 1 |
| source-attribution-monitor | MIGRATED_PROVEN | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0.3 | 3 |


## 5. Incidents (window)

| measure | n |
|---|---|
| distinct episodes (lane × failure class) | 89 |
| events | 1949 |
| duplicate events | 1860 |
| episodes by recovery verdict | {'UNRESOLVED': 69, 'VERIFIED_RECOVERED': 20} |
| episodes by class | {'UNGOVERNED': 16, 'NO_OUTPUT': 64, 'RUN_FAILED': 3, 'run_receipt_failure': 2, 'SILENT': 1, 'STALE_OUTPUT': 2, 'RUN_TIMEOUT': 1} |
| remediation rows (REQUESTED / shadow — NOT heals) | {'supervisor_recoveries_in_window': 4003, 'executed_true': 0, 'modes': {'shadow': 4003}, 'diagnoses_with_remediation_run_id': 0} |
| diagnoses by outcome | {'no_diagnosis': 1808, 'diagnosed': 39} |
| failure-diagnosis state | {'diagnosed_in_window': 39, 'diagnosed_by_action': {'suggest_only': 39}, 'pending': 0, 'lane_last_remediation': 0} |
| unreleased dead letters in window | 2 |


Verified recoveries (20):

| lane_id | failure_class | events | last_at | recovery_evidence |
|---|---|---|---|---|
| build-hermes-canonical-status | NO_OUTPUT | 82 | 2026-10-16T12:18:02+00:00 | output signal now 2026-10-16T18:15:07+00:00 > last breach detection 2026-10-16T10:30:16+00:00 |
| cio-entry-state | NO_OUTPUT | 1 | 2026-10-15T14:25:33+00:00 | output signal now 2026-10-16T19:50:02+00:00 > last breach detection 2026-10-15T14:25:33+00:00 |
| directive-keyword-enhancer | NO_OUTPUT | 2 | 2026-10-16T10:40:18+00:00 | output signal now 2026-10-16T19:25:01+00:00 > last breach detection 2026-10-16T10:40:18+00:00 |
| external-market-data-ingest | NO_OUTPUT | 2 | 2026-10-16T11:31:45+00:00 | output signal now 2026-10-16T19:45:01+00:00 > last breach detection 2026-10-16T11:31:45+00:00 |
| finviz-screener-runner | NO_OUTPUT | 23 | 2026-10-16T19:48:01+00:00 | output signal now 2026-10-16T15:55:12+00:00 > last breach detection 2026-10-16T14:15:14+00:00 |
| goal-gate-bridge | NO_OUTPUT | 1 | 2026-10-15T20:32:04+00:00 | output signal now 2026-10-16T19:35:03+00:00 > last breach detection 2026-10-15T20:32:04+00:00 |
| hermes-coordinator | NO_OUTPUT | 2 | 2026-10-16T10:16:14+00:00 | output signal now 2026-10-16T19:48:25+00:00 > last breach detection 2026-10-16T10:16:14+00:00 |
| hermes-directive-discovery | NO_OUTPUT | 2 | 2026-10-16T10:16:14+00:00 | output signal now 2026-10-16T19:31:18+00:00 > last breach detection 2026-10-16T10:16:14+00:00 |
| hermes-score-alerts | NO_OUTPUT | 2 | 2026-10-16T10:30:16+00:00 | output signal now 2026-10-16T19:45:05+00:00 > last breach detection 2026-10-16T10:30:16+00:00 |
| hermes-subject-enhance-dispatch | NO_OUTPUT | 2 | 2026-10-16T13:16:24+00:00 | output signal now 2026-10-16T19:40:02+00:00 > last breach detection 2026-10-16T13:16:24+00:00 |
| incubator-rolloff-engine | NO_OUTPUT | 2 | 2026-10-16T00:00:35+00:00 | output signal now 2026-10-16T14:00:23+00:00 > last breach detection 2026-10-16T00:00:35+00:00 |
| indicator-engine | NO_OUTPUT | 1 | 2026-10-15T18:38:29+00:00 | output signal now 2026-10-16T12:00:14+00:00 > last breach detection 2026-10-15T18:38:29+00:00 |
| premarket-data-pipeline | NO_OUTPUT | 1 | 2026-10-16T10:00:03+00:00 | output signal now 2026-10-16T10:12:15+00:00 > last breach detection 2026-10-16T10:00:03+00:00 |
| proposal-llm-review-worker | NO_OUTPUT | 2 | 2026-10-16T10:16:14+00:00 | output signal now 2026-10-16T19:30:01+00:00 > last breach detection 2026-10-16T10:16:14+00:00 |
| rag-indexer | NO_OUTPUT | 2 | 2026-10-16T12:17:03+00:00 | output signal now 2026-10-16T16:02:01+00:00 > last breach detection 2026-10-16T12:17:03+00:00 |
| run-research-intelligence-overnight | NO_OUTPUT | 2 | 2026-10-16T00:00:35+00:00 | output signal now 2026-10-16T05:06:53+00:00 > last breach detection 2026-10-16T00:00:35+00:00 |
| send-telegram-proposal-alert | NO_OUTPUT | 2 | 2026-10-16T13:16:24+00:00 | output signal now 2026-10-16T19:50:06+00:00 > last breach detection 2026-10-16T13:16:24+00:00 |
| source-litmus-vs-yahoo | NO_OUTPUT | 2 | 2026-10-16T00:00:35+00:00 | output signal now 2026-10-16T11:46:20+00:00 > last breach detection 2026-10-16T00:00:35+00:00 |
| topic-ingestion | NO_OUTPUT | 1 | 2026-10-16T00:00:35+00:00 | output signal now 2026-10-16T05:06:52+00:00 > last breach detection 2026-10-16T00:00:35+00:00 |
| watch-directives-service | NO_OUTPUT | 2 | 2026-10-16T13:16:24+00:00 | output signal now 2026-10-16T19:49:33+00:00 > last breach detection 2026-10-16T13:16:24+00:00 |


Unresolved episodes are listed in episodes.csv.


## 6. Notifications (today, ET)

| stage | counts |
|---|---|
| n8n comms intents (coordination ledger) | {'DIGEST/QUEUED': 1} |
| router decisions (notification_intent_receipts) | {'DELIVER': 72, 'HELD_QUIET_HOURS': 9, 'DIGEST': 140, 'DEDUPED': 2} |
| communication_events OUTBOUND | 391 |
| scheduler × delivery status | {'UNKNOWN/LEGACY_DELIVERED': 35, 'UNKNOWN/RESERVED': 6, 'UNKNOWN/SENT': 70, 'UNKNOWN/SUPPRESSED': 162, 'cron/LEGACY_DELIVERED': 14, 'cron/SENT': 5, 'cron/SUPPRESSED': 82, 'systemd/LEGACY_DELIVERED': 1, 'systemd/SENT': 1, 'systemd/SUPPRESSED': 15} |
| attribution | {'attributed': 118, 'UNKNOWN': 273} |
| telegram idempotency keys today (by prefix) | {} |
| telegram daily send budget today | UNKNOWN |


Attribution by source: {'UNKNOWN': 273, 'cron:send-watchpool-maturity-alerts': 50, 'systemd:claude-escalation-handler': 12, 'cron:claude-escalation-handler': 11, 'cron:hermes-score-alerts': 7, 'cron:run-trade-ai-scalp-live': 7, 'cron:process-reaper': 6, 'cron:incident-notifier': 6, 'cron:cio-entry-state-runner': 6, 'cron:send-advice-digest': 3, 'systemd:system-health-agent': 2, 'cron:stop-health-check': 2, 'cron:scalp-shadow-logger': 1, 'cron:inference-layer-engine': 1, 'systemd:autonomy-watchdog': 1, 'cron:rotation-autopilot': 1, 'systemd:research-lane-health': 1, 'systemd:check-data-source-health': 1}

No shared key joins a router receipt to a communication_events row (router rows carry producer + decision, events carry one generic chokepoint producer name); the chain is reported as per-stage counts. Per-message intent->delivery linkage is UNKNOWN except where the provenance footer names the lane.


## 7. Effect protection (qualified by ledger health and wrapper policy)

| protection_mode | keyed lanes |
|---|---|
| FAIL_CLOSED | 0 |
| LEDGER_HEALTHY_ONLY | 22 |
| NO_CRON_COPY | 13 |
| UNPROTECTED_CRON_UNWRAPPED | 0 |
| NOT_HANDED_OVER | 34 |


**Protected fail-closed** (0): —


**Protected only while the ledger is healthy** (22): aegis-social-sentiment, aegis-transcript-discovery, agent-outcome-linker, agent-outcome-scorer, build-symbol-profiles-at-0-19, commitment-outcome-sweep, daily-incubator-refresh, etf-analyst-enrich, etf-performance-enrich, feedback-loop-processor, finviz-proactive-research, finviz-screener-runner, hermes-social-sentiment, incubator-rolloff-engine, instrument-belief-writer, journal-tilt-morning-hook, pattern-extractor, proposal-backtest-engine, sec-data-ingest, update-agent-performance, watchlist-enrichment-sweep, weekly-incubator-builder


Manifest vs ledger owner: {'NEITHER': 33, 'MANIFEST_MISSING': 36}. Disagreements (reported, never reconciled): none.


Cron copy stood down (skipped_effect / skipped_ownership_unknown in window): 22 lanes: aegis-social-sentiment, aegis-transcript-discovery, agent-outcome-linker, agent-outcome-scorer, build-symbol-profiles-at-0-19, commitment-outcome-sweep, daily-incubator-refresh, etf-analyst-enrich, etf-performance-enrich, feedback-loop-processor, finviz-proactive-research, finviz-screener-runner, hermes-social-sentiment, incubator-rolloff-engine, instrument-belief-writer, journal-tilt-morning-hook, pattern-extractor, proposal-backtest-engine, sec-data-ingest, update-agent-performance, watchlist-enrichment-sweep, weekly-incubator-builder


Wrapper RAN the command (owner not n8n, or ledger unreachable): 4 lanes: hermes-pipeline-health, hermes-scope-governor, hermes-score-event-feeder, resolve-due-checkpoints


Claim-level view (unchanged since #1827): {'STAGED': 33, 'ARMED_NOT_YET_EXERCISED': 17, 'SINGLE_OWNER_CLAIMING': 14, 'OWNER_ROW_ONLY': 5}. SINGLE_OWNER_CLAIMING = owner n8n, the executor claimed DONE keys in the window, every active cron line wrapped; "cannot run twice" holds only for runs through the n8n executor or the wrapper (a manual run outside both is not fenced). late_write_fenced is false for every key (no lane calls assert_fence yet).

| lane_id | owner | manifest_owner | manifest_ledger | active_cron_lines | active_cron_lines_cron_wrapped | skipped_effect | skipped_ownership_unknown | wrapper_ran | claims_done | claims_ambiguous | protection_mode | protection_mode_why |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aegis-social-sentiment | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| aegis-transcript-discovery | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| agent-outcome-linker | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| agent-outcome-scorer | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| build-symbol-profiles-at-0-19 | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| catalyst-symbol-impact | n8n |  | MANIFEST_MISSING | 0 | 0 | 0 | 0 | 0 | 2 | 0 | NO_CRON_COPY | no active cron line fires the lane |
| commitment-outcome-sweep | n8n |  | MANIFEST_MISSING | 1 | 1 | 2 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| daily-incubator-refresh | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| document-mentions-backfill | n8n |  | MANIFEST_MISSING | 0 | 0 | 0 | 0 | 0 | 19 | 0 | NO_CRON_COPY | no active cron line fires the lane |
| etf-analyst-enrich | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| etf-performance-enrich | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| feedback-loop-processor | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| finviz-proactive-research | n8n |  | MANIFEST_MISSING | 1 | 1 | 2 | 0 | 0 | 2 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| finviz-screener-runner | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 1 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| hermes-analyst-signal-discovery | n8n |  | MANIFEST_MISSING | 0 | 0 | 0 | 0 | 0 | 7 | 0 | NO_CRON_COPY | no active cron line fires the lane |
| hermes-learning-config-governor | n8n |  | MANIFEST_MISSING | 0 | 0 | 0 | 0 | 0 | 0 | 0 | NO_CRON_COPY | no active cron line fires the lane |
| hermes-learning-outcome-feedback-agent | cron |  | MANIFEST_MISSING | 0 | 0 | 0 | 0 | 0 | 0 | 0 | NOT_HANDED_OVER | ledger owner cron, manifest absent |
| hermes-learning-outcome-grader | n8n |  | MANIFEST_MISSING | 0 | 0 | 0 | 0 | 0 | 0 | 0 | NO_CRON_COPY | no active cron line fires the lane |
| hermes-learning-outcome-learning | n8n |  | MANIFEST_MISSING | 0 | 0 | 0 | 0 | 0 | 0 | 0 | NO_CRON_COPY | no active cron line fires the lane |
| hermes-learning-tag-engine | n8n |  | MANIFEST_MISSING | 0 | 0 | 0 | 0 | 0 | 0 | 0 | NO_CRON_COPY | no active cron line fires the lane |
| hermes-momentum-catalyst-scalp | n8n |  | MANIFEST_MISSING | 0 | 0 | 0 | 0 | 0 | 5 | 0 | NO_CRON_COPY | no active cron line fires the lane |
| hermes-news-bridge | n8n |  | MANIFEST_MISSING | 0 | 0 | 0 | 0 | 0 | 2 | 0 | NO_CRON_COPY | no active cron line fires the lane |
| hermes-social-sentiment | n8n |  | MANIFEST_MISSING | 1 | 1 | 2 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| incubator-rolloff-engine | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 1 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| instrument-belief-writer | n8n |  | MANIFEST_MISSING | 1 | 1 | 2 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| journal-tilt-morning-hook | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 1 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| material-change-detector-stage1 | n8n |  | MANIFEST_MISSING | 0 | 0 | 0 | 0 | 0 | 38 | 0 | NO_CRON_COPY | no active cron line fires the lane |
| pattern-extractor | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| proposal-backtest-engine | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 2 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| record-decision-outcome | n8n |  | MANIFEST_MISSING | 0 | 0 | 0 | 0 | 0 | 1 | 0 | NO_CRON_COPY | no active cron line fires the lane |
| sec-data-ingest | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| source-attribution-monitor | n8n |  | MANIFEST_MISSING | 0 | 0 | 0 | 0 | 0 | 1 | 0 | NO_CRON_COPY | no active cron line fires the lane |
| update-agent-performance | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| watchlist-enrichment-sweep | n8n |  | MANIFEST_MISSING | 1 | 1 | 2 | 0 | 0 | 0 | 1 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| weekly-incubator-builder | n8n |  | MANIFEST_MISSING | 1 | 1 | 1 | 0 | 0 | 0 | 0 | LEDGER_HEALTHY_ONLY | served wrapper fails OPEN on an unreadable ledger; handover manifest does not name n8n |
| wire-advisory-lessons | n8n |  | MANIFEST_MISSING | 0 | 0 | 0 | 0 | 0 | 3 | 0 | NO_CRON_COPY | no active cron line fires the lane |


### Event-driven chain (config/lane_registry.json dispatch.triggers)

4 declared triggers on 3 lanes; by state {'SHADOW_FIRING': 3, 'LIVE_ARMED_NOT_FIRED': 1}; with a clock fallback still firing: 4. Whether the tradeai-event-router workflow is active in n8n is not read here (no n8n API call); the e: receipts are the evidence that a trigger fired. The five registry scheduler.kind=event rows (openclaw reminders, cio-situation-detector) are emitted outside n8n and are not part of this chain.

| lane_id | trigger_source | upstream | dispatch_mode | trigger_state | e_live_receipts | e_dry_receipts | last_e_receipt_at | upstream_live_useful | clock_fallback |
|---|---|---|---|---|---|---|---|---|---|
| news-to-catalyst | broker_as_of | catalyst_news | dry_run | SHADOW_FIRING | 0 | 12 | 2026-10-16T16:33:01+00:00 |  | dispatch.cron 45 6,12,18 * * *; crontab L408 (wrapped) |
| news-to-catalyst | run_done | hermes-news-bridge | dry_run | SHADOW_FIRING | 0 | 12 | 2026-10-16T16:33:01+00:00 | 2 | dispatch.cron 45 6,12,18 * * *; crontab L408 (wrapped) |
| research-insight-extractor | run_done | news-to-catalyst | live | LIVE_ARMED_NOT_FIRED | 0 | 0 | None | 0 | dispatch.cron 50 6,12,18 * * * |
| signal-fusion-active | broker_as_of | scalp_list | dry_run | SHADOW_FIRING | 0 | 39 | 2026-10-16T19:25:02+00:00 |  | dispatch.cron */30 4-16 * * 1-5; crontab L413 |


## 8. Next cohorts and burn-down

| cohort | lanes | owner |
|---|---|---|
| C1_parallel_retire_cron_copy | 6 | operator (crontab edit under config-write grant; cutover packet by Agent A) |
| C2_live_listed_unproven | 31 | Agent A (relay-live but no live RUN_DONE in window: find why; fix or delist) |
| C3_shadow_proven_ready_for_live | 37 | Agent A (canary packet + effect key) -> operator (relay live list + crontab) |
| C4a_allowlisted_no_shadow_run | 8 | Agent A (dispatch block / shadow wave so a dry run exists) |
| C4b_not_onboarded | 223 | Agent A (allowlist + health contract PR per lane) |
| C5_p1_last | 14 | operator (policy p1_last: last cohort, cron kept one trading day after proof) |
| C6_operator_hold | 4 | operator (holds in config/lane_cutover_policy.json) |
| C7_retire_pending | 1 | operator (disposition RETIRE but the cron line is still active: retire packet) |


Remaining (excl. holds): **320** lanes. Observed tagged migrations by date: {'2026-10-09': 4, '2026-10-13': 1, '2026-10-16': 12}. Rate 5.67 lanes/trading day → projected completion **2027-01-04**.

Assumptions:

- rate = mean of n8n-cutover/N8N-ONLY tagged cron retirements over the last 3 dates that had any (a calendar date with zero retirements is not in the denominator), so the rate is optimistic
- one migrating lane needs: allowlist + dry run + live canary + effect key/owner + cron retirement
- trading days only (5 of 7); holds, F07 and registry_systemd are excluded (retained by directive)
- no new lanes are added; open PRs in the section 9 table merge and deploy without rework

Open PRs carrying blockers: see section 9 (state OPEN).


## 9. PRs #1808–#1829: merged / deployed / proven

| pr | state | merged | deployed | proven | evidence | title |
|---|---|---|---|---|---|---|
| 1808 | MERGED | True | True | PARTIAL | 3/8 lanes proven; missing: agent-outcome-linker, classify-instruments, etf-analyst-enrich, etf-performance-enrich, feedback-loop-processor | n8n CW1 batch 1: 8 lanes write produced_count + opt into output verdict |
| 1809 | MERGED | True | True | PARTIAL | 6/9 lanes proven; missing: finviz-enrichment, finviz-enrichment-scalp-hot, finviz-sector-research | n8n CW1 batch 2: finviz x4 + hermes x4 write produced_count + opt into output verdict |
| 1810 | MERGED | True | True | PARTIAL | 6/8 lanes proven; missing: sec-data-ingest, update-agent-performance | n8n CW1 batch 3: 8 lanes write produced_count + opt into output verdict |
| 1811 | MERGED | True | True | UNPROVEN | 0/8 lanes have a live produced/empty_allowed receipt at a SHA containing the merge | n8n CW1/CW2 batch 4: 8 lanes write produced_count + opt into output verdict |
| 1812 | MERGED | True | True | PARTIAL | 4/9 lanes proven; missing: build-symbol-profiles-at-0-19, hermes-discovery-scorecard, opening-intelligence-render, pattern-extractor, weekly-incubator-builder | n8n CW2/CW3 batch 5: 9 lanes write produced_count + opt into output verdict |
| 1813 | MERGED | True | True | PROVEN | 5/5 lanes have a qualifying live receipt | n8n cutover: 5 CW1 lanes canary -> cutover (cron retired 2026-10-16) |
| 1814 | MERGED | True | True | UNPROVEN | no lane associated with the PR's changes | §23.25 gate alignment: lift cron markers + soft tokens for approved families; 4 holds; P1 last |
| 1815 | MERGED | True | True | UNPROVEN | 0/9 lanes have a live produced/empty_allowed receipt at a SHA containing the merge | hermes-learning cutover PR-2: 4 learn steps live at canary (feedback agent held), same-morning packe |
| 1816 | MERGED | True | True | UNPROVEN | 0/9 lanes have a live produced/empty_allowed receipt at a SHA containing the merge | hermes-learning: one-day live_manual_slots (until 2026-10-16 23:59 ET) + guarded manual fallback |
| 1817 | MERGED | True | True | PARTIAL | 118 outbound rows today carry a footer, 0 name n8n | comms: Telegram provenance footer (n8n/cron lane) + explicit catalyst line on Active Trader alerts |
| 1818 | MERGED | True | True | PARTIAL | 1/8 lanes proven; missing: hermes-learning-config-governor, hermes-learning-outcome-grader, hermes-learning-outcome-learning, hermes-learning-pipeline-learn, hermes-learning-tag-engine, premarket-watcher, social-scalp-scanner | n8n/comms follow-ups: AT catalyst research + persistent store, n8n-today CC tab, premarket dedupe, n |
| 1819 | OPEN | False | False | UNPROVEN | not merged | n8n self-healing: dedupe by signature, deterministic closes, gated live heal, P1-once / P2-digest (+ |
| 1820 | OPEN | False | False | UNPROVEN | not merged | n8n self-healing follow-ups (stacked on #1819): slot-bound live retry, P2 digest, catalogue approval |
| 1821 | OPEN | False | False | UNPROVEN | not merged | assert_fence wave 1 (stacked on #1820): social sentiment x2 + finviz screener runner; market movers  |
| 1822 | MERGED | True | True | UNPROVEN | no lane associated with the PR's changes | n8n: dry-run load measured (0 parallel dry runs on live lanes); pin invariant + read-only report |
| 1823 | MERGED | True | True | UNPROVEN | no lane associated with the PR's changes | ops: cron copy respects effect ownership (effect_claim_cron wrap packet) |
| 1824 | MERGED | True | True | PARTIAL | 1/3 lanes proven; missing: premarket-watcher, social-scalp-scanner | #1818 re-cut on current main: AT research coverage, n8n-today CC page, premarket dedupe |
| 1825 | MERGED | True | True | UNPROVEN | 0/1 lanes have a live produced/empty_allowed receipt at a SHA containing the merge | release windows: 12:00/17:30 ET runner (disarmed) + 2026-10-16 refusal trace |
| 1826 | MERGED | True | True | UNPROVEN | 0/2 lanes have a live produced/empty_allowed receipt at a SHA containing the merge | n8n consolidation cohort 1: verified-result triggers (research news chain), capacity report, shadow  |
| 1827 | MERGED | True | False | UNPROVEN | NOT DEPLOYED (merge commit not in served SHA); no lane associated with the PR's changes | ops: n8n cutover outcomes packet (read-only generator + first packet 2026-10-16T17:24Z) |
| 1828 | OPEN | False | False | UNPROVEN | not merged | self-heal tranche (#1819+#1820+#1821 integrated + defect fixes) |
| 1829 | MERGED | True | False | UNPROVEN | NOT DEPLOYED (merge commit not in served SHA); 0/1 lanes have a live produced/empty_allowed receipt at a SHA containing the merge | ops: nightly cutover controller — enforced state machine (DISARMED) + P1 completed-session fix |


## 10. Changes since docs/ops/measurements/n8n-cutover-20261016T172425Z

Previous packet 2026-10-16T17:24:25+00:00 (served b120849ed) -> this packet (served 290fce36f); crontab changed: True. The definition of MIGRATED_PROVEN changed between the two (now S+E+U; then tag + any live RUN_DONE), and wrapped cron lines that stood down no longer count as PARALLEL.

| status | prev | now | delta |
|---|---|---|---|
| MIGRATED_PROVEN | 17 | 17 | 0 |
| N8N_NATIVE | 1 | 0 | -1 |
| N8N_PRIMARY_UNPROVEN | 6 | 29 | 23 |
| PARALLEL | 17 | 6 | -11 |
| LIVE_LISTED_IDLE | 13 | 2 | -11 |
| CRON_PRIMARY | 283 | 283 | 0 |
| CONSOLIDATED | 60 | 60 | 0 |
| RETIRED | 52 | 52 | 0 |
| HELD | 4 | 4 | 0 |
| RETAINED_F07 | 21 | 21 | 0 |
| RETAINED_SYSTEMD | 125 | 125 | 0 |
| OTHER | 42 | 44 | 2 |


| measure | prev | now |
|---|---|---|
| active_cron_lines | 336 | 336 |
| unique_lanes_with_active_cron | 316 | 316 |
| relay_live_list_size | 52 | 52 |
| live_runs | 1508 | 1643 |
| dry_runs | 2645 | 2831 |
| useful_live_output | 108 | 143 |
| verified_empty | 31 | 33 |
| unverified_ok | 1333 | 1420 |
| failures | 1 | 2 |
| lock_skips | 35 | 45 |
| refusals | 504 | 534 |
| ambiguous_effects | 0 | 1 |


Proven kept (12): catalyst-graph, catalyst-symbol-impact, document-mentions-backfill, hermes-analyst-signal-discovery, hermes-governance-api, hermes-momentum-catalyst-scalp, hermes-news-bridge, identity-sweep-stage0, material-change-detector-stage1, record-decision-outcome, source-attribution-monitor, wire-advisory-lessons


Proven added (5): finviz-proactive-research, finviz-screener-runner, incubator-rolloff-engine, journal-tilt-morning-hook, proposal-backtest-engine


Proven dropped (5):

| lane_id | status | why_now |
|---|---|---|
| crontab-snapshot-for-health-agent | N8N_PRIMARY_UNPROVEN | live RUN_DONE but no useful output verdict (produced / empty_allowed) |
| n8n-incident-fanin | N8N_PRIMARY_UNPROVEN | live RUN_DONE but no useful output verdict (produced / empty_allowed) |
| n8n-pilot-dispatch | N8N_PRIMARY_UNPROVEN | live RUN_DONE but no useful output verdict (produced / empty_allowed) |
| n8n-research-intake-consumer | N8N_PRIMARY_UNPROVEN | live RUN_DONE but no useful output verdict (produced / empty_allowed) |
| research-insight-extractor | N8N_PRIMARY_UNPROVEN | live RUN_DONE but no useful output verdict (produced / empty_allowed) |


All status moves (30):

| lane_id | prev_status | status | why_now |
|---|---|---|---|
| aegis-social-sentiment | PARALLEL | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| aegis-transcript-discovery | PARALLEL | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| agent-outcome-linker | PARALLEL | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| agent-outcome-scorer | LIVE_LISTED_IDLE | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| build-symbol-profiles-at-0-19 | LIVE_LISTED_IDLE | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| commitment-outcome-sweep | LIVE_LISTED_IDLE | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| crontab-snapshot-for-health-agent | MIGRATED_PROVEN | N8N_PRIMARY_UNPROVEN | live RUN_DONE but no useful output verdict (produced / empty_allowed) |
| daily-incubator-refresh | PARALLEL | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| etf-analyst-enrich | LIVE_LISTED_IDLE | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| etf-performance-enrich | LIVE_LISTED_IDLE | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| feedback-loop-processor | LIVE_LISTED_IDLE | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| finviz-proactive-research | PARALLEL | MIGRATED_PROVEN |  |
| finviz-screener-runner | PARALLEL | MIGRATED_PROVEN |  |
| heartbeat-watch | N8N_NATIVE | N8N_PRIMARY_UNPROVEN | live RUN_DONE but no useful output verdict (produced / empty_allowed) |
| hermes-social-sentiment | PARALLEL | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| incubator-rolloff-engine | PARALLEL | MIGRATED_PROVEN |  |
| instrument-belief-writer | LIVE_LISTED_IDLE | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| journal-tilt-morning-hook | PARALLEL | MIGRATED_PROVEN |  |
| n8n-incident-fanin | MIGRATED_PROVEN | N8N_PRIMARY_UNPROVEN | live RUN_DONE but no useful output verdict (produced / empty_allowed) |
| n8n-pilot-dispatch | MIGRATED_PROVEN | N8N_PRIMARY_UNPROVEN | live RUN_DONE but no useful output verdict (produced / empty_allowed) |
| n8n-research-intake-consumer | MIGRATED_PROVEN | N8N_PRIMARY_UNPROVEN | live RUN_DONE but no useful output verdict (produced / empty_allowed) |
| nightly-cutover-controller | (absent) | OTHER |  |
| pattern-extractor | LIVE_LISTED_IDLE | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| proposal-backtest-engine | PARALLEL | MIGRATED_PROVEN |  |
| release-window | (absent) | OTHER |  |
| research-insight-extractor | MIGRATED_PROVEN | N8N_PRIMARY_UNPROVEN | live RUN_DONE but no useful output verdict (produced / empty_allowed) |
| sec-data-ingest | LIVE_LISTED_IDLE | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| update-agent-performance | LIVE_LISTED_IDLE | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| watchlist-enrichment-sweep | PARALLEL | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |
| weekly-incubator-builder | LIVE_LISTED_IDLE | N8N_PRIMARY_UNPROVEN | no live RUN_DONE in window |


## Not measured / caveats

- (none)
- Lane attribution of a crontab line is a substring match against registry rows; a line no row matches is counted UNMAPPED, never guessed.
- Receipts carry no output verdict until a lane emits produced_count and opts in (output_receipt v2); those live runs are `unverified_ok`, not useful output.

Files: summary.json, lanes.csv, families.csv, retained.csv, episodes.csv, effect_protection.csv, event_chain.csv, prs.csv, notifications.json, burn_down.json.


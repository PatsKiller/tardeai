# 2026-10-23 safe_flock cron outage

The shared lock wrapper rejected the served release layout before starting its
children. The notifier and SIEM bridge used that same wrapper, so their alert
path could fail with the jobs it monitored. This report separates source
integration, observed execution, proposed prevention and live acceptance.

## Evidence and timeline

All times below are America/New_York. GitHub merge times are integration
events; they are not deployment receipts.

| Time | Evidence | Meaning |
| --- | --- | --- |
| Oct 23 11:26:25 | [Batch 8 #2002](https://github.com/PatsKiller/tardeai/pull/2002), merge b42f374357592cdd87f831929beba5ee5eabf6d7 | Source integration. |
| Oct 23 11:26:27 | [#1979](https://github.com/PatsKiller/tardeai/pull/1979), merge 521088d0ad6539abd313e2ef28be23f789a5bd4e | Individual PR merge metadata. The offending source change is d5f51dbef. |
| Oct 23 about 12:06 | Coordinator incident request | Reported release time; this worker did not read the deployment ledger or infer this time from log mtime. |
| Oct 23 12:05:01 | Copied structured wrapper completions, exit 0 | Last observed notifier and paper-sweep execution success before the replay clock. |
| Oct 23 12:06:02 | Same journal | Last observed unified-stop-supervisor and n8n-SIEM-bridge execution success. |
| Oct 23 12:07:22 | Same journal | A Hermes coordinator execution completed after the reported promotion. Already-started children could finish; an immediate stop of every process is not established. |
| Oct 23 12:20 | Offline retrospective evaluation | Would alert for six named execution-success gaps, including stop supervision. No alert was actually sent by this proof. |
| Oct 24 15:35 | a2424b17f source commit | Resolves the trusted release/default log roots physically and accepts the caller's private group; untrusted explicit paths retain rejection. Commit time is not deployment time. |
| Oct 24 16:09:12 | [Batch 21 #2071](https://github.com/PatsKiller/tardeai/pull/2071), merge 8b6cd3be6d9776d3051ea24fbbcfc65248431c45 | Accepted source base for this prevention package. Served-fix identity is NOT_MEASURED by this worker. |

The first refused fire and the exact outage end are NOT_MEASURED. The refusal
text has no timestamp. The coordinator's approximate “30 jobs / two days” is
an incident estimate, not a measured per-job outage duration.

## Measured blast radius

The authorized retained cron capture has SHA256
`b2097df25a62e6824b6e7046d55a3f279b9b058e76b1bcd09c2da89b5a748626`.
It contains 30 active safe_flock invocation lines representing 29 distinct lock
components, and 30 distinct shell paths across the estate. These populations
must not be added together or called 30 independent business processes.

Bounded named-log windows contain the exact refusal text
`log path component is not a real directory`:

| Named log | Matching lines in copied window |
| --- | ---: |
| unified_stop_supervisor |97|
| incident_notifier |336|
| hermes_coordinator |112|
| hermes_event_feeder |336|
| hermes_scope_governor |63|
| portfolio_repricer_intraday |19|
| market_data |19|
| alpaca_live_read_sync |19|
| trade_integrity_audit |19|
| paper_execution |58|
| n8n_siem_bridge |336|
| **Total** |**1,414**|

These are refusal-line counts, not unique run IDs. Each captured window has a
source hash, byte range and stability observation in
[named-log-evidence](../packets/cron-outage-prevention-20261024/named-log-evidence.json).
The post-close repricer log contained no such line in its captured whole-file
window; that is not proof of successful repricing or reconciliation. No broker
code, credentials, orders, positions or provider was inspected or called.

The copied structured journal window contains 9,877 events covering 47 components
from Oct 21 through Oct 24. It has starts/completions/skips and **zero refusal
events**. The preflight returned before the old `log_event` function existed.
Raw commands and account/credential content are excluded from committed evidence.

## Root causes and detection gaps

1. The hardened path preflight examined `CURRENT` and the release's `logs/`
   symlinks as if they were untrusted caller-selected paths. The actual layout
   is `CURRENT -> release`, `release/logs -> persistent-state/logs`, mode775 in
   the caller's private group. Flat checkout tests did not reproduce it.
2. Early refusal preceded durable wrapper journaling. Redirected cron text
   showed the error but supplied no timestamp/run identity.
3. Freshness monitors could see an opened/updated log as activity. A file mtime
   cannot prove a successful execution, a business output or a consumer read.
4. The notifier shared the failed wrapper. A monitor cannot rely solely on the
   failure domain it is supposed to diagnose. The coordinator reports that the
   stop-health check remained OK; this worker did not independently inspect its
   broker/stop subsystem and does not treat that report as verified stop health.

## Source controls and acceptance boundaries

| Control | Implemented source/proof | Remaining boundary |
| --- | --- | --- |
| Post-promote preflight | Declared safe no-ops run through actual CURRENT/log symlinks; an armed failure enters existing rollback, requests direct host P1; train checks exact SHA/path/config/time receipt | Config remains disabled/pending. 24 captured paths lack safe no-op protocols. Never enable a permanently failing gate or silently exclude those paths. |
| Shared release fixture | `tests/support/real_release_layout.py`; safe_flock and all seven safe generic protocols use CURRENT and persistent logs mode775 | Fixture proof is not a host deployment or complete business-entrypoint proof. |
| Independent watchdog | DST-safe declared fire times, explicit completed/receipt success, >= 2 elapsed misses in firing window; separate systemd unit/timer and Health projection; host P1 chokepoint | Unit is source-only/uninstalled. Config disabled/review pending. Unsupported schedules and absent success coverage remain NOT_MEASURED. |
| Wrapper failure events | Early safe_flock refusals append job/reason/run/mode through a path-safe writer; cron_wrapper has lifecycle/preflight telemetry | An unsafe or immutable journal is never repaired or bypassed. Its append failure emits a timestamped sanitized refusal on existing stderr, which the monitor reads from declared cron logs; other producer wrappers require scoped instrumentation. |
| Shared infrastructure PR rule | Base-controlled path list + immutable minimums; title `[shared-infra]`, body `Real-layout proof:`; optional CI workflow and fixture tests | Coordinator reviews separately and excludes mixed batches. No branch-protection change or automatic merge/release. |

Existing safe_flock admission, explicit-path rejection, immutable refusal,
inherited-fd recognition, stable inode, flock and cleanup behavior are preserved.
New journaling is observability only. Preflight/dry-run/lock-skip events cannot
satisfy business-mode execution coverage. A later same-component completed
business execution can resolve the active refusal finding; merely delivering
the alert cannot turn it healthy.

The seven generic protocols are safe_flock, cron_wrapper, effect_claim_cron
(unarmed/no ledger), market_day_gate (true child), llm_priority_guard (clock
only), offpeak (true child), and non_trading_hours_gate (its declared dry run).
All use a minimal environment without inherited secrets/live-state settings.
The full 30-path capture plus nested cron_wrapper appear in the
[inventory](../packets/cron-outage-prevention-20261024/wrapper-inventory.json).
Protected broker/protection launchers are never executed, imported, tested
against or patched by this package.

## Historical proof

The offline CLI uses a copied registry from d5f51dbef and a redacted copied
journal, truncated to observations at or before `2026-10-23T12:20:00-04:00`.
The original captured byte window hash is verified before normalization.
No current mtime, future success or cache rebuild time becomes a historical
observation. Legacy command matching establishes wrapper execution only;
actual business-output and consumer acceptance remain separate.

Result: WOULD_ALERT for incident-notifier, n8n-siem-bridge,
hermes-score-event-feeder, paper-execution-sweep, external-market-data-ingest
and unified-stop-supervisor. These are detected execution-success gaps; this
does not establish that all six originated in this release. The stop lane's
declared `*/3 9-16 * * 1-5` window, calendar gate and last success 12:06:02
produce two missing elapsed opportunities by 12:20 despite its weekend-adjusted
`expected_cadence_hours=64.05`. The count is capped at the last two opportunities,
not a claim that exactly two fires were missed.

Of 465 historical ACTIVE/cadence rows, 226 retain explicit coverage gaps. Missing
timer anchors, unsupported schedules, event/on-demand semantics and absent
success receipts are never silently converted to OK. The 480 current-main
ACTIVE/cadence rows have a different denominator. 27 exact source-pinned wrapper
component bindings are supplied; changed registry match/expression invalidates
that binding rather than guessing a new association.

See [replay summary](../packets/cron-outage-prevention-20261024/historical-replay-summary.json)
and [operator packet](../packets/cron-outage-prevention-20261024/README.md).
The replay returned 1 for the detected critical condition, sent zero messages
and created no monitor state. Live timer, alert-delivery and natural-run
acceptance remain NOT_MEASURED.

Input blindness is a separate `MONITOR_BLINDNESS` incident: an unreadable or missing wrapper journal pages through the same host chokepoint without fabricating a last success or missed-fire count. Restored journal access produces a recovery notification, while lanes lacking successful history remain NOT_MEASURED.

# Jobs and health: execution evidence and incident recovery

Date: 2026-10-24. Owner: W4 monitoring. Design-Task: DSN-20261024-w4-monitoring-P1-T1.
Status: source implementation; runtime installation and delivery are separate acceptance.
Approved references: desks board 16, site audit P1 item 2 and the incident-flood addendum.

`GET /api/v2/jobs-health` is the common read-only execution view for `/ops/jobs`
and the Health, Releases, Ops Controls, Coordination and System Jobs tabs.
The registry declares intent. Matching run receipts and completed wrapper events
prove execution. An enabled cron line, file write time, lock skip, dry run or
preflight cannot establish successful business execution.

The view reads declared artifacts and the coordination SQLite ledger in read-only
mode. It never discovers schedules through subprocesses, runs a producer, changes
the scheduler, sends a notification or migrates the ledger. Results are cached
for 60 seconds, paged at 50 rows by default and capped at 100. Summary counts
cover the full observation before filtering and paging. Missing success coverage
is unknown; the watchdog's two missed opportunities are the missed-run threshold.

## Field trace

| UI element | API/field | Store/key | Writer |
| --- | --- | --- | --- |
| Job name, scheduler, writer state | `/api/v2/jobs-health` `rows[].job/scheduler/state` | `config/lane_registry.json` `display_name` or humanized `lane_id`, `scheduler.kind`, `state` | registry owner W8 |
| Last run | same, `rows[].last_run_at` | coordination ledger `runs.finished_at/started_at/requested_at`; `logs/safe_flock_events.jsonl` explicit event `ts` | host executor / wrapper |
| Last successful run | same, `rows[].last_success_at` | validated matching completion receipt, exit zero and effective live mode; completed business wrapper event; explicit dated completed/exit-zero log marker | host executor / wrapper / declared lane |
| Result and missed count | same, `rows[].result/missed_fires` | registry schedule plus the shared `cron_outage_watchdog.evaluate` over successful receipt timestamps | read-only projection |
| Next due | same, `rows[].next_due_at` | registry cron expression/timezone, shared DST-aware cron parser and market calendar | registry owner; projection computes |
| Real failure cause | same, `rows[].cause` | `runs.receipt_json.stderr_tail`, then diagnostic reason; wrapper refusal reason | host executor / wrapper |
| Summary cards | same, `summary.*` | all projected job rows; never the current page length | read-only projection |
| Independent monitor clock | same, `monitor.*` | `data/runtime/cron_outage_watchdog_latest.json` operational `mode`, `observed_at`, status, notification outcome | independent watchdog systemd lane from #2077 |
| Header Alerts operations source | same, `incidents[]/incident_count` | failed/missed job rows and monitor blindness; independent of incident notifier | projection; existing independent watchdog delivers alerts |
| Job evidence sheet | same, `?job=lane` | identical row from the same observation | read-only projection |
| n8n today failures | `/api/v2/coordination/n8n-today` `failures[].cause` | `data/runtime/n8n_runs/*.json` `stderr_tail/reason` | host executor |
| Workflow-key n8n counts | same, `runs.*` | `n8n-wf-*` receipts, execution timestamp in America/New_York; semantic d/e/g/p keys retain slot-date accounting | host executor |

Execution success and full business recovery have distinct evidence requirements.
Legacy matching completion receipts may prove execution without proving output.
Superseding a live incident requires the existing recovery validator's full
output verdict (`produced` or `empty_allowed`) as well as matching lane, effective
mode, exit code, identity and a later finish time. Future receipts never count.

## Superseded dead letters

`scripts/n8n_dlq.py acknowledge --lane L --superseded-by RUN --by operator
--note REASON --dry-run` previews a typed superseded disposition. Default mode
is also dry run. Applying requires `--apply` and an operator/coordinator host
invocation. The actor argument is a recorded host attestation; it is not a new
web authentication mechanism. There is no web or scheduled acknowledgement path.

The CLI opens the ledger read-only, including apply. It appends fsynced intent
and committed `DeadLetterAcknowledgement@v1` records to the existing
`data/runtime/n8n_dlq_releases.jsonl` audit. It never releases a breaker or marks
a dead slot released, and cannot cause the dispatcher to retry a send/learn lane.
The original terminal record remains intact. Repeating an acknowledgement is
idempotent. An intent without committed evidence closes nothing. A later
re-dead slot must match its new identity/time and is never hidden by an old ack.

Fan-in groups an evidenced wrapper burst by root cause and date. A matching
later success collapses recovered dead letters into a recovery line. Membership,
counts, lanes and successful run IDs remain on the finding. Existing protected
P0/P1 and broker/stop/safety findings retain their protection. This is a
presentation change, not a replay or production acknowledgement.

## Verification and runtime gaps

Pinned fixture tests cover refusal diagnostics, missing success evidence,
dry-run clamps, incorrect output verdicts, future receipts, paused schedules,
weekend windows, paging, no-rearm acknowledgements and grouped recovery.
The browser proof intercepts every API request and uses an isolated Vite server
with no API proxy. Phone proof uses actual taps at 412×915 and 390×844, including
filter, full-screen job detail, browser Back and the bottom primary action.
The evidence sheet is URL-addressable, moves focus, and has 44px controls.

A read-only captured-state projection at 2026-10-24T23:02Z validated 678
registry-backed rows. The independent operational watchdog receipt was absent,
so its result was UNKNOWN. These counts are a dated observation, not shipped
sample values or a runtime health assertion. Evidence lives under the worker's
unique `~/.cache/rtc/codex-w4-monitoring-20261024/` directory. Screenshots live
beside the approved mockups as `impl-16-*.png`.

Seven ops-page frame/embedding changes follow in separate page PRs. A release
check that verifies actual scheduled-job start evidence belongs in its own
shared-infra PR; wrapper `true` preflight alone does not establish that proof.
No worker push, merge, release, cron edit, production DLQ acknowledgement or
notification send is part of this package.

P1 triage remains explicit for the disabled taxonomy timer, missing phone-status
unit, dispatcher Stop And Error executions 82922/83122, investment-costs output
coverage and stale analyst-prospectus output. These are supplied incident leads;
changing their live configuration is not inferred from an old incident count.

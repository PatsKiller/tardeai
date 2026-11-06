# Command Center v3 — complete job coverage inventory

Capture as_of: 2026-11-02T18:45:27.608050Z. Source: served/main job contracts at59ff17d2b, canonical lane registry, persistent receipts/wrapper metadata, generic read-only cron/systemd listings. No scheduled job was triggered.

## Scope and denominators

- 687 registered lane declarations:493ACTIVE,140RETIRED,32NEVER_SCHEDULED,22PAUSED.
- 343 distinct ACTIVE lanes have a declared fire today. This is not the number of elapsed opportunities; unsupported systemd recurrence is absent from that count.
- 5 additional scheduled timers are absent from lane_registry and remain separate runtime-orphan observations.
- Registry has687unique IDs. Currentcron has358entries:355direct declaration matches and3basename+schedule reconciliations; no cron orphan is established.

## Execution coverage independent of healthy/failed

| Evidence coverage | Registered lanes | Share of687 | ACTIVE lanes | Share of493 |
|---|---:|---:|---:|---:|
| Measured | 93 | 13.54% | 93 | 18.86% |
| Partially Measured | 391 | 56.91% | 391 | 79.31% |
| Unmeasured | 1 | 0.15% | 1 | 0.2% |
| Orphaned | 8 | 1.16% | 8 | 1.62% |
| Disabled | 194 | 28.24% | 0 | 0% |

Measured execution requires schedule evidence (or nonrecurring semantics) plus identity-bound durable ledger completion or an unambiguous wrapper completion with an exit code. A failed completion counts as measured, never healthy. Partial means some schedule/attempt/service/success evidence with missing completion dimensions. Output and diagnostics are independent.

ACTIVE evidence dimensions: schedule_evidence_available=484, schedule_declared_measurable=384, schedule_observed_timer_clock=76, execution_attempt_observed=176, durable_completion_observed=93, qualifying_success_observed=144, jobs_reader_success_observed=139, success_signal_discarded_by_jobs_reader=5, output_contract_observed=69, output_contract_satisfied=50.

Seven of9currentfailed jobs have measurable durable completion; two executor-lost cases lack a retained exit/completion outcome.144qualifying success signals are separate from139Jobs-reader successes:5validsuccess signals are discarded by current systemd/schedule paths.69ACTIVE lanes have standard n8n output verdicts;50satisfy those contracts. Other output families are not fully adjudicated.

## Why the page reports217not measured

Frozen native result:343due today,88succeeded,9failed,6missed,4due/pending,201outsidewindow,22paused,140retired,217unknown. These result categories cover687declarations.

217unknown =185ACTIVE +32NEVER_SCHEDULED. The served code omits NEVER_SCHEDULED from inactive-state classification, so32planned-not-installed rows fall through to unknown;2even retain next-due times. The assigned Jobs writer is correcting this with explicit not-scheduled visibility.

185ACTIVEunknown/493ACTIVE=37.53%. Only75are in the343due-today cohort;110are outside it. Dividing215/343 or217/343 mixes populations. ACTIVEunknown classifications: {"missing instrumentation": 170, "orphaned": 8, "undocumented": 7}.

All103ACTIVE systemd lanes appear unknown in this served read model. The census artifact is absent, yet generic hostmetadata exposes76timer clocks. These are visibility gaps, not evidence that103daemons stopped.

## Observed registry/runtime contradictions

8ACTIVE-declared timers are disabled/unloaded. Orphaned here means a registry/runtime contradiction; restore-or-retire is an owner decision. They are not declared dead and were not enabled. Template instances may be intentionally unloaded.
- db-retention-timer — db-retention.timer — CC-OBS-ACTIVE-DISABLED-TIMER:db-retention-timer
- mcporter-token-refresh — mcporter-token-refresh.timer — CC-OBS-ACTIVE-DISABLED-TIMER:mcporter-token-refresh
- systemd-tmpfiles-clean — systemd-tmpfiles-clean.timer — CC-OBS-ACTIVE-DISABLED-TIMER:systemd-tmpfiles-clean
- tradeai-agent-runtime-atlas — tradeai-agent-runtime@atlas.timer — CC-OBS-ACTIVE-DISABLED-TIMER:tradeai-agent-runtime-atlas
- tradeai-agent-runtime-concierge — tradeai-agent-runtime@concierge.timer — CC-OBS-ACTIVE-DISABLED-TIMER:tradeai-agent-runtime-concierge
- tradeai-agent-runtime-hermes — tradeai-agent-runtime@hermes.timer — CC-OBS-ACTIVE-DISABLED-TIMER:tradeai-agent-runtime-hermes
- tradeai-agent-runtime-pulse — tradeai-agent-runtime@pulse.timer — CC-OBS-ACTIVE-DISABLED-TIMER:tradeai-agent-runtime-pulse
- tradeai-iris-taxonomy — tradeai-iris-taxonomy.timer — CC-OBS-ACTIVE-DISABLED-TIMER:tradeai-iris-taxonomy

5scheduled timer references absent from lane_registry:
- tradeai-deploy-on-main.timer — OI-148
- tradeai-incident-watchers.timer — OI-148
- tradeai-n8n-breaker-probe.timer — planned in related draftPR2444
- tradeai-incident-supervisor.timer — OI-148
- tradeai-incident-daily.timer — OI-148

## Expected nonlive operation

56ACTIVE lanes explicitly declare dry-run/shadow/preflight intent; dispatch.mode wins. Native result split: {"due": 2, "missed": 1, "outside_window": 27, "succeeded": 16, "unknown": 10}. Missing LIVE output can be expected; execution evidence still needs measurement.16appear succeeded despite nonlive intent, so mode provenance needs adjudication, not silent arming.

## Existing fixes and remediation ownership

DraftPR2444 already contains four native-n8n stage corrections, the systemd census/read-model integration, expected-nonlive receipt treatment, and several receipt writer/path repairs. Fields distinguish a lane actually changed there from the shared census effect. Do not duplicate it or assume its unmerged code is live.

Every unknown row has proposed remediation ticket keys. ticket_groups.json supplies complete group membership and member hashes. The lead must map keys to external issue IDs; no external issue is claimed opened by this inventory. Retired rows remain visible without invented outage tickets.

## Comparison and scope limits

- User screenshot18:26Z, v1at18:37:18Z, frozen final v2at18:45:27Z are different observations. No before/after improvement is inferred.
- User91succeeded/215unknown versus frozen88succeeded/217unknown cannot be causally compared across clocks and protected-log exclusions.
- 139 in v1 was success-plus-declared-recurrence, not execution coverage. Final93durablecompletions and144successsignals use independent definitions.
- Raw217unknown includes185ACTIVE and32NEVER_SCHEDULED.75ACTIVEunknown are due today;110are not in that population.
- Generic unit metadata proves8ACTIVE-declared timers disabled/unloaded, not whether to re-enable them. Agent-runtime instances may be intentionally unloaded; owner decides.
- Mutable later receipts cannot prove historical completion merely because producer as_of is earlier. Hermes later receipt ended18:51 after the frozen clock.
- Standard n8n output-verdict coverage is not a full adjudication of heterogeneous non-n8n business-output contracts.
- 64protected lanes received registry/existing-receipt metadata inspection only, no broker/execution/scalp logs, protected-unit show, credentials or subsystem investigation.

No source, registry, schedule, unit, broker setting, incident or credential changed. No paid call, live HTTP request, notification or job execution occurred.313zero-byte watchdog temporary files observed separately were not removed.

## Artifacts

- inventory.json/inventory.csv: all687per-job records, evidence dimensions, scheduler/owner/receipt paths, native result, classification, source times and ticket keys.
- runtime_orphans.csv:5separate runtime timer observations.
- summary.json: counts, percentages, definitions, comparison limits.
- ticket_groups.json: proposed root-cause group membership and hashes.
- evidence_manifest.json: immutable baseline and curated file hashes.

Immutable baseline inventory SHA25697f7ee1266db8eba01b5597e2233fff758d0312e66b1eb5a67f1aae72ce9d710; Jobs snapshot SHA256014a995ae2a53f6db6771a67e2b96cfbf963b48b97dc32ecef2c806f79c44f7a.

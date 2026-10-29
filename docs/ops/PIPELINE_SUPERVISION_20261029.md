# Pipeline supervisor failures — 2026-10-29

Status: implemented for review; service installation and production verification pending.
Incident: INC-261029-gtrqjp. Design: none (no UI change).
Operator approval: “Implement the plan.” No broker work or live execution is authorized here.

## Evidence

The alert d7fb0f0c aggregates failed pipeline **start times** over four hours, not kill times.
Read-only production logs, service journals and forced-read-only pipeline_runs queries show:

- Fifteen enrichment runs started 08:04:00 ET and lasted 36.45–36.56s. The watchdog logged
  `enrichment batch exceeded 37s; terminating 15 child process trees` at 08:04:36.803.
  News and Finviz retries had consumed most of its health-tick budget. Tick duration275.323s,
  watchdog252.915s, effective step timeout267.6s; the tick nevertheless reported healthy.
- Seven short orchestrator exits line up with health-tick journal completion at 04:30:26,
  04:45:18, 05:00:24, 05:15:16, 06:15:17, 07:15:22 and 07:45:17 ET. The installed unit has
  KillMode=control-group. Unit cleanup is strongly supported by timing/configuration, although
  the journal does not name each killed PID. The other four exits align with duplicate-reaper
  actions at 05:12, 05:15, 05:21 and 06:15 ET. They were not thirty-minute overruns.
- Escalation retry receipts98436–98438 used worker --limit25 and killed it after300s.
  Health-agent remediation receipt67575 used --limit40 and killed it after180s.
  A later worker completed in89.9s. Both callers lacked cooperative worker deadlines.
- Scalp hot-list receipt06:00:01.922 recorded Finviz prime_setups26.041s followed by
  watchlist_setups128.112s, then two deferred screeners. The lane itself terminated the
  child at its remaining deadline. Subsequent refreshes recovered.

Seven-day uncensored **successful** pipeline durations, queried 2026-10-29:

| Pipeline | Count | Median seconds | p95 seconds | Maximum seconds |
|---|---:|---:|---:|---:|
| symbol_enrichment |888|123.7|194.1|226.7|
| process_watchlist_agent_jobs |643|0.2|92.9|305.5|

These are survivor distributions under existing caps. They justify preserving bounds,
not claiming that every future job must finish inside them. Historical failures stay recorded.

## Execution ownership

The health tick requests `tradeai-pipeline-repair@enrichment.service` on the existing
watchdog cadence. Orchestrator remediation requests `tradeai-pipeline-repair@orchestrator.service`.
No new timer is introduced. Each service is independently owned by the systemd user manager;
nohup and a new process session alone cannot escape the health tick's cgroup.

The service helper accepts only these two fixed names, never caller shell commands. Missing
units fail closed without an inline fallback. Acceptance means PENDING, never recovered.
Completion receipts are `data/runtime/pipeline_repair_{enrichment,orchestrator}_last.json`
under persistent state; pipeline output and child counts still determine recovery.

Enrichment keeps240s for its batch and a270s service backstop. Orchestrator keeps its30m
reaper cap, with1830s service backstop. Internal admission prevents duplicates from beginning
pipeline work; contention is explicit deferred work. Existing external locks remain compatible.

Worker callers retain180/300s hard limits and cooperative deadlines. Unfinished jobs remain
retryable. Finviz retains its limits and prioritizes unfinished screeners on a later refresh;
partial results never advance a complete-refresh claim.

## Operator activation after reviewed merge

Do not run these commands as part of agent implementation. AGENTS.md §17 reserves service
installation/activation for the operator's approval. Deploy the reviewed code first; a missing
unit produces a visible failed handoff until this installation is approved and completed.

From the verified release directory (record its actual path and SHA):

```sh
install -D -m 0644 config/systemd/user/tradeai-pipeline-repair@.service "$HOME/.config/systemd/user/tradeai-pipeline-repair@.service"
install -D -m 0644 config/systemd/user/tradeai-pipeline-repair@enrichment.service.d/timeout.conf "$HOME/.config/systemd/user/tradeai-pipeline-repair@enrichment.service.d/timeout.conf"
systemctl --user daemon-reload
systemctl --user show tradeai-pipeline-repair@enrichment.service -p LoadState -p TimeoutStartUSec -p KillMode
systemctl --user show tradeai-pipeline-repair@orchestrator.service -p LoadState -p TimeoutStartUSec -p KillMode
```

No enable or manual start is needed: existing natural health/watchdog calls request work.
No rendered broker-secret EnvironmentFile is added. Services execute the existing scripts,
not new authoritative-store writers. Keep the previous unit files if replacing an installation.

## Acceptance and rollback

Observe two naturally due enrichment batches. Verify completed counts and fresh enrichment
outputs, no37s herd cancellation, correct nonzero failures, and no false healthy child result.
Verify worker completed/deferred counts, released interrupted claims and later progress.
Verify one orchestrator producer per interval, no failed rows for admission contention, and
no quarter-hour health-tick teardown failures. Verify Finviz deferred IDs resume and output
freshness advances only when produced. Require the normal PASSED post-release tester receipt.

If ownership, progress or output correctness regresses, hold further merges and prepare a
revert PR. Operator decides rollback and restores prior service configuration if needed.
Never clear historical failed rows, disable the reaper, weaken KillMode or raise spend caps.

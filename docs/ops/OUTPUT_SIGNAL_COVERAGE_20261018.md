# Output-signal coverage — ACTIVE lanes with no output signal (2026-10-18 review, recounted 2026-10-19)

Status: report + explicit exemptions. Authority: READ_ONLY_ADVISORY. Packet:
`docs/ops/packets/registry-runtime-truth-20261018/`. Pinned by `tests/test_registry_runtime_truth_20261018.py`
(every ACTIVE kind-none lane below must be named in this file; the exemption set is pinned exactly). The
2026-11-07 update to D and E is pinned by `tests/test_lane_output_signal_cohort_20261107.py`.

## Counts

The external review of 2026-10-18 counted 46 ACTIVE registry rows with `output_signal.kind = none` and 48 of 116
n8n allowlist entries carrying `output_receipt: v2`. Recounted on `origin/main` `baeda8d16` (2026-10-19): **46 / 48 of
116 — both confirmed.**

| measure | main `baeda8d16` | this branch |
|---|---|---|
| registry rows | 645 | 646 (+ `registry-runtime-truth`) |
| ACTIVE rows | 464 | 470 (+5 Hermes steps reconciled, +1 new lane) |
| ACTIVE with `output_signal.kind = none` | 46 | 46 (9 now explicit exemptions) |
| allowlist entries | 116 | 117 |
| allowlist entries with `output_receipt: v2` | 48 | 49 |
| allowlist entries with a `live_arg` | 72 | 73 |
| ... of which without `output_receipt: v2` | 24 | 24 |

The 24 live-capable allowlist entries without a v2 receipt (their live runs get output verdict
`declared_not_enforced`: exit 0 is the only evidence): advisory-desk-run-now, aegis-brief-regenerate,
analyst-prospectus-generate, backup-verify, data-gap-resolver-at-0-10-16, desk-suggestions-digest,
finviz-view-contracts, generate-analyst-daily-digest, heartbeat-watch, hermes-entity-spike-discovery,
**hermes-learning-config-governor, hermes-learning-outcome-grader, hermes-learning-outcome-learning,
hermes-learning-tag-engine** (live on n8n since 2026-10-17), job-coverage-monitor, lane-governance-packet-weekly,
maturity-remeasure, momentum-cache-reconcile, n8n-lab-watchdog, n8n-workflow-drift-check,
nightly-cutover-controller, storage-watch, trade-ai-restore-drill, trade-ai-scalp-live.

## The exemption convention

`check_lane_registry` already allows `output_signal {kind: "none", reason, detail}` (the reconciler writes
`UNVERIFIED_OUTPUT` and `NO_DURABLE_OUTPUT`). Those reasons mean *debt*. A legitimately signal-free lane now says so
explicitly:

```json
"output_signal": {"kind": "none", "reason": "SIGNAL_FREE_EXEMPT", "detail": "<why, >= 20 chars>", "exempt_since": "2026-10-19"}
```

`scripts/lib/lane_registry.py validate_row` rejects an exemption without `detail` / `exempt_since`, or on any kind but
`none` (an exemption can never hide a declared artifact). The lane monitor still reports these lanes UNVERIFIABLE; the
exemption changes the backlog, not the verdict. For generated rows (`generated_by reconcile_lane_registry@v1`) the
same exemption is recorded as `declared_no_output` in `docs/implementation/n8n-maturity/data/lane_output_evidence.json`,
and `scripts/reconcile_lane_registry.py` now honours `declared_no_output` on the systemd path too, so a re-reconcile
keeps it.

## Classification of the 46

### A. Exempt — signal-free by nature (9, `SIGNAL_FREE_EXEMPT` added)

| lane | why |
|---|---|
| `launchpadlib-cache-clean` | OS vendor user timer (owner os), not a Trade AI producer |
| `snap-firmware-updater-firmware-notifier` | OS vendor user timer |
| `systemd-tmpfiles-clean` | OS vendor user timer; **also** `status DISABLED_UNRULED` with a pending proposed NEVER_SCHEDULED (operator ruling, not changed here) |
| `ubuntu-insights-collect` | OS vendor user timer |
| `ubuntu-insights-upload` | OS vendor user timer |
| `openclaw-reminder-claude-plan-1` | calendar reminder fired by the OpenClaw scheduler; the delivered message is the whole effect, recorded by OpenClaw |
| `openclaw-reminder-claude-plan-2` | same |
| `openclaw-reminder-supergrok-expiry` | same |
| `openclaw-reminder-sentinelone-earnings` | same |

### B. Already explicitly declared, needs a tiny receipt (2, unchanged)

| lane | state of the declaration |
|---|---|
| `prewarm-finviz-strip-map` | `NO_DURABLE_OUTPUT`: `curl -o /dev/null` cache prewarm; fix = a `curl -w` status receipt or eliminate (rationalization) |
| `prewarm-trade-ai` | same |

### C. Backlog — long-running services need a liveness contract, not a per-run artifact (13)

None of these has a "run"; `systemd_result` (a oneshot's last Result) does not describe a daemon. They need a liveness
signal kind (ActiveState + restart count, or the service's own heartbeat file) — a schema decision, so they stay
`UNVERIFIED_OUTPUT` for now.

`chatgpt-oauth-proxy-service`, `dof-dashboard-service`, `grok-oauth-proxy-service`, `openclaw-gateway-service`,
`power-watch-service`, `tradeai-cio-telegram-service`, `tradeai-health-agent-service`, `tradeai-lab-postgres-service`,
`tradeai-n8n-coordination-gateway-service`, `tradeai-n8n-run-executor-service`, `tradeai-n8n-run-relay-service`,
`tradeai-ops-agent-service`, `trade-ai-lab-moomoo-opend-service` (broker-adjacent: AGENTS.md §0 rule 2 — listed only,
out of scope without an `execution-ops` grant).

### D. Backlog — timers that need a LaneRunReceipt (13)

| lane | note |
|---|---|
| `tradeai-agent-runtime-alex` | agent runtime tick; `lib/lane_last_receipt` receipt in the runtime |
| `tradeai-agent-runtime-morgan` | same |
| `tradeai-agent-runtime-steph` | same |
| `tradeai-agent-runtime-atlas` | same; **unit disabled, `DISABLED_UNRULED`** while the row says ACTIVE — operator ruling pending |
| `tradeai-agent-runtime-concierge` | same; **unit disabled, `DISABLED_UNRULED`** |
| `tradeai-agent-runtime-hermes` | same; **unit disabled, `DISABLED_UNRULED`** |
| `tradeai-agent-runtime-pulse` | same; **unit disabled, `DISABLED_UNRULED`** |
| `tradeai-maturity-feeds` | feed refresh; receipt with rows written |
| `tradeai-watch-decision-scheduler` | receipt with decisions scheduled |
| `hermes-deep-research-local` | receipt with briefs produced |
| `mcporter-token-refresh` | credential refresh: receipt must carry only ok/expiry, never a token value |
| `hermes-librarian-retention` | **resolved 2026-11-07** — `HermesLibrarianRetentionReceipt@v1` declared as `json_key` `ts` (see the update section) |
| `disk-hygiene-enforcer` | deletion-only; a parallel branch (`feat/disk-hygiene-n8n-20261018`) owns this row — not touched here |

### E. Backlog — cron lines that need a LaneRunReceipt (9)

**2026-11-07:** nine of the eleven rows below are resolved — see the update section after this table.

| lane | note |
|---|---|
| `dof-run-pipeline` | external `~/nyc-dof-auction` pipeline; `run_pipeline.py` never exits nonzero — receipt with per-stage status |
| `ops-daily-digest` | external OpenClaw script, sends Telegram; receipt = sent/skipped + count |
| `ops-weekly-learning-report` | same |
| `rotation-rebalance-digest` | POSTs research requests and sends; receipt with requests posted |
| `crawl-v3-dashboard` | prints and conditionally sends; receipt with result counts |
| `alert-missing-conditions` | dispatches alerts + a paid probe; receipt with alerts and probe outcome |
| `sync-memory-to-drive` | external script; the archive mtime is not proof of upload — receipt with upload result |
| `hermes-top20-external-intel` | stdout-only report; receipt with items curated |
| `hermes-usefulness-backfill` | writes a score without a timestamp column; receipt with rows scored (or add `scored_at`) |
| `release-train-claim` | claimer timer (2026-10-22): a pass with nothing pending writes nothing; receipts only on a claimed TrainWindowRequest — receipt per pass |
| `ops-controls-applier` | long-running Ops Controls applier (2026-10-22): heartbeat is read by GET /api/v2/ops/controls/state — write the heartbeat as a file signal |

## 2026-11-07 update — ten rows that said "no output proof declared"

Ten ACTIVE rows were still `output_signal.kind = none` with no reason, so `GET /api/v2/scheduler-operations`
reported each as `NO_SIGNAL` with `health_reason = "NO_SIGNAL_WITH_REASON missing; no output proof declared"`
and `is_problem()` listed all ten on Jobs & n8n. Each row is now either a declared artifact or an explicit
reason. Half of it was a declaration gap, not a missing producer.

| lane | declaration | evidence |
|---|---|---|
| `crawl-v3-dashboard` | `json_key` `data/runtime/crawl-v3-dashboard_last.json` → `ok_at` | the receipt already existed on disk (`ok_at` 2026-11-06T11:53Z); the registry never named it |
| `hermes-top20-external-intel` | `json_key` → `hermes_top20_external_intel_last.json` `ok_at` | existing `LaneRunReceipt@v1`; `ok_at` advances only when a researcher call succeeded |
| `hermes-usefulness-backfill` | `json_key` → `hermes-usefulness-backfill_last.json` `ok_at` | existing receipt (selected/scored/failed); the timestamp-less `usefulness_score` column is no longer the only evidence |
| `hermes-librarian-retention` | `json_key` → `hermes_librarian_retention_last.json` `ts` | `HermesLibrarianRetentionReceipt@v1`, written only on an applied pass (absent for a dry run) |
| `rotation-rebalance-digest` | `json_key` → `rotation-rebalance-digest_last.json` `ok_at` | **producer added 2026-11-07**; `ok_at` advances only on exit 0, and a withheld publication exits 1, so a withheld digest goes stale instead of green |
| `alert-missing-conditions` | `json_key` → `alert-missing-conditions_last.json` `ok_at` | **producer added 2026-11-07**; the receipt carries each alert count plus the credit-probe outcome, and a probe that could not answer is recorded as such instead of as "credits fine" |
| `dof-run-pipeline` | `file_mtime` `~/nyc-dof-auction/outputs` | stage 6's dated reports; proves stage 6 produced reports, **not** that every upstream stage succeeded — there is no aggregate run receipt, and the row's note says so |
| `ops-daily-digest` | `none` + `NO_SIGNAL_WITH_REASON` | external `~/.openclaw` script: prints one JSON line, sends Telegram, writes no artifact; the cron `>>` redirect carries stderr, so a traceback advances it |
| `ops-weekly-learning-report` | `none` + `NO_SIGNAL_WITH_REASON` | same |
| `sync-memory-to-drive` | `none` + `NO_SIGNAL_WITH_REASON` | external `~/.claude` script: the tarball mtime proves packing, not upload; the log line is the cron redirect; the upload leaves no local receipt |

Two consequences worth stating plainly:

* `rotation-rebalance-digest` and `alert-missing-conditions` have **no receipt on disk yet**, so between this
  change and each lane's first real cron run the projection reports them `SILENT` (an actionable state, because
  an absent artifact is silence and not unverifiability) rather than `NO_SIGNAL`. They clear on their own: the
  rotation digest on its next Sunday 18:00 run, the missing-conditions check on its next weekday 07:30 run.
* For the three reason-bearing rows the reason removes the row from the problem list; it does not make the lane
  verified. The lane monitor still reports them UNVERIFIABLE, which is the honest verdict.

The three reason rows and the dof per-stage gap need a change outside this repository (a wrapper that writes a
`LaneRunReceipt`, and per-stage status in `run_pipeline.py`); those are written up as proposals against an
operator-approved crontab change, not done here.

## Not done here, on purpose

* No backlog row was given an invented artifact: an output signal names something the lane provably writes (AGENTS.md
  §0 rule 8), and each of C–E needs a code change in the lane first.
* The five `DISABLED_UNRULED` ACTIVE rows (`systemd-tmpfiles-clean` and four agent runtimes) are a registry-truth
  contradiction of their own (declared ACTIVE, unit disabled). Their state is an open operator decision
  (`operator_decision_pending: true`), so it is reported, not flipped.

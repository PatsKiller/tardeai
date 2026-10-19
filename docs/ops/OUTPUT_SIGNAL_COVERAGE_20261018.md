# Output-signal coverage — ACTIVE lanes with no output signal (2026-10-18 review, recounted 2026-10-19)

Status: report + explicit exemptions. Authority: READ_ONLY_ADVISORY. Packet:
`docs/ops/packets/registry-runtime-truth-20261018/`. Pinned by `tests/test_registry_runtime_truth_20261018.py`
(every ACTIVE kind-none lane below must be named in this file; the exemption set is pinned exactly).

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
| `hermes-librarian-retention` | deletion-only: needs an archive-first receipt (rows archived/purged); ties to the open DB-retention item |
| `disk-hygiene-enforcer` | deletion-only; a parallel branch (`feat/disk-hygiene-n8n-20261018`) owns this row — not touched here |

### E. Backlog — cron lines that need a LaneRunReceipt (9)

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

## Not done here, on purpose

* No backlog row was given an invented artifact: an output signal names something the lane provably writes (AGENTS.md
  §0 rule 8), and each of C–E needs a code change in the lane first.
* The five `DISABLED_UNRULED` ACTIVE rows (`systemd-tmpfiles-clean` and four agent runtimes) are a registry-truth
  contradiction of their own (declared ACTIVE, unit disabled). Their state is an open operator decision
  (`operator_decision_pending: true`), so it is reported, not flipped.

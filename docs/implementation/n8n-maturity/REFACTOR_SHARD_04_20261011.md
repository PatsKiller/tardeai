Status: PROPOSED — SOURCE_ONLY, not live
as_of: 2026-10-11
Owner: Codex refactor shard 04
Measured at: source worktree; host runtime NOT_MEASURED

# Shard 04 cron → n8n source refactor

Status: SOURCE_ONLY; not merged, not released, no scheduler ownership change.

Base: origin/main `7b36c98c32382b86c04bd5792927fc7c2bd1c729`. Branch: `n8nmat/refactor-shard-04`.

All 37 assigned lane identities were reviewed: 8 shadow proposals, 15 blocked, 6 broker skips, 6 sender skips, 2 class skips. Every new health contract is DRAFT. The installed/main policy and playbook govern this source-only work; no policy was ratified.

## Behavior and durable proof

Each admitted script now parses strict arguments and prints an offline `DRY-RUN <lane>: would ...` plan before credentials, DB, HTTP, model calls or writes. An unknown or abbreviated flag exits 2. Existing real cron argv and stdout are compared with frozen old entrypoints using fake work. Explicit previews write neither output nor lane receipts; legacy implicit corpus previews are retained where they existed.

Real runs write `LaneRunReceipt@v1` to persistent `data/runtime/<lane>_last.json`; registry health reads its `ok_at`. Failures preserve the prior `ok_at`. Existing soft-error exit codes remain compatible while receipt status fails: Finviz write errors, blocked research agenda, incomplete worker pools, and candidate-read errors do not create fresh success proof. The Hermes scalp receipt is limited to the assigned scalp source; another source cannot mint its receipt.

Own environment loaders copy only named variables. All eight allowlist entries remain report mode because the transitive shared DB/search/research loader closure needs the integrator’s narrowing change. No broker variable name is included. All live_arg fields are null and the existing non-retrying policy none is used. Scheduler wave R2-04 records shard ownership; dispatch wave W4 stays within the current shared W0–W5 schema.

## Lane dispositions

| Lane | Source class | Result | Contract | Cron flock needed |
|---|---|---|---|---|
| identity-sweep-stage0 | ingest | SHADOW_READY | DRAFT | false |
| cio-wake-turn-effects | READ_ONLY | BLOCKED(systemd lane has no cron shadow shape under current R1 gate) | unchanged | false |
| provider-cost-reconcile | READ_ONLY | BLOCKED(systemd lane has no cron shadow shape under current R1 gate) | unchanged | false |
| eod-consolidated-close-sync | WRITER | BLOCKED(systemd lane has no cron shadow shape under current R1 gate) | unchanged | false |
| advisory-lessons-reflect | WRITER | BLOCKED(systemd lane has no cron shadow shape under current R1 gate) | unchanged | false |
| gir-projector | WRITER | BLOCKED(systemd lane has no cron shadow shape under current R1 gate) | unchanged | false |
| tradeai-agent-runtime-atlas | DAEMON | BLOCKED(disabled unknown-agent timer requires operator ruling; no cron shadow shape) | unchanged | false |
| tradeai-watch-decision-scheduler | READ_ONLY | BLOCKED(systemd lane has no cron shadow shape under current R1 gate) | unchanged | false |
| hermes-momentum-catalyst-scalp | ingest | SHADOW_READY | DRAFT | false |
| portfolio-repricer | BROKER | SKIP_BROKER | unchanged | false |
| goal-pilot-material-change | WRITER | BLOCKED(host-side paid pilot routing and truthful failure contract require separate review) | unchanged | false |
| aegis-transcript-discovery | ingest | SHADOW_READY | DRAFT | true |
| agent-intelligence-cron-deep | WRITER | BLOCKED(cross-shard child launcher masks child failures and has no step receipts) | unchanged | false |
| agent-intelligence-cron-daily | WRITER | BLOCKED(cross-shard child launcher masks child failures and has no step receipts) | unchanged | false |
| agent-intelligence-cron-intraday | WRITER | BLOCKED(cross-shard child launcher masks child failures and has no step receipts) | unchanged | false |
| auto-enrichment-runner | BROKER | SKIP_BROKER | unchanged | false |
| auto-research | SENDER | SKIP_SENDER | unchanged | false |
| build-hermes-canonical-status | WRITER | SKIP_CLASS | unchanged | false |
| candidate-discovery-orchestrator | ingest | SHADOW_READY | DRAFT | true |
| defense-inverse-stoplights | BROKER | SKIP_BROKER | unchanged | false |
| finviz-proactive-research | ingest | SHADOW_READY | DRAFT | false |
| generate-analyst-reports-autonomous-weekly | WRITER | BLOCKED(shared reporting engine calls provider-named llm_lane rather than a reviewed process route) | unchanged | false |
| generate-analyst-reports-autonomous-full | WRITER | BLOCKED(shared reporting engine calls provider-named llm_lane rather than a reviewed process route) | unchanged | false |
| hermes-backlog-health-check | WRITER | BLOCKED(systemd monitor has no cron shadow shape and class is outside allowed set) | unchanged | false |
| hermes-coordinator | WRITER | BLOCKED(cross-shard child executor and embedding/promotion closure require separate governed runner review) | unchanged | false |
| hermes-discovery-scorecard | learn | SHADOW_READY | DRAFT | true |
| hermes-research-agenda-at-45-7 | learn | SHADOW_READY | DRAFT | false |
| hermes-research-worker-pool | ingest | SHADOW_READY | DRAFT | false |
| incubator-rolloff-engine | WRITER | SKIP_CLASS | unchanged | false |
| ipo-lockup-alert | SENDER | SKIP_SENDER | unchanged | false |
| market-regime-classifier | SENDER | SKIP_SENDER | unchanged | false |
| proposal-monitor | BROKER | SKIP_BROKER | unchanged | false |
| run-scheduled-quote-refresh-incubator | BROKER | SKIP_BROKER | unchanged | false |
| run-scheduled-quote-refresh-pending | BROKER | SKIP_BROKER | unchanged | false |
| system-rollup-snapshot | SENDER | SKIP_SENDER | unchanged | false |
| watch-alerts-eval | SENDER | SKIP_SENDER | unchanged | false |
| watch-directives-service | SENDER | SKIP_SENDER | unchanged | false |

## Blockers and required integration work

Systemd timer lanes remain blocked: the current R1 shadow admission requires cron shape, and this shard has no exact cron counterpart. Do not synthesize a cron expression or claim timers were observed. Broker/safety and sender lanes stay outside this refactor. The three agent-intelligence launcher modes mask four other-shard child failures; the coordinator and provider-named reporting engine need separate child/process-route review. The goal pilot can return success without executing its expected API. None is declared ready.

The canonical Hermes status projection has historical hard-coded census and a retired local-model identity. Its monitor class is excluded, and the discrepancy is documented for the integrator. Ollama remains retired; this shard invokes no model.

Aegis transcript discovery, candidate discovery and Hermes scorecard have no observed outer flock. Their proposed locks are `/tmp/aegis-transcript-discovery.lock`, `/tmp/candidate-discovery-orchestrator.lock` and `/tmp/hermes-discovery-scorecard.lock`. They require an operator-owned later cron packet; no canary before each cron lock matches the executor lock.

The approved scoped crontab snapshot at `/home/johnclaw/n8n-maturity-verification/refactor/authorized_cron_snapshot_01_04.json` (2026-10-11T14:57:08.697196+00:00) provides exact scheduler text for these proposals. Other host states, liveDB, CURRENT and execution receipts were not read in this refactor. Full host state-drift acceptance is NOT_MEASURED; supported scoped fixtures exercise source validation only.

## Validation and handoff

Evidence and final gate exits are in untracked `REFACTOR_EVIDENCE_04.md`, `refactor-gates-04/`, `CRON_FLOCK_NEEDED.tsv` and `SHARED_CHANGES_NEEDED.md`. The new test family is registered in `run_cio_hardening_ci.py`; each subprocess preview is trapped against secret files, network, subprocesses and writes. Final pytest uses an empty-env dependency fixture and pre-import capability traps with M2_SKIP_DOCKER=1. Shared conftest defaults require separate hardening; no live connection is allowed here. DRAFT health-gate refusals are expected and require operator contract review.

Final guarded tests: 131 passed, 11 inherited optional/integration skips, 215 deselected; capability blocks zero. Registry (scoped source), authority, coverage, host paths, dark contracts, docs inventory and Ruff pass. The health check retains exactly eight DRAFT_NOT_GRANDFATHERED findings; contracts were never marked REVIEWED. Own unmeasured run counts are null. Initial test-fixture errors were corrected; no gate was relaxed. Startup initialization failures in Hermes scalp and the worker pool are now receipted, with negative coverage.

The additional isolated relay check required native socket approval and then returned REFUSED on two existing held-workflow filters: approval-escalate and heartbeat-watch are undeclared on this branch. Its 12-request synthetic concurrency probe passed (cold max 0.517s, warm max 0.409s); no service runtime is proven. The gate remains red, with exact command/errors in the local evidence artifact. Actual crontab read denial was resolved by native approval for the same read. Successful stream-fd warnings were continued under §1A.

Integrator: merge source branches into one train, resolve additive JSON/test-registration/doc-index conflicts, rerun gates, obtain contract review, and rebuild the workbook once. Inventory rows are in `refactor/inventory_rows_04.tsv`; skipped/blocked rows keep their current stage. No Drive sync or push by this shard.

Rollback before integration: omit this branch. After a separately authorized deployment, use the existing exact-release rollback and scheduler packet procedures; this source commit does not change any runtime schedule.

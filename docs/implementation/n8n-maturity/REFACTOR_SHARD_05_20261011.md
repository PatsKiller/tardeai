# Refactor shard 05 — 2026-10-11 source packet

Six new cron-supported source proposals use `scheduler.stage: shadow`, `dispatch.mode: dry_run`, `dispatch.wave: W4`, `scheduler.wave: R2-05`, and no retry. This packet is not live. It changes no scheduler, service, deployed release, database, notification route or model runtime. Contracts remain DRAFT; no reviewer fields are changed. One assigned lane (`update-lockup-earnings-dates`) already has a reviewed shadow admission on main and is retained untouched, with zero new delivery.

The exact approved selected cron snapshot was captured at `2026-10-11T17:05:28.513179+00:00`; full cron census, timer state, natural shadow execution and live ledger are NOT_MEASURED. `tests/fixtures/refactor_shard_05/cron_argv.json` retains exact original lines and all business parameters. The stance rendered-env source remains in its exact scheduler text. Hermes source safety was tested, but its admission was refused because the exact cron contains llm_priority_guard.sh; its original control-plane row is restored unchanged. Proposed executor commands retain the business argv. Report-mode environment reasons expose those shared closures; the packet never reads a rendered environment.

Explicit previews print one offline plan before environment, database, store or provider work. Existing no-flag data previews remain where present. Real business calls, stdout and exit behavior are compared with frozen original entrypoints using fakes. Weekly no-top profile receipt is additive; the reviewed `--watchlist-top 300` lane and its receipt are retained. Exceptions keep their original behavior and failed receipts carry the previous ok_at. Finviz partial failures and profile provider/writer misses keep legacy exit 0 while their own receipt reports failed without advancing ok_at.

`siem-to-hermes-backlog` has an offline preview and named loader source fix, but the approved snapshot contains no matching cron line. Its source safety is tested, and it receives no new registry, allowlist or contract admission. Other blocked/sender/broker/monitor rows are left unchanged.

All new health baselines are CLASS_DEFAULT_PROVISIONAL / SOURCE_ONLY; coordination ledger NOT_MEASURED and runs_considered null. Source-derived freshness separates regular weekday gaps from weekend gaps. Deployment must establish receipt freshness before it can support health claims. Success evidence comes from run and lane receipts; no soft-deleted execution behavior is asserted as live evidence.

Two cron locks are proposed only: `/tmp/drain-discovery-backlog.lock` and `/tmp/commitment-outcome-sweep.lock`. No outer flock appears in their approved original lines. The operator must reconcile exact cron/executor locks before canary. All six environment policies remain report until the integrator resolves shared loader/import closure debt. Narrowing shared libraries is outside this shard.

Validation uses a minimal scratch environment, empty dotenv fixtures and pre-import DB/socket/production-file guards from the first test run. Python profile children inherit those guards even when they pass an explicit environment. Nodeps supplies optional missing dependencies; it is independent of the safety guards. The new shard test is registered in the canonical PR profile. The installed-dependency test action was refused by the safety barrier after six attempted psycopg2 connections; no connection executed. Its printed passing tests do not turn that guarded action green. Exact gate results are in the local untracked SHARD_REPORT_05.md and refactor-gates-05 artifacts; DRAFT review refusals must remain red until operator review, without gate weakening.

Integration: merge source only after reviewing gate evidence. Resolve JSON and generated-index conflicts by preserving all shards and existing reviewed objects. External inventory overlay contains all 37 rows; non-ready new_stage is unchanged. Rebuild the workbook once on the integration branch. Omit/revert this source packet to roll it back before deployment; no live rollback is needed for this work.

| lane | class | result | lock needed | contract | notes |
|---|---|---|---|---|---|
| material-change-detector-stage1 | ingest | SHADOW_READY | observed outer flock | DRAFT | Source-only proposal; DRAFT review and shared env closure pending |
| free-first-circulation | unadmitted | BLOCKED | unchanged | unchanged | systemd timer has no cron R1 shadow admission shape; shared circulation/model closure requires its owner |
| served-copy-split-audit | monitor | SKIP_CLASS | unchanged | unchanged | read-only served-copy audit is a monitor, outside ingest/llm/learn |
| set-purge-dates | unadmitted | BLOCKED | unchanged | unchanged | inline secret-bearing retention command has no owned script; no secret read or scheduler edit |
| prewarm-trade-ai | monitor | SKIP_CLASS | unchanged | unchanged | read-only cache warming/health monitor has no owned durable research output |
| hermes-deep-research-local | unadmitted | BLOCKED | unchanged | unchanged | systemd timer shape and direct local model-route ownership require governed admission |
| tradeai-agent-runtime-concierge | unadmitted | BLOCKED | unchanged | unchanged | disabled agent runtime timer requires operator class/state ruling and a supported timer admission shape |
| approval-package-reminder | excluded | SKIP_SENDER | unchanged | unchanged | direct approval-package notification sender |
| cio-stance-classification-drain | ingest | SHADOW_READY | observed outer flock | DRAFT | Source-only proposal; DRAFT review and shared env closure pending |
| portfolio-ai-analyst | excluded | SKIP_BROKER | unchanged | unchanged | portfolio orchestrator reaches holdings/rebalance/stop paths; investigation stopped at boundary |
| dormant-lane-consumers | unadmitted | BLOCKED | unchanged | unchanged | orchestrates child scripts owned by other shards; child argv/env/receipt proof needed |
| run-inference-cycle-preopen | unadmitted | BLOCKED | unchanged | unchanged | shared inference shell launches cross-shard model children; governed bridge/child proof needed |
| run-inference-cycle-midday | unadmitted | BLOCKED | unchanged | unchanged | same shared inference shell; repeated schedule retained unchanged |
| run-inference-cycle-postclose | unadmitted | BLOCKED | unchanged | unchanged | same shared inference shell; repeated schedule retained unchanged |
| premarket-data-pipeline | unadmitted | BLOCKED | unchanged | unchanged | cross-shard premarket stage children and C1 ownership must be reconciled by integration owner |
| aegis-synthesis | unadmitted | BLOCKED | unchanged | unchanged | direct provider/model routing requires named governed bridge; shard does not invoke a model |
| build-symbol-profiles-at-0-19 | ingest | SHADOW_READY | observed outer flock | DRAFT | Source-only proposal; DRAFT review and shared env closure pending |
| drain-discovery-backlog | learn | SHADOW_READY | yes, proposed only | DRAFT | Source-only proposal; DRAFT review and shared env closure pending |
| external-market-data-ingest-fundamentals | excluded | SKIP_BROKER | unchanged | unchanged | shared script includes direct Alpaca credential/endpoint path; no further investigation or edit |
| external-market-data-ingest | excluded | SKIP_BROKER | unchanged | unchanged | same broker-adjacent shared script; both observed schedules retained unchanged |
| finviz-sector-research | ingest | SHADOW_READY | observed outer flock | DRAFT | Source-only proposal; DRAFT review and shared env closure pending |
| generate-analyst-daily-digest | unadmitted | BLOCKED | unchanged | unchanged | shared report-builder provider closure requires named governed model engine |
| generate-weekly-docx | excluded | SKIP_SENDER | unchanged | unchanged | weekly report delivery sends directly |
| hermes-analyst-coverage | unadmitted | BLOCKED | unchanged | unchanged | direct llm_lane selection and chained cron child need governed bridge and child evidence |
| hermes-directive-discovery | unadmitted | BLOCKED | unchanged | unchanged | REFUSED: exact cron llm_priority_guard.sh is forbidden_token:guard@scheduler.command_text; no exception or token stripping |
| hermes-source-curation | unadmitted | BLOCKED | unchanged | unchanged | direct llm_lane source-validation model route needs governed bridge |
| incubator-llm-screener | excluded | SKIP_SENDER | unchanged | unchanged | direct notification path |
| intel-auto-discovery | excluded | SKIP_SENDER | unchanged | unchanged | optional direct Telegram source path; sender admission requires notification intents |
| proposal-enrichment-loop | excluded | SKIP_BROKER | unchanged | unchanged | execution-readiness path is broker adjacent; further investigation stopped |
| run-research-intelligence-overnight | unadmitted | BLOCKED | unchanged | unchanged | cross-shard model child orchestration with masked failures; all repeated cron schedules retained |
| run-research-intelligence-overnight-archive | unadmitted | BLOCKED | unchanged | unchanged | same shared shell and masked child failures; receipt closure not established |
| run-scheduled-strategy-audits | excluded | SKIP_BROKER | unchanged | unchanged | open-trade/strategy audit child boundary; no further broker investigation |
| siem-to-hermes-backlog | unadmitted | BLOCKED | unchanged | unchanged | NO_APPROVED_CRON_MATCH: safe offline preview, strict argv, narrow loader and fake receipt tests added; no registry/allowlist/contract admission |
| social-scalp-scanner | excluded | SKIP_SENDER | unchanged | unchanged | direct alert notification source path |
| commitment-outcome-sweep | learn | SHADOW_READY | yes, proposed only | DRAFT | Source-only proposal; DRAFT review and shared env closure pending |
| update-lockup-earnings-dates | unadmitted | BLOCKED | unchanged | retained REVIEWED | ALREADY_SHADOW_MAIN: existing REVIEWED contract, row, allowlist and source retained untouched; zero new delivery |
| wire-advisory-lessons | unadmitted | BLOCKED | unchanged | unchanged | cross-shard rollup/learning child argv, env and output proof required |

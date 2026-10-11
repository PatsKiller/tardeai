Status: SOURCE_ONLY / DRAFT — local preparation, not live
as_of: 2026-10-11T15:17:00+00:00
Measured at: source base 7b36c98c32382b86c04bd5792927fc7c2bd1c729; approved scoped cron snapshot 2026-10-11T14:57:08.697196+00:00
Owner: Codex refactor shard 01

# Refactor shard 01 — offline CLI plans and durable receipts

Branch `n8nmat/refactor-shard-01` from current fetched origin/main `7b36c98c32382b86c04bd5792927fc7c2bd1c729`. All 38 assigned rows were read and classified; results: **BLOCKED 14, SHADOW_READY 6, SKIP_BROKER 5, SKIP_CLASS 2, SKIP_SENDER 11**. Six source rows propose scheduler shadow state; none are production acceptance or a natural fire. Main/CURRENT deployment identity, live timers and live DB receipts were not measured by this shard.

## Scope and evidence

`refactor/shard_01.tsv` defines ownership. Exact cron text for the six prepared entries comes from `/home/johnclaw/n8n-maturity-verification/refactor/authorized_cron_snapshot_01_04.json` (`native_approval=true`, exit 0, no sensitive rows retained). This snapshot contains 124 matching job lines across shards 01 and 04, not the full host cron census. Registry/allowlist/contract changes here are SOURCE_ONLY.

The terminal warning `Failed to create stream fd: Operation not permitted` accompanied successful exit-0 commands and was noted once, following playbook §1A. A separate sandboxed read actually failed: `crontabs/johnclaw/: fopen: Permission denied` (exit 1, tool chunk b90dee). That action stopped and was reported. The parent obtained native operator approval for the same read-only command; the approved snapshot resolves that read boundary. No alternate access path was used.

Each prepared CLI parses with `allow_abbrev=False`; `--dry-run` returns an offline plan before DB access, files, credential loading, telemetry, paid fetches or model calls. Unknown or abbreviated flags exit 2. Original successful cron argv are compared against source fragments from base `7b36c98c32382b86c04bd5792927fc7c2bd1c729` using only fake connections/providers. Real-run receipt branches are exercised only with fakes and scratch `TRADEAI_STATE_ROOT`. Failures preserve the previous `ok_at` and original exit/exception semantics.

The legacy injected SQL-preview APIs in feedback-loop and watchlist discovery remain available for their existing fake-DB tests. Their actual CLI entrypoints use the new offline plan. Finviz now reports unknown dry-run counts as null rather than invented zero; this source-only plan does not prove credentials or upstream connectivity. Provider empty-result/auth discrimination is not redesigned here and remains a live canary validation item.

All six `live_arg` values are null. Environment names contain no broker names. All six env closures use **report mode**, because shared `db_adapter`/`env_bootstrap` or `session13_db` narrowing needs integration; this is an explicit canary blocker, not an enforcement claim. The feedback-loop script's own loader copies only `DB_PASSWORD`; it is deferred to the real connection. No shared library was edited.

`dispatch.wave=W4` uses the current shared validator's supported W0–W5 enum. `scheduler.wave=R2-01` preserves requested shard provenance. This distinction was agreed with the integrator; the shared enum was not relaxed. Classes are ingest (goods, finviz, discovery, incubator) and learn (feedback, checkpoints), based on business semantics. All six use the existing non-retrying policy `none`, which permits these writer classes and avoids duplicate writes; the initial invalid `transient-2` selection was detected by the gate and corrected without changing any policy.

All six health contracts are DRAFT, have no reviewer and have no UNKNOWN field. Their `CLASS_DEFAULT_PROVISIONAL` cadence/timeout values are source defaults, not observed p95 or SLOs. Weekday-only lanes have weekend silence; checkpoint resolution is hourly all seven days and requires weekend receipts. Schedule gaps must be evaluated against the exact cron calendar before wall-clock freshness. Contract review, real-output proof, natural shadow receipt evidence and runtime env enforcement remain required.

## Lane decisions

| lane | class | result | lock needed | contract | notes |
|---|---|---|---|---|---|
| persistent-wake-hourly | SENDER | SKIP_SENDER | unchanged | unchanged | Gateway settlement sanctions a Telegram transport in the real wake path (run_persistent_wake.py:396); notification-intent migration is separate. |
| cio-nightly-reflection | WRITER | BLOCKED(SYSTEMD_RECIPE_HAS_NO_EXACT_CRON) | unchanged | unchanged | Source unit resolves scripts/lib/cio_nightly_reflection.py; systemd-specific dry-run and receipt recipe needed. No fabricated cron line. |
| agent-runtime-health | READ_ONLY | SKIP_CLASS | unchanged | unchanged | Health monitor is outside dispatch ingest/llm/learn; source unit invokes scripts.agent_runtime.health_monitor. |
| expected-services-audit | SENDER | SKIP_SENDER | unchanged | unchanged | Source timer service invokes check_expected_services.py --alert; real code calls send_telegram at line 369. |
| prewarm-finviz-strip-map | WRITER | BLOCKED(NO_SHARD_SCRIPT_FOR_HTTP_CACHE_ENDPOINT) | unchanged | unchanged | Shard script is ?; registry declares an HTTP cache endpoint with fresh=1. Need owned bounded wrapper and receipt; no read-only assumption. |
| trade-ai-news-monitor | SENDER | SKIP_SENDER | unchanged | unchanged | Source daemon/service calls send_telegram in trade_ai_news_monitor.py:171; notification ownership unchanged. |
| tradeai-agent-runtime-steph | WRITER | BLOCKED(SYSTEMD_RECIPE_HAS_NO_EXACT_CRON) | unchanged | unchanged | Source service is a bounded --once runner. Systemd-to-dispatch recipe and exact scheduling evidence required; do not misclassify as daemon. |
| hermes-subject-enhance-dispatch | WRITER | BLOCKED(LLM_BRIDGE_ROUTE_MISSING) | unchanged | unchanged | Controller launches provider-specific grok/chatgpt work without registered governed host process route. No provider migration into n8n. |
| research-scheduler-holdings | WRITER | BLOCKED(LLM_BRIDGE_ROUTE_MISSING) | unchanged | unchanged | External research/model calls lack a registered governed bridge process route; preserve existing account gate and model selection. |
| research-scheduler-priority-hourly | WRITER | BLOCKED(LLM_BRIDGE_ROUTE_MISSING) | unchanged | unchanged | Same research_scheduler.py owner/import closure; no provider keys moved or direct provider invocation allowed. |
| research-scheduler-watchlist-2030 | WRITER | BLOCKED(LLM_BRIDGE_ROUTE_MISSING) | unchanged | unchanged | Same research scheduler route blocker; preserve exact argv and scheduling ownership. |
| research-scheduler-incubator-sun-1900 | WRITER | BLOCKED(LLM_BRIDGE_ROUTE_MISSING) | unchanged | unchanged | Same governed model process route blocker; Sunday schedule unchanged. |
| active-trader-signal-calibration | BROKER | SKIP_BROKER | unchanged | unchanged | Protected scripts/active_trader/** path; script contents not read or modified. |
| aegis-overnight | SENDER | SKIP_SENDER | unchanged | unchanged | Direct send_telegram calls in aegis_overnight.py; separate notification-intent work required. |
| alert-missing-conditions | SENDER | SKIP_SENDER | unchanged | unchanged | dispatch_alert notification path and provider credit ping; no sends or paid calls performed. |
| daily-incubator-refresh | WRITER | SHADOW_READY | proposed /tmp/daily-incubator-refresh.lock | DRAFT | Offline CLI before eager shared env/telemetry imports; durable receipt for fake real path; shared env report mode blocks canary. |
| desk-suggestions-digest | READ_ONLY | SKIP_CLASS | unchanged | unchanged | Pure report class is outside ingest/llm/learn; existing report and dry-run semantics left intact. |
| feedback-loop-processor | WRITER | SHADOW_READY | existing lock reused | DRAFT | Offline CLI plan; DB_PASSWORD-only local env loader deferred until real connection; existing SQL-preview API and receipts retained. |
| finviz-screener-runner | WRITER | SHADOW_READY | existing lock reused | DRAFT | Paid-fetch dry-run defect removed; lazy throttle and telemetry; real receipt records soft membership/DB failure without advancing ok_at. |
| health-agent-llm-review | WRITER | BLOCKED(RETIRED_OLLAMA_AND_MISSING_GOVERNED_ROUTE) | unchanged | unchanged | Source still targets localhost:11434/qwen/gemma. Ollama is retired; model and governed host process route require operator choice. |
| indicator-engine | BROKER | SKIP_BROKER | unchanged | unchanged | Stop/target computation path excluded under the task stop/position-sizing rail; no claim that this source alone proves a broker transport. |
| oversight-weekly-digest | SENDER | SKIP_SENDER | unchanged | unchanged | Direct send_telegram; notification-intent migration separate. |
| proposal-llm-review-worker | WRITER | BLOCKED(RETIRED_OLLAMA_AND_MISSING_GOVERNED_ROUTE) | unchanged | unchanged | Source imports warmup_ollama/local_llm; retired runtime and no approved replacement model/process route. |
| reclassify-momentum-proposals | BROKER | SKIP_BROKER | unchanged | unchanged | Proposal strategy identity/type changes affect financial exit-routing semantics; conservative task policy boundary, no edits. |
| reconcile-watch-outcomes | WRITER | BLOCKED(PRICE_IMPORT_BOUNDARY_UNVERIFIED) | unchanged | unchanged | Imports _bars_with_volume from holdings_gain_guardian. Need reviewed data-broker read boundary before admitting this closure. |
| research-intelligence-queue | SENDER | SKIP_SENDER | unchanged | unchanged | Completion path calls send_telegram at research_intelligence_queue.py:173; no notification authority changes. |
| research-watchlist-discovery | WRITER | SHADOW_READY | proposed /tmp/research-watchlist-discovery.lock | DRAFT | Offline CLI --dry-run wins --apply; injected SQL-preview and original real receipts retained; existing CRLF lines retained; added/changed lines use LF. |
| resolve-due-checkpoints | WRITER | SHADOW_READY | proposed /tmp/resolve-due-checkpoints.lock | DRAFT | Offline CLI before input store/price DB; real append and migration receipts; pending apply refusal is failed output with legacy exit retained. |
| run-profit-capture-refresh | BROKER | SKIP_BROKER | unchanged | unchanged | Stop/protection-rule backtest child path is excluded by task rails; wrapper also contains git/secret handling. No children executed. |
| run-scalp-shadow-logger | WRITER | BLOCKED(OUT_OF_SHARD_CHILD_DRY_RUN_UNPROVEN) | unchanged | unchanged | Wrapper forces scalp_shadow_logger.py --live --apply; child is outside this shard. Need owned safe child CLI and receipt proof. |
| run-scheduled-watchpool-alerts-diagnostic | SENDER | SKIP_SENDER | unchanged | unchanged | Shell wrapper passes --send to child notification scripts. |
| run-scheduled-watchpool-alerts-maturity | SENDER | SKIP_SENDER | unchanged | unchanged | Same send-bearing wrapper; maturity argv kept untouched. |
| shadow-batch-generator-at-15-9 | WRITER | BLOCKED(NO_EXACT_LIVE_CRON_MATCH) | unchanged | unchanged | No exact weekday cron match in the approved scoped snapshot; registry state must be reviewed against fresh full host evidence. Also governed model route unresolved. |
| shadow-batch-generator-at-15-10 | WRITER | BLOCKED(LLM_BRIDGE_ROUTE_MISSING) | unchanged | unchanged | Weekly source route makes paid model calls and cron sources broad env. Need governed process route and narrow closure. |
| strategy-tilt | BROKER | SKIP_BROKER | unchanged | unchanged | Source description names account_policy.compute_sizing and per-trade budget; protected position-sizing/policy path. |
| strategy-weekly-review | SENDER | SKIP_SENDER | unchanged | unchanged | Direct send_telegram call; leave notification scheduler and authority unchanged. |
| technicals-gap-backfill | SENDER | SKIP_SENDER | unchanged | unchanged | Exact observed cron contains --alert and source calls send_telegram; notification migration separate. |
| watch-goods-consistency | WRITER | SHADOW_READY | existing lock reused | DRAFT | Strict offline source plan; original proposal backfill argv preserved; legacy coverage artifact plus LaneRunReceipt for real fake runs. |

## Locks and activation boundary

Existing cron locks are reused for watch-goods-consistency (`/tmp/watch_goods_consistency.lock`), finviz-screener-runner (`/tmp/finviz_screener.lock`) and feedback-loop-processor (`/tmp/feedback_loop.lock`). Three unlocked cron lines require an exact operator packet before any live canary: daily-incubator-refresh, research-watchlist-discovery and resolve-due-checkpoints. Proposed allowlist locks are `/tmp/<lane_id>.lock`; only a proposal is recorded, no cron line was edited. Details: untracked `CRON_FLOCK_NEEDED.tsv`.

Blocked model lanes are not admitted as llm work without a registered host-side governed process route. Ollama is retired, and no replacement model is selected in this change. Systemd lanes receive no fabricated cron record. Notification senders, stop/protection and sizing paths are left untouched under the explicit playbook rail.

## Validation and rollback

The dedicated shard suite is registered in `scripts/run_cio_hardening_ci.py`. Local dry-run outputs and state before/after hashes are in untracked `REFACTOR_EVIDENCE_01.md`; gate commands, exits and tails are in untracked `refactor-gates-01/`. The lane-registry gate uses its supported discovery-file options with the approved scoped cron snapshot and unmeasured timer state; its result is SOURCE_ONLY scoped structural/cron checking, not a full runtime census. Full live timer drift is NOT_MEASURED. Health-contract DRAFT refusals are retained and are not converted to REVIEWED.

No crontab, systemd, n8n workflow, live DB, release, broker, model routing, provider key, notification authority or workbook/Drive changes were made. No push, merge or deployment occurs in this shard. Integrator-owned external documentation append blocks: untracked `EXTERNAL_DOC_UPDATES_01.md`; inventory overlay: `/home/johnclaw/n8n-maturity-verification/refactor/inventory_rows_01.tsv`.

Rollback before release is to omit this local commit from the train, or revert its source changes. Because runtime is unchanged there is no scheduler rollback action for this shard. After a future authorized deployment, exact-SHA source rollback and the independently approved cron-lock packet rollback must be recorded separately; no ownership cutover is granted here.

## Final gate results

| Gate | Result | Evidence / scope |
|---|---|---|
| Lane registry, no exemptions, state drift | SOURCE_ONLY scoped check; final result in evidence summary | Approved scoped cron snapshot, no timers fabricated; 142 timer rows NOT_MEASURED. Initial six retry-class findings retained and corrected to existing policy none. |
| n8n health contracts | EXPECTED BLOCKED, exit 1 | Exactly six DRAFT_NOT_GRANDFATHERED findings for these six proposals. Existing global UNKNOWN fields are inherited, not introduced here. No operator review applied. |
| Data-source authority | PASS, exit 0 | findings=0, static source scan |
| Test coverage | PASS, exit 0 | registered shard suite; no new gap |
| Test host paths | PASS, exit 0 | new violations=0 |
| Dark contracts | PASS, exit 0 | no new undeclared writer |
| Docs inventory | PASS on initial run; final after this update recorded in summary | Index regenerated after staging new doc |
| Ruff | PASS on initial run; final after policy assertion recorded in summary | Changed Python files only |
| Shard and relevant existing tests | PASS: 79 passed, 74 deselected | Explicit fake DB/providers, scratch state, M2_SKIP_DOCKER=1, no actual DB/network/write capability blocks |

The untracked test bootstrap supplies an empty dotenv/absent-.env fixture for existing module import closures and installs explicit DB/network/production-write barriers; it prints every attempted prohibited capability. Final existing/shard test output records `TEST_BOOTSTRAP_CAPABILITY_BLOCKS=[]`. An initial bootstrap argument-name collision failed before collection and is retained in the initial log; the helper was corrected, no gate or test assertion was weakened. The source shared-test-bootstrap debt is listed for the integrator.

Initial targeted-test setup limitation: an earlier 43-test iteration used TRADE_AI_CI=1 and fake lane dependencies but omitted M2_SKIP_DOCKER and the pre-import capability traps. The inherited conftest maintenance-DB collection path was not instrumented there; whether any ambient attempt occurred/succeeded is NOT_MEASURED. It is not retroactively described as hermetic. The final 79-test run uses the explicit fixtures and traps described above and reports zero forbidden capability attempts. Source inspection found this setup debt and no shared code was modified to hide it.

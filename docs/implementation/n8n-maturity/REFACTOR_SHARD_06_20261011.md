# Shard06 cron writer preview and receipt proposal (2026-10-11)

Owner: Platform / Codex refactor-shard-06. Evidence: SOURCE_ONLY. State: local source proposal, not live.

Seven cron writers now accept strict `--dry-run` and return one plan before auth, DB, provider,
model or mutation work. Unknown and abbreviated flags exit 2. Fake real runs retain the existing
successful business argv, stdout and business calls, and add canonical LaneRunReceipt files.
Failures retain the previous `ok_at`; exception paths remain failures. Source-only allowlist and
registry rows describe dry_run W4 dispatch with scheduler wave R2-06, retry none and live_arg null.

Base: `9f602186a958df4c2d9f36f04a0ad1809bfce808`. The parent-approved scoped cron snapshot was captured `2026-10-11T17:05:28.513179+00:00`: seven selected full
lines and exact script arguments are frozen in `tests/fixtures/refactor_shard_06/approved_cron_argv.json`.
The full host cron census, coordination ledger, natural-schedule receipts, holidays and runtime
deletedAt state were not measured. No source proposal is a deployment or post-release proof.

| Lane | R1 class | Exact business argv | Receipt | Cron lock |
|---|---|---|---|---|
| finviz-market-movers | ingest | `(none)` | `data/runtime/finviz-market-movers_last.json` | `/tmp/finviz_market_movers.lock (observed)` |
| proposal-backtest-engine | learn | `--all-pending --apply` | `data/runtime/proposal-backtest-engine_last.json` | `/tmp/proposal_backtest.lock (observed)` |
| run-sec-form4-momentum-context | ingest | `--apply` | `data/runtime/run-sec-form4-momentum-context_last.json` | `/tmp/tradeai_sec_form4_ctx.lock (observed)` |
| social-ingest-stocktwits | ingest | `--source stocktwits --discover` | `data/runtime/social-ingest-stocktwits_last.json` | `/tmp/social-ingest-stocktwits.lock (proposed; absent from cron)` |
| instrument-belief-writer | learn | `--apply` | `data/runtime/instrument-belief-writer_last.json` | `/tmp/instrument-belief-writer.lock (proposed; absent from cron)` |
| sec-filings-feed | ingest | `--apply` | `data/runtime/sec-filings-feed_last.json` | `/tmp/tradeai_sec_filings_feed.lock (observed)` |
| trade-thesis-review-engine | learn | `--apply --json` | `data/runtime/trade-thesis-review-engine_last.json` | `/tmp/thesis_review_engine.lock (observed)` |

The explicit preview preserves `--apply` in the observed command and returns before work. On real
invocations, existing mutation rails still govern writes. Form4 returns 1 when DB/artifact/refresh
work fails instead of its old false-green 0; SEC feed returns 1 when every attempted company fetch
is unavailable; belief mutation refuses return 1. SEC ticker-map failure retains 2. Other legacy
failure exits are preserved. All deliberate changes have mocked coverage; no business run occurred.

Each new health contract remains DRAFT with CLASS_DEFAULT_PROVISIONAL, SOURCE_ONLY and
ledger NOT_MEASURED / runs_considered null. Freshness bounds are computed from the full approved
cadence over a fixed 21-day October calendar plus 2h, including weekend gaps; they require owner
review against holiday/calendar and real receipts. Existing REVIEWED aegis-nightly-ingestion and
validate-expense-ratios rows and contracts remain unchanged and are not counted as new admissions.

All seven env allowlists remain report while the shared lazy DB/provider/telemetry/cognition
closure is unmeasured. Own env reads select logical names; no broker env is admitted. The two
missing outer locks are proposed in the allowlist only: `/tmp/social-ingest-stocktwits.lock` and
`/tmp/instrument-belief-writer.lock`. Their cron packet, contract review and shared-closure proof
are prerequisites before canary. Real cron commands continue to do the work under their existing schedule.

Verification uses a minimal scratch environment, empty dotenv fixture and pre-import DB, socket
and production-file barriers. Profile subprocesses inherit those barriers even when a test builds
its own environment. The .nodeps bootstrap supplies missing packages; it is separate from the
safety guards. No real DB, production state, broker, sender or model access is authorized by tests.
The own shard test is registered in run_cio_hardening_ci.py and compares frozen old entrypoints
with each exact observed cron argv. Review refusal gates remain enabled.

The StockTwits marker selects the observed `--source stocktwits --discover` line. Its separate
`--source stocktwits --scalp-list` schedule was previously covered only by the broader marker.
One SOURCE_ONLY `social-ingest-scalp-hot` visibility row now records that exact approved line and
the existing code's receipt signal, with no dispatch, allowlist or health-contract admission and
no new authority. It is not an eighth candidate. Its argv, flag/window behavior and schedule remain
unchanged. The registry gate's initial mismatch and resulting undeclared sibling were corrected
by truthful source declarations; no gate or baseline exemption was relaxed.

All 37 assigned lanes are accounted for below. New-stage inventory changes apply only to seven
source-ready candidates. Sender/class exclusions, retired families, unresolved timer/route/behavior
closures and already-shadow main rows remain unchanged. Shared follow-ups and proposed locks
are recorded in the worktree handoff artifacts; the integrator serializes external shared docs.

| lane | class | result | lock needed | contract | notes |
|---|---|---|---|---|---|
| material-change-notifier-stage2 | SENDER | SKIP_SENDER | unchanged | unchanged | notify_material_change delivers notices through gateway |
| cio-delivery | SENDER | SKIP_SENDER | unchanged | unchanged | CIO delivery worker claims and delivers outbox messages |
| holdings-agent-enqueue | WRITER | BLOCKED(SYSTEMD_SHAPE) | unchanged | unchanged | systemd timer has no cron shadow admission shape; output enqueue is not runtime proof |
| data-source-health-audit | SENDER | SKIP_SENDER | unchanged | unchanged | systemd ExecStart check_data_source_health.py --alert |
| tradeai-aec-command-center-cycle | WRITER | BLOCKED(SYSTEMD_CHILD_CLOSURE) | unchanged | unchanged | systemd timer plus cross-library cognition/narrator closure |
| hermes-overnight-pipeline-night | WRITER | BLOCKED(SHARED_CHILD_CHAIN) | unchanged | unchanged | night manifest runs cross-shard business children; pipeline refactor owned separately |
| run-cio-event-detector-once-at-0-5 | WRITER | BLOCKED(RETIRED_FAMILY_ROW) | unchanged | unchanged | main RETIRED into cio-event-detector family; do not re-admit duplicate scheduler |
| tradeai-agent-runtime-hermes | DAEMON | BLOCKED(DISABLED_UNRULED) | unchanged | unchanged | main says disabled-unruled orphan persona; bounded run_once but no output; retain operator decision |
| finviz-view-contracts | READ_ONLY | SKIP_CLASS | unchanged | unchanged | systemd monitor is outside ingest/llm/learn classes |
| aegis-nightly-ingestion | WRITER | BLOCKED(ALREADY_SHADOW_MAIN) | unchanged | existing REVIEWED; untouched | main reviewed shadow row and allowlist untouched; no net new delivery |
| cio-lineage-completion-report | READ_ONLY | SKIP_CLASS | unchanged | unchanged | read-only lineage report is outside admitted R1 classes |
| finviz-market-movers | WRITER | SHADOW_READY | no | DRAFT | selected Finviz screen ingest writer |
| fred-data-ingest | WRITER | BLOCKED(BROKER_IMPORT_CLOSURE) | unchanged | unchanged | external_market_data_ingest shared helper carries direct broker credential/quote reach, reported by shard05; do not edit or investigate it |
| hermes-librarian-backlog-loop | WRITER | BLOCKED(SYSTEMD_SHAPE) | unchanged | unchanged | timer plus current dry path writes reports; needs owner-supported timer admission |
| hermes-score-alerts | SENDER | SKIP_SENDER | unchanged | unchanged | --send reaches send_telegram |
| holdings-llm-refresh | WRITER | BLOCKED(GOVERNED_ROUTE_EGRESS) | unchanged | unchanged | generate_cloud routes llm_lane in-process; prompt contains account and dollar exposure; separate governed route and egress work |
| iris-taxonomy-agent-at-0-10 | SENDER | SKIP_SENDER | unchanged | unchanged | Iris taxonomy modes contain direct Telegram sends |
| iris-taxonomy-agent-gaps | SENDER | SKIP_SENDER | unchanged | unchanged | Iris gaps mode sends taxonomy summary |
| iris-taxonomy-agent-freshness | SENDER | SKIP_SENDER | unchanged | unchanged | Iris freshness mode sends summary |
| iterate-research-topics | SENDER | SKIP_SENDER | unchanged | unchanged | optional --telegram sends; requires notification-intent/egress route separation |
| llm-intelligence-enrichment | WRITER | BLOCKED(GOVERNED_ROUTE) | unchanged | unchanged | generate_cloud routes llm_lane in-process, no proven cio-governed-bridge named route |
| llm-intelligence-enrichment-section | WRITER | BLOCKED(GOVERNED_ROUTE) | unchanged | unchanged | same shared in-process route; heavy wrapper iterates sections, preserve all cron parameters |
| oauth-lane-keepalive | SENDER | SKIP_SENDER | unchanged | unchanged | keepalive has Telegram stale alert and OAuth capability path |
| pattern-extractor | WRITER | BLOCKED(BEHAVIOR_WRITE_SEMANTICS) | unchanged | unchanged | pattern_library writes scoring_bonus/scoring_adjustment; needs owner proof of cognition-only consumer before dispatch |
| portfolio-level-qa | SENDER | SKIP_SENDER | unchanged | unchanged | operational QA failures/crashes send Telegram |
| proposal-backtest-engine | WRITER | SHADOW_READY | no | DRAFT | historical proposal backtest persistence admitted by operator ruling; never execution |
| proposal-lifecycle | READ_ONLY | SKIP_CLASS | unchanged | unchanged | CLI prints lifecycle strategy table, outside ingest/llm/learn |
| rotation-rebalance-digest | SENDER | SKIP_SENDER | unchanged | unchanged | digest sends Telegram |
| run-sec-form4-momentum-context | WRITER | SHADOW_READY | no | DRAFT | supporting SEC context writer only |
| social-ingest-stocktwits | WRITER | SHADOW_READY | proposed | DRAFT | StockTwits free ingest, preserve exact discovery args |
| topic-research-synthesizer-at-20-x | WRITER | BLOCKED(RETIRED_FAMILY_ROW) | unchanged | unchanged | main RETIRED into topic-research-synthesizer family |
| topic-research-synthesizer-reground | WRITER | BLOCKED(RETIRED_FAMILY_ROW) | unchanged | unchanged | main RETIRED into topic-research-synthesizer family |
| trade-thesis-review-engine | WRITER | SHADOW_READY | no | DRAFT | historical post-close review learning writer, no order or stop action |
| validate-expense-ratios | WRITER | BLOCKED(ALREADY_SHADOW_MAIN) | unchanged | existing REVIEWED; untouched | main reviewed shadow source remains untouched; script header reports broker read so no further investigation |
| instrument-belief-writer | WRITER | SHADOW_READY | proposed | DRAFT | settled belief cognition writer through existing behavior rail |
| sec-filings-feed | WRITER | SHADOW_READY | no | DRAFT | SEC filing event append writer |
| sector-momentum-engine | SENDER | SKIP_SENDER | unchanged | unchanged | sector transitions emit Telegram and dry-run currently reaches DDL/snapshot writes |

Status: DRAFT
as_of: 2026-10-11
Evidence: SOURCE_ONLY implementation; TEST_ONLY validation; OBSERVED_HOST approved cron command snapshot.

# Refactor shard 02 — source handoff

Branch: `n8nmat/refactor-shard-02`; base `7b36c98c32382b86c04bd5792927fc7c2bd1c729`. Not deployed. No cron/systemd/n8n mutation, model migration, secret read, broker change or policy ratification.

Seven explicit `--dry-run` entrypoints now print a structural plan before secret-file/DB/provider/telemetry access. Mutation flags lose to the dry guard; abbreviated and unknown arguments fail with usage exit 2. Real runs retain their cron argv and output and write canonical LaneRunReceipt@v1, carrying previous `ok_at` on failure. Regime and attribution retain their legacy receipt aliases for existing readers. RI partial builds and SEC document failures now propagate failure instead of reporting green.

The registry/allowlist contains source shadow candidates only: `live_arg: null`, `dispatch.mode: dry_run`, DRAFT health contracts. `scheduler.wave: R2-02` records shard provenance; `dispatch.wave: W4` uses the existing runtime enum. Health review/activation and two natural shadow fires remain outstanding. The health gate is expected to refuse these non-grandfathered DRAFT rows; no exemption or reviewer was added.

The source contract measures only this script's receipt; previous domain artifacts remain listed in `previous_output_signal`. Source attribution remains one stage of the live maturity/vetting cron chain. Its new receipt cannot prove the downstream steps. Weekly incubator's exact allowlist argv excludes `--llm`; no model/provider key is admitted.

Three future cron locks are proposed: build-lesson-candidates, sync-social-to-intelligence, weekly-incubator-builder. Reuse exact existing cron locks for regime, RI, attribution and SEC. The RI inner lock remains separate; a lock skip leaves a failed receipt with `lock_skipped` and does not advance health. Model-bound, broker, sender, timer and other-class lanes below are excluded from source admission.

## Per-lane disposition

| Lane | Class | Result | Reason / limit |
|---|---|---|---|
| governed-research-producer | WRITER | SKIP_CLASS | CIO persistent-wake producer; retain its agent-owned schedule, not a dispatcher lane. Existing --execute overrides --dry-run: separate owner fix needed; do not run. |
| ops-daily-digest | SENDER | SKIP_SENDER | External OpenClaw skill directly sends Telegram. |
| research-lane-health | SENDER | SKIP_SENDER | Systemd ExecStart --alert reaches send_telegram. |
| cio-memory-shadow-measure | WRITER | BLOCKED | Systemd measurement one-shot; no exact cron line for §3.7 and no dry-run/receipt contract. Timer-native recipe required. |
| cio-material-scan | SENDER | SKIP_SENDER | Systemd --live scan publishes office events; fabric observation writes remain reachable. |
| data-plausibility-audit | SENDER | SKIP_SENDER | Systemd --alert path sends Telegram. |
| aegis-surveillance | WRITER | BLOCKED | Systemd persona surveillance loop; repository unit missing and no exact cron line. Full import-time env load and stop-integrity observation require separate owner audit. |
| tradeai-agent-runtime-producer | WRITER | SKIP_CLASS | Agent-runtime shadow trigger producer; retain CIO/reactive authority and independent enabled-marker control. |
| tradeai-iris-taxonomy | SENDER | SKIP_SENDER | Taxonomy agent has multiple direct Telegram paths; repository systemd fragment missing. |
| goal-loop-baseline | WRITER | SKIP_CLASS | Measurement/report projection class is outside ingest|llm|learn; retain cron. |
| hermes-learning-pipeline-learn | WRITER | SKIP_CLASS | Manifest stage runner is an existing pipeline authority; do not relabel its multi-step process as a single ingest/llm/learn entry. |
| hermes-learning-pipeline-tune | WRITER | SKIP_CLASS | Existing manifest stage runner; ordered step receipts and per-step locks need a pipeline-specific recipe. |
| run-pullback-macd-screener | BROKER | SKIP_BROKER | Launcher enters dev tree and screener writes entry/stop/target trade plans and proposals; excluded financial path. |
| alert-dispatcher-unified | SENDER | SKIP_SENDER | Direct Telegram/email dispatcher; notification-intent migration is separate. |
| approval-reminder-reconcile | WRITER | SKIP_CLASS | Approval transport reconciliation projection, outside admitted classes; no authority conversion. |
| build-lesson-candidates | WRITER | SHADOW_READY | SOURCE_ONLY structural shadow candidate; DRAFT contract blocks activation. Legacy cron unchanged; natural runtime proof NOT_MEASURED. Proposed lock only; canary requires operator cron grant. |
| catalyst-momentum-engine-premarket | BROKER | SKIP_BROKER | Exact cron requests --generate-proposals; paper proposer child and broker-mode guard are present. |
| catalyst-momentum-engine-market | BROKER | SKIP_BROKER | Exact cron requests proposal generation; financial authority path excluded. |
| comms-lifecycle | WRITER | SKIP_CLASS | Retention/archive lifecycle hygiene, outside admitted classes; keep failure isolation. |
| directive-keyword-enhancer | WRITER | BLOCKED | LLM job uses in-process llm_lane OAuth calls, not proven host-service bridge; no safe dry-run/receipt yet. No model selection changed. |
| hermes-cross-source-synthesizer | WRITER | BLOCKED | --dry-run still reaches model synthesis via in-process governed_cloud_generation; host bridge and named DB settings need owner design. |
| hermes-discovery-ingestors | SENDER | SKIP_SENDER | Scheduled intake critical-error path directly sends Telegram and writes alert throttle state. |
| hermes-think-tank | BROKER | SKIP_BROKER | Real chain may invoke rotation_autopilot --tick --force-bridge; do not edit child financial paths. |
| market-regime-collector | WRITER | SHADOW_READY | SOURCE_ONLY structural shadow candidate; DRAFT contract blocks activation. Legacy cron unchanged; natural runtime proof NOT_MEASURED. Shared environment closure remains report-only and blocks canary. |
| multi-tier-trade-reviewer-weekly | WRITER | BLOCKED | Tier-specific model route and top-level full env loading are not a proven host bridge. Keep existing model authority; no provider chosen. |
| multi-tier-trade-reviewer-monthly | WRITER | BLOCKED | Same shared reviewer; model routing unproven and full env loading unresolved. |
| multi-tier-trade-reviewer-overnight | WRITER | BLOCKED | Same shared reviewer; in-process llm_lane route is not host-service routing proof. |
| options-lifecycle-digest | SENDER | SKIP_SENDER | Import-time daily_digest / _telegram path directly sends when policy enables it. |
| portfolio-lookthrough-themes | WRITER | BLOCKED | Exact cron --grok uses in-process model calls and an optional retired local fallback; no host-bridge proof. Dry preview may fetch fund holdings. |
| premarket-watcher | SENDER | SKIP_SENDER | Direct Telegram notifications; retain independent watcher. |
| research-intelligence-materialize | WRITER | SHADOW_READY | SOURCE_ONLY structural shadow candidate; DRAFT contract blocks activation. Legacy cron unchanged; natural runtime proof NOT_MEASURED. Shared environment closure remains report-only and blocks canary. |
| source-outcome-attribution | WRITER | SHADOW_READY | SOURCE_ONLY structural shadow candidate; DRAFT contract blocks activation. Legacy cron unchanged; natural runtime proof NOT_MEASURED. Canonical receipt proves this stage only, not later maturity/vetting chain steps. |
| sync-social-to-intelligence | WRITER | SHADOW_READY | SOURCE_ONLY structural shadow candidate; DRAFT contract blocks activation. Legacy cron unchanged; natural runtime proof NOT_MEASURED. Proposed lock only; canary requires operator cron grant. Shared environment closure remains report-only and blocks canary. |
| trade-close-llm-analyzer-source | BROKER | SKIP_BROKER | Broker-mode/live-trade review-adjacent path plus exact --allow-local-llm uses retired local model authority; excluded, no broker edits. |
| weekly-incubator-builder | WRITER | SHADOW_READY | SOURCE_ONLY structural shadow candidate; DRAFT contract blocks activation. Legacy cron unchanged; natural runtime proof NOT_MEASURED. Proposed lock only; canary requires operator cron grant. Shared environment closure remains report-only and blocks canary. |
| youtube-channel-discovery | SENDER | SKIP_SENDER | Exact cron includes --telegram; direct sender. |
| sec-fundamentals-ingest | WRITER | SHADOW_READY | SOURCE_ONLY structural shadow candidate; DRAFT contract blocks activation. Legacy cron unchanged; natural runtime proof NOT_MEASURED. Shared environment closure remains report-only and blocks canary. |

Counts: BLOCKED=8, SHADOW_READY=7, SKIP_BROKER=5, SKIP_CLASS=7, SKIP_SENDER=10. All 37 assigned lanes accounted for.

## Validation and recovery

Hermetic shard tests audit real CLI imports for secret-file, network/subprocess and file-write access; verify exact approved cron argv against archived original entrypoints; fake all real work and test success/failure receipts and original exit codes. Existing affected regression suites remain registered. Gate output is recorded in the untracked `REFACTOR_EVIDENCE_02.md` and `gate-logs-02/` handoff artifacts.

Gate results: 104 tests passed; lint, source authority, test coverage, host paths, dark contracts and docs index passed. The registry gate first found the inherited combined regime expression; the integrator confirmed this was schema-validation feedback, and it was normalized to the first exact five-field expression while preserving both observed schedules and command lines. No classifier or enum was weakened. The affected registry gate and targeted regression were rerun after that correction. Health gate remains blocked only on seven new DRAFT_NOT_GRANDFATHERED contracts; contract review and runtime activation remain operator work.



Validation isolation limitation: the initial 104-test run and initial targeted registry run inherited M2_SKIP_DOCKER unset. tests/conftest.py therefore invoked its maintenance-database setup helper before fakes; the helper can connect to the shadow container maintenance DB and create a dedicated test DB, and swallows connection errors. Whether that happened is NOT_MEASURED. No live DB was inspected or mutated to establish impact. Those earlier runs are not proof of hermetic collection.

The same scoped suite was repeated with a minimal environment, M2_SKIP_DOCKER=1, and the untracked refactor-test-bootstrap-02.py installed before pytest import. It supplies absent environment-file/empty dotenv fixtures, blocks DB connections, network sockets, host maintenance commands and production file reads/writes. Guarded result: 104 passed in 2.47s; TEST_BOOTSTRAP_CAPABILITY_BLOCKS=[]; the only dependency intervention was an absent .env fixture. This is TEST_ONLY proof with explicit fixtures, not retrospective proof about the earlier run. Final registry-admission and RI durable-root assertions were then rechecked under the same guard (2 passed); health contracts were rechecked after marking unmeasured ledger history explicitly and still refuse seven DRAFT rows.


The initial unapproved `crontab -l` read failed with `crontabs/johnclaw/: fopen: Permission denied`; that read stopped. The integrator obtained native operator approval for the same read and supplied a fresh scoped snapshot at 2026-10-11T14:57:08.697196+00:00. This shard used that snapshot and did not retry the refused operation.

Rollback before deployment: revert the shard commit. After separately granted exact-main deployment, roll back the source release/registry candidate entries through the normal operator release path; leave legacy cron active throughout. Do not delete receipts or reset their `ok_at`. Future cron lock changes require their own backup-and-restore packet; no such change was applied here.

The integrator merges the local branch into one train, resolves JSON rows without dropping another shard, runs train gates, and pushes once. The integrator alone rebuilds the workbook; Drive sync is separate. `SHARED_CHANGES_NEEDED.md`, `CRON_FLOCK_NEEDED.tsv`, `inventory_rows_02.tsv` and the append-only external documentation blocks are local handoff artifacts.

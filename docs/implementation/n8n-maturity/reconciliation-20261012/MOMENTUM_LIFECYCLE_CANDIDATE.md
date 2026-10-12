# Momentum lifecycle implementation and activation packet

This package adds a host momentum lifecycle monitor, an inactive n8n orchestration workflow, and a concrete gateway/relay/alerting integration diff. It is source preparation. The package does not activate scheduling, pause legacy triggers, review a contract, arm remediation, read a credential or call a model.

The user requested six-AM ET scanning, complete momentum lifecycle monitoring, governed LLM diagnosis and bounded self-healing, and shared Active Trader/Trade-AI advisory data. The six-AM requirement is a trading-day output expectation. The existing five-minute scalp live schedule retains its RTH market gate. A completed run with zero GO or proposals can be healthy.

## Source implementation

- `scripts/lib/n8n_momentum_lifecycle.py`: pure calendar/receipt/output evaluator, fixed-path read-only host collector, admission checks, stable incident findings, and deterministic bounded recovery planner.
- `scripts/n8n_momentum_lifecycle.py`: explicit fixture or host-metadata evaluation. `--write-monitor` writes only `data/runtime/momentum_lifecycle_last.json`; it requires enabled configuration plus operative monitor admission. `--dry-run` never writes or submits a run.
- `config/n8n_momentum_lifecycle_candidate.json`: disabled, disarmed, unreviewed candidate. Schedules come from the operative lane registry rather than duplicated forecast schedules.
- `workflows/tradeai-momentum-lifecycle-candidate.json`: inactive workflow; schedule -> authenticated relay due -> exact monitor-lane host run request, with parallel authenticated durable receipt readback. Errors use the existing `tradeai-incident-router`. Successful execution data is not retained. It holds only the existing relay credential reference and performs no external send, shell, model or secret action.
- `MOMENTUM_GATEWAY_INTEGRATION.patch`: five exact source diffs (zero context so the patch artifact itself has no trailing whitespace; apply with `git apply --unidiff-zero`) for the existing gateway library, HTTP gateway, relay, fan-in and host notifier. Shared originals remain unchanged in this worker checkout. The integrator applies and validates them on the final head.

The gateway addition is `coordination/status`, operation `momentum_lifecycle`, with existing HMAC `coordination_read` authentication. It rejects every extra request field, including caller paths, snapshots, enabled flags, review flags and recovery choices. The relay exposes authenticated `GET /momentum-lifecycle` with no query parameters. It uses the existing gateway transport and read claim. The provider uses the served code root and state root derived from existing gateway configuration; it requires actual operative monitor admission and rejects a missing, stale or wrong-SHA monitor receipt. Reading never writes or requests recovery.

The fan-in reads bounded monitor findings using the existing `scalp_lane`/SIEM mapping. The proposed host notifier adapter independently reads the same canonical source/item keys when n8n or the fan-in is unavailable. It cannot double an incident represented by both paths. Operator-action P1 rows preserve their classification and bypass the notifier's incident dedupe window. Stable durable incident keys do not grant notification suppression. Transport delivery, escalation and recovery still need an authorized host failure-to-notification proof.

## Host metadata contract

The collector reads only:

| Store | Collected evidence |
| --- | --- |
| `data/governance/n8n_coordination_ledger.sqlite` | Read-only bounded watched-lane census; run/lane/mode/slot/state/attempt/timestamps/exit/source identity. No log tail, prompt, account or credential fields are exported. |
| `data/runtime/momentum_lifecycle_inputs.json` | Host-owned sanitized business-output and completed credential-check metadata. A reviewed producer/projection adapter must publish this store. Missing metadata remains unproven. |
| `data/runtime/scalp_cycle_monitor_last.json` | Existing `ScalpCycleMonitor@v1` projection. Missing SLO values remain null; source-specific RTH missed-slot rules are reused. |
| `data/runtime/n8n_failure_diagnosis_last.json` | Existing diagnoser's bounded liveness/count status only. No model answer, evidence pack or action text is forwarded. |
| `/tmp` and state filesystem metadata | Free bytes/inodes. Zero capacity is FAILED; positive capacity alone does not establish a reviewed operating reserve. No file deletion or lock clearing is offered. |

Each business product must carry `available`, `run_id`, `run_date`, actual producer `source_sha`, aware `finished_at`, `basis=REAL_BUSINESS_OUTPUT`, `business_status=ok`, and explicit nonnegative population counts. A served cache must also carry `derived_from_run_id` matching the real scan package. `HEALTH_AUTOHEAL` timestamps do not prove business work. The producer source SHA is not inferred from a cache mtime or the monitor's own served SHA.

Under `population_contract=scan_partition`, `classified_total + manual_total == scanned_total`. Overlay universe/GO counts have separate populations. This accepts a 67-row scan partition of 44 classified and 23 manual rows without forcing the separate Active Trader universe to equal 67. Notification metadata must bind body, link and footer subjects consistently; incidents contain a finite reason code rather than those subjects.

Under `population_contract=shared_signal_union`, the product also requires `projection_hash`, `source_verdicts_preserved=true`, and `consumer_views.active_trader` / `consumer_views.trade_ai`, each with the same projection hash, run ID and business date. A newly authored shared API is not proof that both consumers read it. Pending Active Trader advisories remain pending; source verdicts, conflicts and timestamps remain visible. The monitor does not create GO, approve proposals, change watch subscriptions or duplicate the independent Active Trader alert path.

A `d:` coordination slot proves the requested slot, not that the n8n trigger was natural. Natural closure requires explicit `trigger_kind=NATURAL_SCHEDULE`, complete requested/started/finished chain, and matching receipt run/lane/slot/SHA/exit. Manual canaries, lock skips and unknown trigger provenance cannot close that requirement. Two completed run IDs in one slot require duplicate-effect inspection. Existing legacy work may have outputs while lacking n8n requests; `expected_fire_without_request` identifies the n8n ownership/evidence gap and does not assert that legacy business work never ran.

## Governed diagnosis and recovery

Existing `scripts/n8n_failure_diagnosis.py` already implements grounded, scrubbed host evidence -> governed process `n8n_lane_failure_diagnosis` / template `lane_failure_diagnosis.v1` -> strict bounded catalogue action -> deterministic handler -> `host_run_request` -> durable diagnosis/action receipts. The SIEM bridge folds diagnosis into the rows it owns, and the fan-in exposes low confidence/refusal/failure escalation. This implementation is reused rather than selecting a model or provider in n8n.

At this source base, `config/n8n_remediation_catalogue.json` is labelled **PROPOSED — operator review before activation**. Its implementation and action rows do not establish review authority. Lifecycle coverage records this boundary. `trade-ai-scalp-live` remains explicitly excluded from external LLM diagnosis by the existing catalogue library and is escalated. Financial proposal/promoter paths, senders, secret render, cookies, daemons, deletion, policy edits and arbitrary model-generated commands are never candidate recovery actions.

The source planner's only candidate recovery ID is `momentum-cache-reconcile`. It has no operative admission or helper here. No autonomous cache repair is claimed. A concrete reviewed safe cache-owner helper and output contract must exist before it can be admitted. The planner then still requires the actual registry ACTIVE/cutover stage, reviewed target contract with reviewer and deployed SHA, allowlist/live/flock admission, proven output dependencies, reviewed storage reserve, and original durable budget-slot history. It uses existing `class_verdict`/`next_attempt_at` policy, backoff, catch-up window and attempt caps. Polling cannot reset a slot or create fresh retry budgets. Deterministic request IDs are stable for a slot/attempt; the gateway/executor retain final admission.

FINVIZ_COOKIE remains in Bitwarden Secrets Manager. Its existing Command Center System > secrets host render/validator flow is an operator task. The existing credential-health API performs a live probe and is not called by this monitor. n8n reads only completed authorized nonsecret health metadata. It receives no item value, item ID, cookie file, provider credential or secret-render capability.

## Exact activation and rollback

`MOMENTUM_ACTIVATION_PACKET.json` records the 12 exact current source lane IDs, expressions, scheduler metadata, legacy trigger text, lock candidates and operative contract/allowlist state. It includes the complete proposed monitor registry/allowlist row and the exact existing diagnoser schedule. The continuous orchestrator parent and pipeline SLO population/calendar baseline remain explicit collection actions; there is no invented second orchestrator lane or zero-filled SLO.

`MOMENTUM_HEALTH_CONTRACT_PROPOSALS.json` contains 13 fully authored external DRAFT contracts, including the new monitor. Each defines purpose, declared owner and confirmation boundary, connections, healthy/degraded/failed criteria, provisional baseline/calendar/population rules, alerting, remediation, evidence and review date **2026-10-13**. Existing operative contract identity/review provenance is recorded and preserved. Missing acceptance remains `NOT_MEASURED`; no UNKNOWN placeholder passes as approval. At this source base, the catalogue has no operative `trade-ai-scalp-live` health contract; its proposal therefore requires an explicit review rather than assuming one exists.

The integrator must apply the shared integration diff and producer projection adapter, register these source/tests/docs, and run the native final-head profile. Activation requires actual per-process reviewer evidence, approved operative rows, exact-SHA release grant and CURRENT deployment, relay/workflow contract checks, authorized runtime validation, and the required natural shadow/canary/output/consumer/alert/recovery proofs. The staged source release SHA is left null until the final integrated head exists. Expired guard grants are not restored or inferred here.

Legacy triggers stay authoritative until their lane reaches GO. A scoped cron grant comments only the exact approved matching line after fresh host fingerprint/equivalence checks. Protected lanes remain watch/escalation unless their existing policy and mechanical admission are met. Retired midday orchestrator slots are not restored. Independent broker, safety, recovery and host P1 scheduling remain in place.

Rollback stops candidate scheduling first, restores only the affected archived legacy trigger, verifies one scheduler and the original lock, and proves output recovery. It never restores an entire crontab or discards incident/receipt history.

## Verification receipt

`TRADE_AI_CI=1 PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_n8n_momentum_lifecycle_20261012.py`: **43 passed**. The fixture suite executes the proposed gateway/relay/fan-in/notifier adapters in memory, exercises negative authentication/admission cases, storage/lock-create failure, incomplete/wrong-SHA/manual/duplicate receipts, stable retry budgets, same-day business freshness, valid distinct population counts, consumer lineage drift and operator credential tasks. All 13 contract structures validate with the existing health-contract validator.

`git apply --unidiff-zero --check MOMENTUM_GATEWAY_INTEGRATION.patch` passes against this source base. Shared originals, operative registry/allowlist/contracts, runtime, cookies and credentials were not changed. The system Python has no Ruff package; no dependency install was attempted. Final integrated native CI and any configured lint gate remain integrator checks. Runtime activation, host alert delivery, repair business output, natural schedules and final source/CURRENT identity remain unmeasured by these isolated fixtures.

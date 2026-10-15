# n8n contracts — design architecture

```
Status:      PROPOSED design (informational; AGENTS.md is normative). For external architect review.
as_of:       2026-10-15
Measured at: origin/main 94601ff69 (every schema id below verified by grep on that tree; see §15)
Owner:       platform (n8n maturity program); Chief Architect: Agent A
Policy:      AGENTS.md §23.23 (10.0.0, ACTIVE) and §23.24 (11.0.0, mandatory workflow framework)
Companion:   N8N_REFERENCE_ARCHITECTURE.md (planes, boundaries, lifecycle);
             scripts/check_n8n_workflow_framework.py (implements the element catalogue in §12)
```

Status markers: **(E)** exists on `origin/main`; **(P)** proposed, with its tracker item (`TRK-n` =
[`PROGRAM_TRACKER_20261015.md`](../../implementation/n8n-maturity/PROGRAM_TRACKER_20261015.md) row n; `GAP §n` =
[gap assessment](../../implementation/n8n-maturity/N8N_GAP_ASSESSMENT_AND_MATURITY_REVIEW_20261014.md); `FW-x` =
framework element, §12).

---

## 1. Executive summary

The n8n fabric is held together by **contracts, not by code sharing**: n8n workflows (JSON in a container) and host
services (Python) agree on a small set of versioned documents. This design names each contract, its schema id, the
file that owns it, who produces and consumes it, how it may change, where it is validated, and what happens when it
is violated. Ten contracts are in scope (§3–§11). Most exist (E); the gaps are the **workflow framework metadata**
(class, owner, stage, connects_to, runbook_id), the **expected-output rule** that makes "exit 0 but produced
nothing" a failure, the **approval/HITL** contract, the **n8n → LLM bridge** route, and **`p:` key validation** at
the gateway. Each gap is (P) with a tracker.

**Operator requirement (2026-10-15), first-class in this design:** *a run that exits 0 but produces nothing is a
FAILURE.* Concrete case: `scripts/hermes_research_worker_pool.py` ran hourly from July with exit 0 while every lane
reported `skipped: no_runner`; only the breach detector's `NO_OUTPUT` noticed. §5 (receipt) and §6 (health contract)
define the fields that make it detectable, and §12 element **FW-M6** fails any workflow whose contract has no
expected-output rule.

## 2. Contract map

| # | Contract | Schema id(s) | Owner file | Producer → consumer | Status |
|---|---|---|---|---|---|
| 3 | Workflow contract | `N8nWorkflowSet@v1`, `N8nGenericWorkflowSet@v1`, `N8nFabricManifest@v1`; metadata `N8nWorkflowFrameworkMeta@v1` | `scripts/n8n_workflow_templates.py` | generator → n8n import packet, drift check, framework checker | (E) sets; (P) metadata block |
| 4 | Run Lane request / result | `RunRequested@v1`, `RunOutcome@v1`, `FabricStepResult@v1`, `FabricProcessResult@v1`, `DueResponse@v1`, `N8nRunRelayLast@v1`, `N8nRunRelayRoutes@v1` | `scripts/lib/n8n_coordination_gateway.py`, `scripts/lib/n8n_fabric_store.py`, `scripts/n8n_run_relay.py`, generator | n8n ↔ relay ↔ gateway | (E) |
| 4 | Run keys | `d:` / `e:` / `g:` (`KEY_RE`), `p:` (`PROCESS_KEY_PREFIX`) | `scripts/lib/n8n_due.py`; generator | gateway / process workflow → ledger, executor | (E) d/e/g; (P) `p:` validation |
| 5 | Run receipt | `RunReceipt@v1`, `RunReceipt@v2`, `ExecutorStatus@v1`, `LaneRunReceipt@v1`; (P) `LaneRunReceipt@v2` | `scripts/n8n_run_executor.py`, `scripts/lib/lane_last_receipt.py` | executor / lane → ledger, fan-in, health monitors | (E); (P) output fields |
| 6 | Health contract | `N8nHealthContracts@v1` / `N8nHealthContract@v1`; (P) `expected_output` block `N8nExpectedOutput@v1` | `scripts/build_n8n_health_contracts.py`, `scripts/lib/n8n_health_contracts.py`, `config/n8n_health_contracts.json` | owner → checker, SIEM bridge, fan-in, framework checker | (E); (P) expected_output |
| 7 | Effect key | `EffectClaim@v1`, `N8nEffectKeys@v1` | `scripts/lib/effect_claim.py`, `config/n8n_effect_keys.json` | executor + cron wrapper → ledger | (E) code; inert for live until a lane opts in |
| 8 | Error workflow → incident | `CommsIntentReceipt@v1`, `N8nCommsIntentRoutes@v1`, `N8nCommsIntentConsumption@v1`, `N8nIncidentFanin@v1`; legacy `N8nCoordinationReceipt@v1` | `scripts/lib/n8n_fabric_store.py`, `scripts/lib/n8n_comms_intent_consumption.py`, `scripts/n8n_incident_fanin.py` | `tradeai-fabric-error` → relay → gateway → consumer → fan-in → notifier | (E) code; consumer not applied (TRK-16/25) |
| 9 | Notification intent | same `comms/intent` route; host-side intents (§24.1) | `config/n8n_comms_intent_routes.json`; `config/comms_categories.yaml` | any workflow → host comms gateway | (E) 3 fabric routes; (P) general workflow intents |
| 10 | LLM step | `LlmStepResult@v1`, `LlmStepAudit@v1`, `N8nLlmStepOutputSchemas@v1`, `N8nPromptTemplateSet@v1` / `N8nPromptTemplate@v1`, `N8nModelJobReceipt@v1`; process registry `config/llm_process_registry.json` | `scripts/lib/bridge_llm_step.py`, `scripts/lib/cio_governed_model_bridge.py`, `scripts/lib/llm_deferral.py` | process workflow → (P relay) → bridge | (E) bridge; (P) n8n reach |
| 11 | Approval / HITL | (P) `ApprovalRequest@v1`, `ApprovalDecision@v1`; existing `ApprovalPackage@v1` (host, operator packages) | (P) approval service; `scripts/lib/approval_package.py` | approval workflow → host approval service → operator | (P) |
| 11 | Allowlist / registry | `N8nRunAllowlist@v1`, `LaneRegistry@v1`, `N8nRetryPolicies@v1`, `N8nDueConfig@v1`, `N8nExecutorConfig@v1`, `N8nFabricProcesses@v1` | `config/n8n_run_allowlist.json`, `config/lane_registry.json`, `config/n8n_retry_policies.json`, `config/n8n_due.json`, `config/n8n_executor.json`, `config/n8n_fabric_processes.json` | reviewed PR → gateway, executor, `/due`, generator | (E) |
| 12 | Framework report | `N8nWorkflowFrameworkReport@v1` | `scripts/check_n8n_workflow_framework.py` | checker → CI, scorecard, (P) fan-in | (E) this PR |

## 3. Workflow contract

**What it is.** The committed workflow JSON plus its generator manifest. Every workflow is generated from git by
`scripts/n8n_workflow_templates.py` (per-lane: default command; generic: `build-generic`; fabric and processes:
`build-fabric`) and imported by a reviewed packet; it is never edited in the n8n UI (§23.23 governance (1)).

| Field | Where | Rule | Status |
|---|---|---|---|
| `id`, `name` | workflow JSON | stable; equals manifest row `id` | (E) |
| `active` | workflow JSON | always `false` in git; activation is a grant (`scripts/check_n8n_activation_grants.py`, `N8nActivationAttribution@v1`) | (E) |
| `settings.errorWorkflow` | workflow JSON | set on every workflow; new work → `tradeai-fabric-error` | (E) generic + fabric (`validate_fabric_workflow` `error_workflow_missing`); per-lane missing |
| `settings.executionTimeout` | workflow JSON | integer ≥ 1 | (E) generic + fabric |
| `settings.saveDataSuccessExecution` / `saveDataErrorExecution` | workflow JSON | `all` / `all` (`FABRIC_REQUIRED_SETTINGS`) | (E) fabric only |
| `meta.generator`, `meta.kind`, `meta.graph_sha256`, `meta.policy_sha256` | workflow JSON | graph hash re-computed by the trusted-deployer check (`build-fabric --verify`) | (E) fabric |
| manifest row `sha256`, `node_types`, `relay_calls`, `error_workflow` | `INDEX.json` | byte-stable regeneration (`--check`) | (E) |
| **`meta.framework`** (`N8nWorkflowFrameworkMeta@v1`) | workflow JSON | see below | **(P)**; first carrier: the reference mature workflow (§13) |

**`meta.framework` — the framework metadata block (P, FW-C1..C3, FW-A6, FW-R3, FW-R5):**

```json
{
  "schema": "N8nWorkflowFrameworkMeta@v1",
  "class": "business-critical | resilience | ai-llm | monitoring-compliance",
  "owner": "<role>",
  "stage": "shadow | canary | cutover",
  "connects_to": ["relay:POST /run", "relay:GET /run_outcome", "workflow:tradeai-fabric-run-lane", "lane:<lane_id>"],
  "runbook_id": "<id resolving to a runbook file>",
  "runbook_path": "docs/...",
  "health_contract_id": "<id in config/n8n_health_contracts.json, or a draft path>",
  "lanes": ["<lane_id>"],
  "effect_process": "<process id in config/n8n_effect_keys.json or null>",
  "rollback": "<the fallback: commented cron line or ROLLBACK_COMMANDS.md anchor>",
  "llm_steps": []
}
```

- **Producer:** the generator (a spec in git; never hand-written). **Consumers:** `scripts/check_n8n_workflow_framework.py`
  (scores it), the import packet (records class/owner), the fan-in (P: attaches `runbook_id` to pages).
- **Versioning:** additive optional keys keep `@v1`; a new required key, a renamed key or a changed enum is `@v2`
  (§14).
- **Validation point:** CI (`check_n8n_workflow_framework.py --strict` once §23.24 binds by code), generator
  self-check, trusted-deployer verify.
- **Failure behaviour:** a workflow without the block scores FW-C1/C2 fail and cannot be activated or promoted a
  stage once 11.0.0 binds by code (§23.24 "Activation bar"); the generator refuses to render a block whose
  `class` is outside the enum.

## 4. Run Lane request / result contract and run keys

**Request (n8n → relay `POST /run`).** Body keys exactly `RUN_BODY_KEYS` = `lane_id, mode, idempotency_key,
workflow_id, execution_id` (`scripts/n8n_workflow_templates.py`); relay bounds: `MAX_BODY` 1024 B, `RUN_MODES`
`dry_run|live`, lane id regex; gateway: HMAC claim scope `coordination_run`, allowlist, never-list,
`RUN_ID_RE = ^[A-Za-z0-9._:-]{16,128}$`, `requested_by: n8n:workflow:<id>`.

**Reply `RunRequested@v1`** (`scripts/lib/n8n_coordination_gateway.py`): run recorded REQUESTED; a repeated
`idempotency_key` returns the original row (no second run). **Refusals** are typed codes (gateway `REFUSALS`, relay
`REFUSALS`), never free text.

**Outcome `RunOutcome@v1`** (`scripts/lib/n8n_fabric_store.py`, relay `GET /run_outcome?run_id=`): `status ∈
{success, failed, refused_policy, skipped_lock}` terminal, `pending | unknown` non-terminal; plus `run_state`,
`exit_code`, `receipt_path`, `duration_s`, `effect_key`, `reason`, `attempt`, `finished_at`.

**Run Lane I/O** (`tradeai-fabric-run-lane`; generator `build_run_lane`): inputs `lane_id, mode, idempotency_key,
max_attempts (≤ 3), outcome_timeout_s (≤ 1000), process_id`; output one result with `status` from
`RUN_LANE_TERMINAL = (success, failed, refused_policy, skipped_lock)`; process workflows wrap each step's result as
`FabricStepResult@v1` and the run as `FabricProcessResult@v1`, adding `blocked` and `skipped_upstream`.

**Run keys.**

| Prefix | Shape | Minted by | Validated by | Status |
|---|---|---|---|---|
| `d:` | `d:<lane>:<mode>:<YYYYMMDDTHHMM local>[:a<n>]` | gateway `/due` (`slot_key`) — server-minted | `KEY_RE`, `is_server_minted` (`scripts/lib/n8n_due.py`) | (E) |
| `e:` / `g:` | same shape | event / generic sources of `/due` | `KEY_RE` | (E) |
| `p:` | `p:<lane>:<mode>:<slot>` | process workflow (`PROCESS_KEY_PREFIX`) | gateway accepts as a caller key; executor refuses a LIVE `p:` run (`effect_slot_unknown`) | **(P)** gateway validation against `config/n8n_fabric_processes.json` + manifest (TRK-21/33) |
| `fx:` | `fx:<process>:<slot>:<input_version>` | executor / `effect_claim.py run` | `effect_claim.py` | (E), §7 |

- **Versioning:** a key prefix is a closed set; a new prefix is a new `KEY_RE` and a `DueResponse@v2`
  (`docs/implementation/n8n-maturity/schemas/due-response.schema.json`).
- **Validation points:** relay (shape, size), gateway (scope, allowlist, key), executor (stage clamp, effect gate),
  `scripts/check_n8n_relay_contract.py` (every workflow HTTP node vs the relay route table).
- **Failure behaviour:** refusals are data (`refused_policy` in Run Lane; the process branch decides). A lost
  outcome is intent `run_lane_outcome_lost`. The legacy dispatcher still turns refusals into n8n errors (WS1b-07)
  — FW-A4 fails for it.

## 5. Run receipt contract — and "exit 0 with nothing produced is a failure"

**Executor receipt `RunReceipt@v1` / `@v2`** (`scripts/n8n_run_executor.py`, `RECEIPT_SCHEMA`,
`RECEIPT_SCHEMA_V2`; file `data/runtime/n8n_runs/<run_id>.json`): `run_id, lane_id, mode, requested_mode,
stage_clamp, state ∈ {RUN_DONE, RUN_FAILED, RUN_TIMEOUT, RUN_REFUSED, RUN_SKIPPED_LOCK}, exit_code, started_at,
finished_at, duration_s, output_signal, output_signal_mtime_before, output_signal_mtime_after, env_allowlist, effect,
attempt_states` (+ v2 dispatch fields: class, worker, verdict, DLQ/breaker). **(E)**

**Lane receipt `LaneRunReceipt@v1`** (`scripts/lib/lane_last_receipt.py`; `<state_root>/data/runtime/<lane>_last.json`):
`schema, lane_id, script, mode, status ∈ {ok, failed}, ok_at` (advances only on success), `exit_code, started_at,
finished_at, summary, error` (type name only). **(E)**

**The gap.** Today an exit-0 run is `RUN_DONE` / `success` whatever it produced. The mtime pair shows whether the
output signal *moved*, but a lane that rewrites its own receipt with `status: ok` and zero work moves it too (the
worker-pool case). The breach detector's `NO_OUTPUT` (`scripts/supervisor_breach_detector.py`, `Breach@v1`) fires
only when the signal is older than 3× cadence.

**(P) `LaneRunReceipt@v2` — additive output fields** (a v2 writer keeps every v1 field; v1 readers ignore the rest):

| Field | Type | Meaning |
|---|---|---|
| `produced_count` | int ≥ 0 | units of business output this run produced (rows written, items processed, files emitted) — the lane defines the unit in its contract (§6) |
| `attempted_count` | int ≥ 0 | units the run tried (so 0/0 "nothing to do" differs from 0/40 "everything skipped") |
| `skipped_reasons` | object reason → count | every skipped unit, by typed reason (e.g. `{"no_runner": 12}`) |
| `output_evidence` | list of `{kind: store_rows | file | receipt_field | ledger_row, ref, count, as_of}` | durable artifacts that would not exist had the work not happened (§0 rule 8) |
| `empty_reason` | string or null | when `produced_count == 0`: a typed legitimate reason (`market_closed`, `no_new_items`, …) or null |

**(P) Executor verdict on top of the receipt** (`RunReceipt@v3`, additive to v2: one new block `output_verdict`):

```json
"output_verdict": {
  "rule": "min_produced | per_window | empty_allowed",
  "produced_count": 0, "attempted_count": 12, "skipped_reasons": {"no_runner": 12},
  "verdict": "produced | empty_allowed | empty_violation | unverifiable",
  "contract_id": "<health contract id>"
}
```

- The executor reads the lane's `LaneRunReceipt` after exit 0 and evaluates the contract's `expected_output` rule
  (§6). `empty_violation` and `unverifiable` (rule declared but the receipt lacks `produced_count`) turn
  `RUN_DONE` into **`RUN_FAILED` reason `empty_output`** (or `output_unverifiable`), so `RunOutcome@v1` reports
  `failed` with that `reason` — no new outcome status, so Run Lane and every n8n Switch keep working unchanged.
- A dry run is exempt from `min_produced` (it must write nothing); it is checked for `attempted_count` instead.
- **Failure behaviour:** the run is a failure everywhere downstream (ledger, DLQ/breaker on v2, run outcome, Run
  Lane, error workflow intent, fan-in). The hermes worker-pool case — `produced_count 0`, `skipped_reasons
  {no_runner: N}` — is `empty_violation` on its first run.
- **Validation points:** executor (per run, P); health monitors (per window, P); framework checker FW-M6
  (contract declares the rule — **E in this PR**).

## 6. Health contract (REVIEWED / DRAFT lifecycle)

**Schema** `N8nHealthContracts@v1` document with `N8nHealthContract@v1` entries, built by
`scripts/build_n8n_health_contracts.py`, rules in `scripts/lib/n8n_health_contracts.py`, gate
`scripts/check_n8n_health_contracts.py` (codes `MISSING_CONTRACT`, `INVALID_CONTRACT`, `DRAFT_NOT_GRANDFATHERED`,
`DRAFT_AT_LIVE_STAGE`, `ORPHAN_CONTRACT`). 126 contracts on 2026-10-15: 65 REVIEWED, 61 DRAFT; `kind` lane (116),
generic_workflow (7), host_monitor (3).

| Field | Rule (E) |
|---|---|
| `id`, `kind`, `workflow_id`, `stage`, `owner`, `purpose` | required, non-empty |
| `connects_to[]` | `{name, kind ∈ service/runner/lock/receipt/store/provider/cron_twin…, direction, source}`; non-empty |
| `healthy[]`, `degraded[]`, `failed[]` | `{check, text}`; non-empty |
| `baseline` | `basis ∈ {OPERATOR_SLO, LEARNED_PROVISIONAL, CLASS_DEFAULT_PROVISIONAL}`, freshness bounds, `timeout_s`, `duration_degraded_above_s`, `class` |
| `alerting` | `lane_severity`, failed/degraded `notifier_priority` |
| `remediation`, `evidence`, `review_by`, `review` | evidence commands; `review_by` required for provisional baselines |

**Lifecycle.** `DRAFT` (built from sources, every edge unreviewed) → `REVIEWED` (the owner checked each field;
`review.reviewed_by`, `reviewed_on`) → re-review by `review_by`. A lane at canary or cutover needs REVIEWED
(`DRAFT_AT_LIVE_STAGE`); a new lane needs REVIEWED before its registry PR (only the 2026-10-10 set is
grandfathered). §23.24: a business-critical or AI/LLM workflow needs REVIEWED before it leaves shadow. The
operator's word "PROPOSED" for a contract change maps to a DRAFT entry; REVIEWED is the accepted state.

**(P) `expected_output` block (`N8nExpectedOutput@v1`) — required for FW-M6:**

```json
"expected_output": {
  "schema": "N8nExpectedOutput@v1",
  "unit": "research items written to ri_research_queue",
  "rule": "min_produced",
  "min_produced": 1,
  "window_h": null,
  "produced_field": "produced_count",
  "fatal_skip_reasons": ["no_runner", "no_credentials", "disabled", "unconfigured"],
  "empty_allowed_reasons": ["no_new_items", "market_closed"],
  "evidence": [{"kind": "store_rows", "ref": "Postgres ri_research_queue rows created_at >= started_at"}],
  "on_violation": {"run_state": "RUN_FAILED", "reason": "empty_output", "notifier_priority": "P2"}
}
```

- `rule`: `min_produced` (every live run must produce ≥ `min_produced`), `per_window` (≥ `min_produced` within
  `window_h`; for lanes that legitimately produce nothing on some runs), or `empty_allowed` (an explicit, reviewed
  statement that empty is normal — still requires `empty_reason` on an empty run). A contract with **no**
  `expected_output` fails FW-M6.
- A skip whose reason is in `fatal_skip_reasons` is a violation even under `empty_allowed`.
- `failed[]` gains the check `empty_output`, `healthy[]` gains `output_produced`.
- **Versioning:** the block is additive to `N8nHealthContract@v1` (optional in the schema); §23.24 makes it
  required by the framework checker, not by `check_n8n_health_contracts.py`, so no existing contract is broken by
  the schema. Making it schema-required is `N8nHealthContract@v2` after the 30-day remediation window.
- **Failure behaviour:** at review time FW-M6 fails (blocks activation once §23.24 binds by code); at run time §5's
  executor verdict fails the run.

## 7. Effect-key contract

`scripts/lib/effect_claim.py` (`EffectClaim@v1`; config `N8nEffectKeys@v1` in `config/n8n_effect_keys.json`).
Key `fx:<process>:<slot>:<input_version>`; states `CLAIMED, DONE, FAILED, UNKNOWN, RELEASED`; held states refuse a
second claim (`effect_already_claimed`); owner-epoch fence (`effect_no_owner`, `effect_fenced_owner`,
`effect_fenced_epoch`, `effect_fenced_stale_admission`); `set-owner` compare-and-swap; cron wrapper `run` exits 75
on refusal. Both tables live in the coordination ledger, one `BEGIN IMMEDIATE`.

- **Producer/consumer:** executor (live runs of listed lanes) and cron lines wrapped with `effect_claim.py run`.
- **Versioning:** the key format is closed; changing `input_version` in config deliberately opens new keys.
- **Validation point:** executor, before spawn; refused → `RUN_REFUSED effect:<reason>`, nothing runs.
- **Failure behaviour:** fail closed (no owner row → refuse; store unavailable → refuse). `UNKNOWN` (timeout) is
  never re-claimed without an operator release. FW-R6 checks that a live-capable workflow's lanes are listed.

## 8. Error workflow → incident contract

**Fabric path (E):** every fabric workflow sets `settings.errorWorkflow: tradeai-fabric-error` → Error Trigger →
shape → relay `POST /intent` with exactly `INTENT_BODY_KEYS = {domain, kind, subject, summary, workflow_id,
execution_id, node}` (subject ≤ 120, summary ≤ 300, control chars stripped, secrets redacted) → gateway
`comms/intent` (scope `comms_intent`) → `comms_intents` row QUEUED with `tier`, `runbook_id`, `dedupe_key`, `count`,
`routes_sha256` → `CommsIntentReceipt@v1`. Routing table `N8nCommsIntentRoutes@v1` is CLOSED: a `(domain, kind)`
without a row is refused `intent_unrouted`; `dedupe_window_s 3600`, `max_per_hour 30`; no PAGE tier (P1 never
depends on n8n). Consumer `scripts/n8n_comms_intent_consumer.py` (`N8nCommsIntentConsumption@v1`) turns QUEUED rows
into fan-in incidents (P2 digest) — merged, not yet served/applied (TRK-16, TRK-25).

**Legacy path (E):** `tradeai-incident-router` → relay `POST /event` (lane `n8n-workflow-error` only, body keys
`EVENT_BODY_KEYS`, message ≤ 160) → gateway `accept_event` → `N8nCoordinationReceipt@v1` → `N8nIncidentFanin@v1`.

- **Versioning:** a new `(domain, kind)` is a reviewed PR to `config/n8n_comms_intent_routes.json` (§24.1); a new
  body key is a relay + gateway change and a new route schema.
- **Failure behaviour:** the error workflow itself has no error workflow it can trust (self-reference); its
  failure is caught host-side by the fan-in from ledger/receipts — FW-A1 scores a self-referencing error workflow
  as fail with that reason. A refused intent is logged in `relay_log.jsonl` and is not retried by n8n.

## 9. Notification-intent contract

n8n decides **what** and **when**; the host decides **whether and how** (§24.1 superseded note, §23.23). Today the
only n8n-originated intents are the three fabric routes (`workflow_error` → `n8n-workflow-error`,
`run_lane_dead_letter` → `n8n-dlq`, `run_lane_outcome_lost` → `n8n-run-lost`, tier DIGEST). **(P)** business
notifications from process workflows use the same route with new `(domain, kind)` rows, each carrying
`runbook_id`; host-side senders emit intents (`category, severity, dedupe_key, as_of, body`) to the comms gateway
(§24.1 "Senders emit notification intents"; ratchet `notification_intent_baseline.json`). Validation: relay (keys,
bounds), gateway (route table, caps, dedupe), comms gateway (quiet hours, caps). Failure: refused intents are data;
P0/P1 never use this path.

## 10. LLM step contract

| Part | Contract | Owner | Status |
|---|---|---|---|
| Process registry | `config/llm_process_registry.json` entry: `id, allowed_lanes, max_input_tokens, max_output_tokens, daily_soft_cap, daily_cost_cap_usd, tools_allowed, fallback_allowed, advisory_only, circuit_breaker, offpeak_tier` | registry; bridge | (E); n8n processes `n8n_material_digest_draft`, `n8n_ops_summary_draft`, `n8n_lane_failure_diagnosis` |
| Template | `N8nPromptTemplateSet@v1` / `N8nPromptTemplate@v1` (`config/n8n_prompt_templates.json`: `material_digest_draft.v1`, `ops_summary_draft.v1`, `lane_failure_diagnosis.v1`), rendered server-side | `scripts/lib/n8n_model_job.py` | (E) |
| Output schema | `N8nLlmStepOutputSchemas@v1` (`config/schemas/n8n_llm_step_outputs.json`, e.g. `lane_failure_decision/v1`); closed; decision fields enumerated | `scripts/lib/bridge_llm_step.py` | (E) |
| Request | `POST /v1/llm_step {process_id, template_id, output_schema_id, allowed_values ⊆ enum, facts (provenance-wrapped), run_id, execution_id, budget}` — never a model, provider or key | bridge (`LLM_STEP_PATH`) | (E) on loopback `:8766` |
| Result | `LlmStepResult@v1` `status ok|refused`, typed refusal (`process_not_registered`, `schema_not_closed`, `over_cap`, `provider_outage`, …), `decision`, `host_recheck_required: true` | bridge | (E) |
| Audit | `LlmStepAudit@v1` one row per call (prompt hash, response hash, route receipts, decision, run_id, execution_id) | bridge | (E) |
| Caps | per-process `daily_cost_cap_usd`, per-call ceiling (routing policy `cost_ceiling_usd`), global `LLM_GLOBAL_DAILY_USD_CAP` | bridge | (E) |
| Deferral tier | `offpeak_tier ∈ {critical, standard, deferred}` (`scripts/lib/llm_deferral.py` `TIERS`) | registry | (E) field; (P) bridge-side deferral (GAP §5.3) |
| n8n reach | relay `POST /llm_step` (scope `llm_step`) or a scoped bridge token | — | **(P)** RP-B / Q1 in the reference architecture |
| Host re-check | gateway re-checks a recommended action (allowlist, stage, mode, catalogue) before any action | — | (P) |

**Workflow-side declaration (P, in `meta.framework.llm_steps[]`):** `{node, process_id, template_id,
output_schema_id, branch_fields[], offpeak_tier, hitl: "none | approval_request"}`. FW-G1..G7 check each entry against
the registry, the template set and the schema set. **Failure behaviour:** a refusal is data on an enumerated
branch; an AI/LLM exception (cap, schema, outage) is a typed event, P1 only when a business-critical process
stalls (§23.24 Alerting (5)); low confidence is data, not an alarm.

## 11. Approval / HITL contract and allowlist / registry contract

**Approval (P; TARGET_ARCHITECTURE §5).** `ApprovalRequest@v1 {kind, subject, payload_ref, workflow_id,
execution_id, expires_at}` → relay `POST /approval/request` → host mints `approval_ref`, records it, sends the
button through the comms gateway → `ApprovalDecision@v1 {approval_ref, decision, decided_by, decided_at, factor}`
recorded by the host → single-use execution-scoped resume token → gateway re-checks the action against the decision
record before acting. Money-class approvals are never this contract (operator assertion over `H(intent)` at the
execution service). Existing host-side packages (`ApprovalPackage@v1`, `scripts/lib/approval_package.py`) are the
operational-class precedent. **Failure behaviour:** fail closed — n8n down, token expired or record absent means
not approved; an n8n "approved" branch authorises nothing alone (§23.23 "Broker" (4)).

**Allowlist / registry (E).** `N8nRunAllowlist@v1` (`config/n8n_run_allowlist.json`): per lane `lane_id, command
(argv), lock, lock_kind, timeout_s, dry_run_arg, live_arg (null = refused), market_gate, output_signal, env_names,
env_allowlist_mode`, plus `blocked_reasons` and the `never` list. `LaneRegistry@v1` (`config/lane_registry.json`):
schedule, `scheduler.stage`, `dispatch` block (`scripts/lib/lane_dispatch.py`). Retry/due/executor configs:
`N8nRetryPolicies@v1` (`class_caps`, `breaker_threshold`), `N8nDueConfig@v1`, `N8nExecutorConfig@v1`. Processes:
`N8nFabricProcesses@v1`. **Validation:** gateway and executor re-read per request/drain (fail closed on unreadable),
`scripts/check_n8n_relay_contract.py`, registry checks in `scripts/run_cio_hardening_ci.py`. **Change:** reviewed
PR; adding a lane, widening the never-list exceptions or adding a live arg is an operator decision (§17, §23.14).
**Known gap:** live authority split across registry, relay live list and allowlist `live_arg` (WS1-07; P reconciler).

## 12. Framework element catalogue (implemented by `scripts/check_n8n_workflow_framework.py`)

Report schema `N8nWorkflowFrameworkReport@v1`. Each element yields `pass | partial | fail | n/a` with a reason.
Workflow elements score the workflow (pass = 1, partial = 0.5); **platform** elements are instance-wide facts,
reported once and not counted in a workflow's score (they cannot be fixed per workflow).

| Area | Id | Element | Offline check |
|---|---|---|---|
| Scope | FW-C1 | class declared | `meta.framework.class` in the enum |
| | FW-C2 | owner declared | `meta.framework.owner` non-empty |
| | FW-C3 | health contract (REVIEWED for BC/AI) | contract found for the workflow or its lanes; REVIEWED = pass, DRAFT = partial (fail for BC/AI past shadow) |
| Monitoring | FW-M1 | success evidence | `saveDataSuccessExecution: all` and every run request carries `workflow_id` + `execution_id` (or goes through Run Lane) |
| | FW-M2 | failure | `settings.errorWorkflow` set to a known error workflow |
| | FW-M3 | performance | `executionTimeout` set and contract `baseline.duration_degraded_above_s` |
| | FW-M4 | capacity | contract `baseline.class` in `config/n8n_retry_policies.json` `class_caps` |
| | FW-M5 | dependency | contract (or metadata) `connects_to` non-empty |
| | FW-M6 | **expected output** | contract `expected_output` with a valid `rule`; **missing = fail** |
| Alerting | FW-A1 | failure routed | error workflow is `tradeai-fabric-error` or `tradeai-incident-router`, not itself |
| | FW-A2 | SLA breach | contract freshness bounds + failed `notifier_priority` |
| | FW-A3 | performance degradation | contract duration bound + a `slow` degraded check |
| | FW-A4 | integration failure | refusals are data: run requests go through Run Lane (no Stop-and-Error on a refusal) |
| | FW-A5 | AI/LLM exception | (AI only) each LLM step declares an exception branch |
| | FW-A6 | runbook id | `meta.framework.runbook_id` declared |
| Logging | FW-L1 | execution saved | `saveDataSuccessExecution: all` |
| | FW-L2 | error saved | `saveDataErrorExecution: all` |
| | FW-L4 | security log | every HTTP node calls the relay base URL with the relay credential |
| | FW-L5 | change | file listed in a generator manifest and its sha256 matches |
| Recovery | FW-R1 | retry owner | Run Lane, or `retryOnFail` on HTTP nodes (partial for legacy) |
| | FW-R2 | breaker / DLQ | run requests go to the executor (ledger `breakers`, `dead_letters`) |
| | FW-R3 | fallback | `meta.framework.rollback` declared |
| | FW-R5 | manual recovery | `runbook_path` resolves to a file in the repo |
| | FW-R6 | idempotency | live-capable stage: every lane listed in `config/n8n_effect_keys.json`; shadow = pass (dry runs claim nothing) |
| Security | FW-S1 | authN | every HTTP node uses `httpHeaderAuth` `tradeai-run-relay`; webhooks have header auth |
| | FW-S2 | authZ | every lane named is in the allowlist; every relay call is in the relay route table |
| | FW-S3 | secrets | no credential other than the relay's; no secret-like literal in parameters |
| | FW-S4 | node types | node types ⊆ the fabric allowlist, none forbidden |
| AI/LLM | FW-G1..G7 | template, process, caps, schema, host re-check, deferral tier, HITL | (AI only) each `llm_steps[]` entry against the registries |
| Platform | FW-P1..P5 | instance success saving, n8n DB role not superuser, drift check scheduled with P1, firewall for the relay bind, pinned image + env hardening | platform facts file (measured values, cited) |

`--strict` exits non-zero when any workflow element is `fail`; the default is a report (exit 0).

## 13. The reference mature workflow

`docs/implementation/n8n-parallel/workflows/reference/tradeai-reference-mature-workflow.json` (INERT, `active:
false`, never imported) is generated by `scripts/build_n8n_reference_workflow.py` from the fabric helpers, carries
`meta.framework`, calls exactly one lane through Run Lane, treats refusals as data, sets every required setting,
and ships a REVIEWED-style contract draft with an `expected_output` rule and a runbook beside it. It passes every
workflow element the checker can evaluate offline.

## 14. Compatibility rules and the contract-change procedure

**Schema ids.** `Name@vN`. One document type per id; the id is a literal in the owner file (verified by grep).

**Compatibility rules.**

1. **Additive optional field** → same version. Every consumer ignores unknown fields; producers never rely on a
   consumer reading them.
2. **New required field, removed field, renamed field, changed type or changed meaning** → new major `@vN+1`.
   The producer dual-writes (or the consumer dual-reads) for at least one release; the old version is retired by a
   later PR, never by the same one.
3. **Closed enums** (run states, outcome statuses, refusal codes, intent routes, key prefixes, classes) are part of
   the contract. Adding a value that a consumer **branches on** (an n8n Switch, Run Lane's terminal list) is a
   breaking change → new version, unless the value maps to an existing branch (as §5 maps `empty_output` onto the
   existing `failed` status via `reason`).
4. **Refusal codes are data, append-only**; a code is never reused with a new meaning.
5. **Workflow graphs** are versioned by `graph_sha256` + `policy_sha256`; any change is a regeneration plus a reviewed
   import packet; the live graph must equal git (drift → P1).
6. **Authority-bearing contracts** (allowlist, never-list, registry live mode, comms routes, credentials, approval)
   change only by reviewed PR with the operator decision §17 requires; no contract change may widen authority as a
   side effect.

**Procedure (one PR per contract change).**

1. State the change, the schema id(s) and the compatibility class (rule 1 or 2) in the PR body.
2. Change the owner file constant, then every producer and consumer found by
   `git grep -n '<SchemaId>'`; for rule 2, implement dual-read/dual-write.
3. Update this document's row and §12 if an element changes; update `scripts/check_n8n_workflow_framework.py` and
   its tests.
4. Regenerate (`scripts/n8n_workflow_templates.py … --check`, `scripts/build_n8n_reference_workflow.py --check`,
   `scripts/regenerate_generated_files.sh`), run the relay contract check and the hermetic tests.
5. Dry run any runtime-affecting change and quote it (§0 rule 7); a live effect needs the grants §23.2 requires.
6. For workflow changes: import packet, drift check OK, activation grant naming the workflow ids.

## 15. Verification of schema ids (grep on 94601ff69)

Each id below appears as a literal in the named owner file: `N8nWorkflowSet@v1`, `N8nGenericWorkflowSet@v1`,
`N8nFabricManifest@v1`, `FabricStepResult@v1`, `FabricProcessResult@v1`, `N8nFabricProcesses@v1`
(`scripts/n8n_workflow_templates.py`); `RunRequested@v1`, `N8nCoordinationReceipt@v1`
(`scripts/lib/n8n_coordination_gateway.py`); `RunReceipt@v1`, `RunReceipt@v2`, `ExecutorStatus@v1`,
`N8nExecutorConfig@v1` (`scripts/n8n_run_executor.py`); `RunOutcome@v1`, `CommsIntentReceipt@v1`,
`N8nCommsIntentRoutes@v1` (`scripts/lib/n8n_fabric_store.py`); `N8nRunRelayLast@v1`, `N8nRunRelayRoutes@v1`
(`scripts/n8n_run_relay.py`); `DueResponse@v1`, `N8nDueConfig@v1`, `N8nRunAllowlist@v1` (`scripts/lib/n8n_due.py`);
`EffectClaim@v1`, `N8nEffectKeys@v1` (`scripts/lib/effect_claim.py`); `N8nHealthContracts@v1`
(`scripts/lib/n8n_health_contracts.py`), `N8nHealthContract@v1` (`config/n8n_health_contracts.json`);
`LaneRunReceipt@v1` (`scripts/lib/lane_last_receipt.py`); `LlmStepResult@v1`, `LlmStepAudit@v1`,
`N8nLlmStepOutputSchemas@v1` (`scripts/lib/bridge_llm_step.py`); `N8nPromptTemplate@v1`, `N8nModelJobReceipt@v1`
(`scripts/lib/n8n_model_job.py`); `N8nCommsIntentConsumption@v1` (`scripts/lib/n8n_comms_intent_consumption.py`);
`N8nIncidentFanin@v1` (`scripts/n8n_incident_fanin.py`); `N8nWorkflowDriftReceipt@v1`
(`scripts/check_n8n_workflow_drift.py`); `N8nActivationAttribution@v1` (`scripts/check_n8n_activation_grants.py`);
`Breach@v1` (`scripts/supervisor_breach_detector.py`); `LaneRegistry@v1` (`config/lane_registry.json`);
`N8nRetryPolicies@v1` (`config/n8n_retry_policies.json`); `ApprovalPackage@v1` (`scripts/lib/approval_package.py`);
`N8nWorkflowFrameworkReport@v1` (`scripts/check_n8n_workflow_framework.py`, this PR). **Proposed, not in code:**
`N8nWorkflowFrameworkMeta@v1` (carried only by the reference workflow and read by the checker),
`N8nExpectedOutput@v1` (read by the checker; carried only by the reference contract draft), `LaneRunReceipt@v2`,
`RunReceipt@v3`, `ApprovalRequest@v1`, `ApprovalDecision@v1`. The test
`tests/test_check_n8n_workflow_framework.py` re-greps the E list so this section cannot drift silently.

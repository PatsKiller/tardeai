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
| 4 | Run Lane request / result | `RunRequested@v1`, `RunOutcome@v1`, `RunLaneResult@v1`, `FabricStepResult@v1`, `FabricProcessResult@v1`, `DueResponse@v1`, `N8nRunRelayLast@v1`, `N8nRunRelayRoutes@v1` | `scripts/lib/n8n_coordination_gateway.py`, `scripts/lib/n8n_fabric_store.py`, `scripts/n8n_run_relay.py`, generator | n8n ↔ relay ↔ gateway | (E) |
| 4 | Run keys | `d:` / `e:` / `g:` (`KEY_RE`), `p:` (`PROCESS_KEY_PREFIX`) | `scripts/lib/n8n_due.py`; generator | gateway / process workflow → ledger, executor | (E) d/e/g; (P) `p:` validation |
| 5 | Run receipt | `RunReceipt@v1`, `RunReceipt@v2`, `ExecutorStatus@v1`, `LaneRunReceipt@v1`; (P) `LaneRunReceipt@v2` | `scripts/n8n_run_executor.py`, `scripts/lib/lane_last_receipt.py` | executor / lane → ledger, fan-in, health monitors | (E); (P) output fields |
| 6 | Health contract | `N8nHealthContracts@v1` / `N8nHealthContract@v1`; (P) `expected_output` block `N8nExpectedOutput@v1` | `scripts/build_n8n_health_contracts.py`, `scripts/lib/n8n_health_contracts.py`, `config/n8n_health_contracts.json` | owner → checker, SIEM bridge, fan-in, framework checker | (E); (P) expected_output |
| 7 | Effect key | `EffectClaim@v1`, `N8nEffectKeys@v1` | `scripts/lib/effect_claim.py`, `config/n8n_effect_keys.json` | executor + cron wrapper → ledger | (E) code; inert for live until a lane opts in |
| 8 | Error workflow → incident | `CommsIntentReceipt@v1`, `N8nCommsIntentRoutes@v1`, `N8nCommsIntentConsumption@v1`, `N8nIncidentFanin@v1`; legacy `N8nCoordinationReceipt@v1` | `scripts/lib/n8n_fabric_store.py`, `scripts/lib/n8n_comms_intent_consumption.py`, `scripts/n8n_incident_fanin.py` | `tradeai-fabric-error` → relay → gateway → consumer → fan-in → notifier | (E) code; consumer not applied (TRK-16/25) |
| 9 | Notification intent | same `comms/intent` route; host-side intents (§24.1) | `config/n8n_comms_intent_routes.json`; `config/comms_categories.yaml` | any workflow → host comms gateway | (E) 3 fabric routes; (P) general workflow intents |
| 10 | LLM step | `LlmStepResult@v1`, `LlmStepAudit@v1`, `N8nLlmStepOutputSchemas@v1`, `N8nPromptTemplateSet@v1` / `N8nPromptTemplate@v1`, `N8nModelJobReceipt@v1`; process registry `config/llm_process_registry.json` | `scripts/lib/bridge_llm_step.py`, `scripts/lib/cio_governed_model_bridge.py`, `scripts/lib/llm_deferral.py` | process workflow → (P relay) → bridge | (E) bridge; (P) n8n reach |
| 11 | Approval / HITL | (P) `ApprovalRequest@v1`, `ApprovalDecision@v1`; existing `ApprovalPackage@v1` (host, operator packages) | (P) approval service; `scripts/lib/approval_package.py` | approval workflow → host approval service → operator | (P) |
| 11 | Allowlist / registry | `N8nRunAllowlist@v1`, `LaneRegistry@v1`, `N8nRetryPolicies@v1`, `N8nDueConfig@v1`, `N8nExecutorConfig@v1`, `N8nFabricProcesses@v1` | `config/n8n_run_allowlist.json`, `config/lane_registry.json`, `config/n8n_retry_policies.json`, `config/n8n_due.json`, `config/n8n_executor.json`, `config/n8n_fabric_processes.json` | reviewed PR → gateway, executor, `/due`, generator | (E) |
| 12 | Framework report | `N8nWorkflowFrameworkReport@v2` (static conformance + five separate fields), `N8nFrameworkExceptions@v1`, `N8nFrameworkRuntimeEvidence@v1` | `scripts/check_n8n_workflow_framework.py` | checker → CI, scorecard, (P) fan-in | (E) this PR |

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
`idempotency_key` from the SAME request identity (lane_id, mode, requested_by) returns the original row with
`duplicate: true` (no second run); from any other identity it is `run_idempotency_conflict` with `conflict_fields`
(**corrected 2026-10-15, audit DD03**: it used to return the original row whatever lane/mode asked, a cross-scope
false success). The relay refuses unknown or duplicated `POST /run` body keys (`relay_unexpected_field`; the
accepted set is `RUN_BODY_KEYS` plus `requested_by`, which the ten generated per-lane workflows send and the relay
ignores) and a gateway reply naming another lane/mode/run (`relay_identity_mismatch`). A LIVE request from the relay
caller must carry a `d:`/`e:`/`g:`/`p:` key or the RELAY-MINTED `n8n-wf-<workflow_id>-<execution_id>` key (what a
body without `idempotency_key` gets; one per n8n execution; a caller-supplied key in that namespace is refused
`relay_bad_run_id`), else `run_key_namespace_refused`. Every active workflow's exact body is replayed through the
relay and the real gateway by `tests/test_n8n_audit_findings_20261015.py::test_active_workflow_run_bodies_*`. **Refusals** are typed codes (gateway `REFUSALS`,
relay `REFUSALS`), never free text. (E)

**Outcome `RunOutcome@v1`** (`scripts/lib/n8n_fabric_store.py`, relay `GET /run_outcome?run_id=`): `status ∈
{success, failed, refused_policy, skipped_lock}` terminal, `pending | unknown` non-terminal; plus `run_state`,
`exit_code`, `receipt_path`, `duration_s`, `effect_key`, `reason`, `attempt`, `finished_at`; additive since
2026-10-15: `identity {run_id, lane_id, requested_mode, requested_by, caller_id, slot_key, attempt}` (so a caller can
check the outcome is the one it asked for) and `retry` (the typed retry block below). (E)

**Run Lane I/O** (`tradeai-fabric-run-lane`; generator `build_run_lane`): inputs `lane_id, mode, idempotency_key,
max_attempts (≤ 3), outcome_timeout_s (≤ 1000), process_id`; output one `RunLaneResult@v1` with `status` from
`RUN_LANE_TERMINAL = (success, failed, refused_policy, skipped_lock)`; process workflows wrap each step's result as
`FabricStepResult@v1` and the run as `FabricProcessResult@v1`, adding `blocked` and `skipped_upstream`.

**Run keys.**

| Prefix | Shape | Minted by | Validated by | Status |
|---|---|---|---|---|
| `d:` | `d:<lane>:<mode>:<YYYYMMDDTHHMM local>[:a<n>]` | gateway `/due` (`slot_key`) — server-minted | `KEY_RE`, `is_server_minted` (`scripts/lib/n8n_due.py`) | (E) |
| `e:` / `g:` | same shape | event / generic sources of `/due` | `KEY_RE` | (E) |
| `p:` | `p:<lane>:<mode>:<slot>[:a<n>]` | process workflow (`PROCESS_KEY_PREFIX`) | gateway: `scripts/lib/n8n_process_keys.py` (spec + manifest, slot window, budget; #1760) + `:a<n>` only after a `retryable` predecessor; executor: every path refuses a row without the validated `slot_key` (`process_key_unvalidated`); host callers refused | (E). Earlier text here ("executor refuses a LIVE `p:` run") was wrong: only effect-keyed lanes checked it (audit DD03) |
| `fx:` | `fx:<process>:<slot>:<input_version>` | executor / `effect_claim.py run` | `effect_claim.py` | (E), §7 |

- **Versioning:** a key prefix is a closed set; a new prefix is a new `KEY_RE` and a `DueResponse@v2`
  (`docs/implementation/n8n-maturity/schemas/due-response.schema.json`).
- **Validation points:** relay (shape, size), gateway (scope, allowlist, key), executor (stage clamp, effect gate),
  `scripts/check_n8n_relay_contract.py` (every workflow HTTP node vs the relay route table).
- **Retry ownership (audit DD04, E):** one owner per namespace — `p:` → Run Lane (host never re-runs; gateway
  admits `:a<n>` only after a `retryable` verdict), `d:`/`e:`/`g:` → host policy (`coordination/due` RETRY_DUE),
  other keys → the executor's allowlist loop (v1). Every receipt (v1 and v2) carries `retry {owner, attempt,
  max_attempts, attempts_remaining, retryable, next_attempt_at, next_attempt_by, terminal_reason, dlq_ref, verdict}`
  and a terminal/exhausted run writes a durable `dead_letters` row named by `dlq_ref`. send/learn stay single-attempt
  under every owner. (P) Run Lane reading `retry.retryable` instead of its own rule (generator change + import).
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
`schema, lane_id, script, mode, status ∈ {ok, failed}, ok_at` (advances only on success), `exit` (the field is
`exit`, not `exit_code` as this document said before 2026-10-15), `started_at, finished_at, pid, summary, error`
(type name only). **(E)**

**Status 2026-10-15 (audit DD07): the executor verdict below is implemented (E)**, bound to the ATTEMPT: the
executor sets `TRADEAI_RUN_ID / _ATTEMPT / _MODE / TRADEAI_CODE_SHA` on the child; `write_lane_receipt(...,
produced_count=...)` writes `LaneRunReceipt@v2` with that identity and ALSO creates it once, immutably (`O_EXCL`),
at `data/runtime/lane_attempts/<lane>/<run_id>.json`; the executor reads only that file and requires its
`run_id`/`lane_id` to be the run's (a stale, concurrent-cron, v1 or other-lane receipt = `unverifiable`). Rules
are validated by one closed semantic schema (`scripts/lib/n8n_output_verdict.validate_expected_output`, shared
with FW-M6). No contract declares `expected_output` yet, so every run reports `output_verdict: no_rule` and is
unchanged. Remaining (P): dry runs are exempt (they write no receipt; captured dry evidence is not built), the
per-window rule is evaluated by monitors not per run, the verifier trusts the lane's own counts (an independent
query of the declared durable output is not built), and a lane writes v2 only once it is changed to pass
`produced_count`.

**The gap (as found).** An exit-0 run was `RUN_DONE` / `success` whatever it produced. The mtime pair shows whether the
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
- **Validation points:** executor (per run, **E** 2026-10-15); health monitors (per window, P); framework
  checker FW-M6 (closed semantic validation shared with the executor — E).

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
- **Corrections 2026-10-15 (audit DD05/DD06), (E):** `FAILED` was reclaimable after a possible effect (a target
  write followed by a non-zero exit reopened the key). Now a FAILED key is reclaimable only with `pre_effect = 1`
  (spawn failed, or a fence-declaring lane exited before passing the fence); every other failure is held like
  UNKNOWN until `release` (which now also accepts such FAILED keys). The owner-epoch fence acts at ADMISSION only;
  for late writes every claim hands the lane `TRADEAI_EFFECT_FENCE=<key>:<epoch>:<attempt>` (+
  `TRADEAI_EFFECT_FENCE_LEDGER`) and `effect_claim.assert_fence()` refuses a write after release, re-claim or owner
  switch. **Only lanes that call it are late-write safe**; `late_write_fenced: true` declares it and a test checks
  the lane source. A finish after the epoch moved is a late completion: `UNKNOWN`, `fenced_late = 1`, detail
  `late_completion:<state>`, receipt `effect.incident = effect_late_completion` (no longer a silent DONE).
  Residual: `release` still trusts the operator's note (no reconciliation evidence is required by code), and no
  lane yet calls `assert_fence`, so ownership switches still need drain-before-switch.
- **Effect-keyed lanes that do NOT call `assert_fence` (not late-write safe):** all 56 effect-keyed lanes in
  `config/n8n_effect_keys.json` (none declares `late_write_fenced`). The six whose executor side is armed
  (`n8n_claim` default true): `hermes-learning-outcome-grader`, `hermes-learning-outcome-learning`,
  `hermes-learning-config-governor`, `hermes-learning-tag-engine`, `hermes-learning-outcome-feedback-agent`,
  `hermes-learning-autonomous-self-tune`; the other 50 are staged (`n8n_claim: false`).

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
| Process registry | `config/llm_process_registry.json` entry: `id, allowed_lanes, max_input_tokens, max_output_tokens, daily_soft_cap, daily_cost_cap_usd, tools_allowed, fallback_allowed, advisory_only, circuit_breaker, offpeak_tier, reasoning_tier, escalate_below_confidence, escalation_confidence_field, escalate_on_values` | registry; bridge | (E); n8n processes `n8n_material_digest_draft`, `n8n_ops_summary_draft`, `n8n_lane_failure_diagnosis`; fabric process `hermes_tag_engine` |
| Routing | `config/llm_routing_policy.json` row with `route_profile: n8n_oauth_first`: `primary` grok OAuth → `secondary` chatgpt OAuth → `fallback` DeepSeek FAST, `transport_failover: true`, `reasoning_lane` DeepSeek `PRO_THINK`; registry `allowed_lanes` lists grok, chatgpt and the DeepSeek lanes, `deepseek_allowed_policies` FAST + PRO_THINK (pinned in agreement by `tests/test_n8n_oauth_first_routing_20261015.py`) | bridge (`route_plan`, `walk_routes`, `escalate_once`) | (E) |
| Escalation | `BridgeEscalation@v1` under `_tradeai.escalation`: `reason, outcome ∈ {escalated, escalation_skipped_cap, escalation_skipped, escalation_failed}, request_id (<rid>:esc1), parent_request_id, provider, model, projected_usd, cost_usd, reservation_id, oauth_answer{provider, model, response_sha256}`; `_tradeai.escalation_skipped_cap` boolean | bridge | (E) |
| Template | `N8nPromptTemplateSet@v1` / `N8nPromptTemplate@v1` (`config/n8n_prompt_templates.json`: `material_digest_draft.v1`, `ops_summary_draft.v1`, `lane_failure_diagnosis.v1`), rendered server-side | `scripts/lib/n8n_model_job.py` | (E) |
| Output schema | `N8nLlmStepOutputSchemas@v1` (`config/schemas/n8n_llm_step_outputs.json`, e.g. `lane_failure_decision/v1`); closed; decision fields enumerated | `scripts/lib/bridge_llm_step.py` | (E) |
| Request | `POST /v1/llm_step {process_id, template_id, output_schema_id, allowed_values ⊆ enum, facts (provenance-wrapped), run_id, execution_id, budget}` — never a model, provider or key | bridge (`LLM_STEP_PATH`) | (E) on loopback `:8766` |
| Result | `LlmStepResult@v1` `status ok|refused`, typed refusal (`process_not_registered`, `schema_not_closed`, `over_cap`, `provider_outage`, …), `decision`, `host_recheck_required: true` | bridge | (E) |
| Audit | `LlmStepAudit@v1` one row per call (prompt hash, response hash, route receipts, `route` {route_profile, reasoning_tier, served lane/provider, each lane tried with outcome and detail, escalated + why}, decision, run_id, execution_id); the model-job receipt `N8nModelJobReceipt@v1` carries the same `route` block | bridge; `scripts/lib/n8n_model_job.py` | (E) |
| Caps | per-process `daily_cost_cap_usd`, per-call ceiling (routing policy `cost_ceiling_usd`), global `LLM_GLOBAL_DAILY_USD_CAP` | bridge | (E) |
| Deferral tier | `offpeak_tier ∈ {critical, standard, deferred}` (`scripts/lib/llm_deferral.py` `TIERS`) | registry | (E) field; (P) bridge-side deferral (GAP §5.3) |
| n8n reach | relay `POST /llm_step` (scope `llm_step`) or a scoped bridge token | — | **(P)** RP-B / Q1 in the reference architecture |
| Host re-check | gateway re-checks a recommended action (allowlist, stage, mode, catalogue) before any action | — | (P) |

**Routing — operator decision 2026-10-15, verbatim:** "in terms of n8n, then, we should try OAuth first. And if OAuth fails or if the answer needs higher reasoning, then we go to DeepSeek."

How the bridge implements it for every `route_profile: n8n_oauth_first` row (`scripts/lib/cio_governed_model_bridge.py`):

1. **Default order.** grok OAuth, then chatgpt OAuth, then DeepSeek FAST. An OAuth lane the host has not enabled
   (`CIO_BRIDGE_OAUTH_TRANSPORTS`) is skipped with receipt outcome `no_transport` — not an error.
2. **Fallback to DeepSeek when OAuth fails.** Transport error, timeout, 401/403 (`auth_failure`), 429
   (`rate_limited`, Retry-After held), outage, and — new 2026-10-15 — an empty, non-JSON or schema-invalid answer
   (receipt outcome `output_invalid`, detail = the output-gate code) all move the walk to the next lane. A paid lane is
   never attempted twice in one call; a rejected paid answer is still metered on its receipt and settled.
3. **Higher reasoning, declared.** `reasoning_tier: "standard" | "high"` on the registry row; a template's
   `reasoning_tier` overrides it on the in-process `llm_step` path (the loopback model-job path uses the registry
   tier). `high` routes the row's `reasoning_lane` (DeepSeek `PRO_THINK`: thinking on, reasoning_effort high) first
   and the OAuth lanes after it. Every process is `standard` today.
4. **Higher reasoning, escalation.** A schema-valid OAuth answer whose closed output has `escalation_confidence_field`
   (default `confidence`) below `escalate_below_confidence`, or a field value listed in `escalate_on_values`, is
   re-asked ONCE on the reasoning lane: request id `<rid>:esc1`, its own reservation and provider-journal identity,
   inside the per-process daily caps and the per-call ceiling. If it does not fit, the OAuth answer returns with
   `escalation_skipped_cap`; if the escalation fails or is itself invalid, the OAuth answer stands
   (`escalation_failed`). Never a second escalation. `n8n_lane_failure_diagnosis` escalates below 0.7
   (= `CONFIDENCE_MIN`, V9 §6.4); the digest and ops-summary schemas have no numeric confidence, and no schema
   declares `needs_escalation` yet, so those two escalate only once a schema/template version adds that field.
5. **Audit.** Every lane considered has a `BridgeRouteReceipt@v1` (escalation receipts carry `attempt: escalation`);
   the decision (`route_profile`, `reasoning_tier`, served lane, `escalation`) is on `routing_decision`, in the
   `LlmStepAudit@v1` row and on the model-job receipt. Spend accounting is unchanged: OAuth $0 (`free_oauth_unmetered`,
   reservation settled at projection), DeepSeek metered.

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
`N8nFabricProcesses@v1`. **Validation:** the run allowlist is re-validated per request (gateway, relay) and per
claimed run (executor) — **corrected 2026-10-15 (audit DD08)**: it was in fact read once at gateway/relay start
and before the executor loop; the relay live-lane list and bearers are still process env read at start (restart
required; N8N_REFERENCE_ARCHITECTURE §8.1a) — an unreadable allowlist refuses every run,
`scripts/check_n8n_relay_contract.py`, registry checks in `scripts/run_cio_hardening_ci.py`. **Change:** reviewed
PR; adding a lane, widening the never-list exceptions or adding a live arg is an operator decision (§17, §23.14).
**Known gap:** live authority split across registry, relay live list and allowlist `live_arg` (WS1-07; P reconciler).

## 12. Framework element catalogue (implemented by `scripts/check_n8n_workflow_framework.py`)

Report schema `N8nWorkflowFrameworkReport@v2` (v1 until 2026-10-15; bumped because the score's meaning changed).
Each element yields `pass | partial | fail | n/a` with a reason. Workflow elements score the workflow (pass = 1,
partial = 0.5); **platform** elements are instance-wide facts, reported once, not counted in a workflow's score,
and gated (below).

**What the number is (third-party audit 2026-10-15, DD09/DD15/DD16).** The per-workflow and fleet percentage is
**static conformance**: the share of the offline predicates below that the committed artifact satisfies. It is not
operational maturity. It does not prove that a run succeeded, that an effect was safe, that recovery works, or that
the deployed copy equals the committed one. A 100% static score means every selected offline predicate passed —
not that every §23.24 obligation was checked. The obligations no offline check can prove are listed in §12.2 as
`not_checkable_offline` and reported per workflow as `UNPROVEN` until runtime evidence exists.

**Five separate fields per workflow, never folded into one number:** `artifact_integrity` (listed in a manifest,
manifest sha, `meta.graph_sha256` recomputed, byte-equal to a fresh render of its generator), `design_coverage`
(the static conformance score), `deployed_parity` (UNPROVEN until a drift receipt for the live copy exists),
`runtime_outcome` (UNPROVEN until every applicable runtime obligation has evidence) and `activation_eligibility`
(the gate below).

**Structural checks stand on the graph alone.** A hand edit can re-stamp both the manifest hash and
`meta.graph_sha256`, and a changed generator can re-stamp its own outputs; neither substitutes for a content check.
Positive evidence (a Run Lane call, a `run_id` record, result routing) counts only on nodes reachable from a
trigger. FW-L5 compares the file with a **fresh in-process render** of its generator, not with the manifest.

### 12.1 Elements

| Area | Id | Element | Offline check |
|---|---|---|---|
| Structure | FW-W1 | connections valid | every connection's source and target is an existing node; names unique |
| | FW-W2 | reachability | a trigger exists; every node is reachable from a trigger; no disabled node |
| | FW-W3 | required nodes on a path | a declared lane / effect process implies a run request; every Run Lane call / `POST /run` on a trigger path; every Run Lane call waits for the sub-workflow; the Run Lane result routed by a Switch on `status` whose `failed` and fallback outputs reach a throwing node (error route), whose refusal outputs reach a node, and whose success branch forwards the run result (no Code node asserting `status: 'success'`) |
| | FW-W4 | metadata = graph | recomputed `graph_sha256` and `policy_sha256`; declared lanes appear in a reachable node; `effect_process` is the effect-key process of a declared lane; every `llm_steps[].node` exists, is a reachable `POST /llm_step` node, and every LLM node is declared; manifest `node_types` / `relay_calls` / `error_workflow` equal the graph |
| Scope | FW-C1 | class declared | `meta.framework.class` in the enum |
| | FW-C2 | owner declared | `meta.framework.owner` non-empty |
| | FW-C3 | health contract bound | a declared `health_contract_ref` / `health_contract_id` must exist and bind this workflow id (no fallback to another contract); REVIEWED = pass, DRAFT = partial (fail for BC/AI past shadow) |
| Monitoring | FW-M1 | success evidence | `saveDataSuccessExecution: all` and a `$execution.customData.set('run_id', …)` statement (JS comments stripped) downstream of the Run Lane call on a reachable path (or ids in a reachable direct run body); the ledger join itself is runtime (23.24-M1a) |
| | FW-M2 | failure | `settings.errorWorkflow` set to a known error workflow |
| | FW-M3 | performance | `executionTimeout` set and a positive contract `baseline.p95_duration_bound_s` ≤ the timeout (a duration bound without p95 = partial); the measured p95 is runtime (23.24-M3b) |
| | FW-M4 | capacity | contract `baseline.class` in `class_caps`; start lag / enforcement runtime (23.24-M4b) |
| | FW-M5 | dependency | `connects_to` names every graph dependency: Run Lane id, error workflow, each relay route, each lane (missing = partial); stores are runtime (23.24-M5b) |
| | FW-M6 | **expected output** | closed `N8nExpectedOutput@v1`: no unknown keys; `rule` enum; `min_produced` integer (booleans refused) ≥ 1 for `min_produced`/`per_window`; `window_h` finite in (0, 744] only for `per_window`; `produced_field` a field name; `unit` non-empty; `fatal_skip_reasons` ⊆ closed enum and contains `no_runner`; `empty_allowed_reasons` ⊆ closed enum, ≥ 1 for `empty_allowed`, disjoint from fatal; every evidence item `{kind ∈ store_rows, receipt_field, ledger_row, file_artifact; ref}` and one `receipt_field` names `produced_field`; `on_violation = {RUN_FAILED, empty_output, P1|P2}`; **missing = fail** |
| Alerting | FW-A1 | failure routed | error workflow is `tradeai-fabric-error` or `tradeai-incident-router`, not itself |
| | FW-A2 | SLA breach | contract freshness bound + failed `notifier_priority` (the outside watcher is FW-P6) |
| | FW-A3 | performance degradation | contract duration bound + a `slow` degraded check |
| | FW-A4 | integration failure | through Run Lane AND the result Switch sends `refused_policy` / `skipped_lock` to nodes that never throw; a direct `POST /run` fails |
| | FW-A5 | AI/LLM exception | (AI only) each step's `exception_branch` is a node downstream of the LLM node |
| | FW-A6 | runbook id | `runbook_id` found in its `runbook_path` file or in `docs/runbooks/INCIDENT_RESPONSE.md` |
| Logging | FW-L1 | execution saved | `saveDataSuccessExecution: all` |
| | FW-L2 | error saved | `saveDataErrorExecution: all` |
| | FW-L4 | security log | every HTTP URL is exactly `={{ $('Relay').first().json.TRADEAI_N8N_RUN_URL }}/<path>` or `={{ $json.TRADEAI_N8N_RUN_URL }}/<path>` (no substring match), and every `TRADEAI_N8N_RUN_URL` assignment is an approved origin (`http://RELAY_HOST:18092` placeholder or `http://172.19.0.1:18092`) |
| | FW-L5 | change | byte-equal to a fresh in-process render of its generator (generic, fabric, per-lane, reference); a manifest sha alone is partial at best |
| Recovery | FW-R1 | retry owner | Run Lane (a `retryOnFail` on the Run Lane call itself = two owners = fail), or `retryOnFail` on HTTP nodes (partial for legacy) |
| | FW-R2 | breaker / DLQ | a run request on a trigger path goes to the executor; half-open is runtime (23.24-R2b) |
| | FW-R3 | fallback | `rollback` declared AND resolvable: every declared lane's registry scheduler is `cron` (the cron line is the fallback) = pass; only an existing cited file = partial; neither = fail |
| | FW-R5 | manual recovery | `runbook_path` exists and names the `runbook_id` |
| | FW-R6 | idempotency | `effect_process` must be a process in `config/n8n_effect_keys.json`; live stage: every lane keyed with `n8n_claim: true` (and `cron_claim: true` at canary, while the cron line can fire); shadow = pass with the unarmed lanes named |
| Security | FW-S1 | authN | every HTTP node: credentials exactly `{httpHeaderAuth: {id: tradeai-run-relay, name: tradeai-run-relay}}`, `authentication: genericCredentialType`, `genericAuthType: httpHeaderAuth`, no hand-set auth header, no redirect/proxy override; webhooks `authentication: headerAuth` with that credential |
| | FW-S2 | authZ | every lane named is in the allowlist; every HTTP call parses to a relay route in `ROUTES` (an unparseable URL is never a route) |
| | FW-S3 | secrets | no credential other than the relay's (type, id and name); no secret-like literal; no `$env` / `process.env` |
| | FW-S4 | node types | node types ⊆ the fabric allowlist, none forbidden |
| AI/LLM | FW-G1..G7 | template bound to the step's process and sent by the node, no inline prompt (G1); process id sent, no model/provider (G2); positive `daily_cost_cap_usd`, `max_input_tokens`, `max_output_tokens` (G3); schema registered for the process, sent, and closed — every decision field enumerated and required (G4); `branch_fields` ⊆ the schema's enumerated decision fields (G5); deferral tier (G6 — the off-peak rule, **not** §23.24 AI(6)); `hitl: approval_request` needs a served `POST /approval/request` on a reachable node; `hitl: none` on an action-bearing decision field = partial (G7) | (AI only) each `llm_steps[]` entry bound to a real reachable `POST /llm_step` node |
| Platform | FW-P1..P6 | instance success saving, n8n DB role not superuser, drift check scheduled with P1, firewall for the relay bind, image pinned **by digest** + env hardening (tag pin = partial), a dead-man outside n8n | platform facts file (measured values, cited) |

Critical elements (a PARTIAL blocks the gate): FW-W1..W4, FW-C3, FW-M2, FW-M6, FW-A1, FW-A4, FW-L5, FW-R6,
FW-S1..S4, FW-G1..G7.

### 12.2 §23.24 crosswalk (every obligation, line by line)

`OBLIGATIONS` in the checker, built line by line from AGENTS.md §23.24 with the third-party audit's policy
crosswalk (2026-10-15, `POLICY_CROSSWALK.md`) as the base: every row it marked absent or weakened is a row here.
`tests/test_check_n8n_workflow_framework_adversarial.py` holds this table and the code equal. `static` = a scored element; `platform` = an instance fact (reported, gated); `not_checkable_offline` =
UNPROVEN until the named evidence exists — never PASS offline, never silently omitted, never replaced by a weaker
predicate. Two rows are labelled extras (not §23.24 lines): the deferral tier and the graph-validity elements.

| Id | §23.24 obligation | Kind | Checked by / evidence that would prove it |
|---|---|---|---|
| 23.24-SC1 | every workflow in m8m-n8n is in scope (inventory complete) | **not_checkable_offline** | UNPROVEN until: live SELECT of workflow_entity (id, active) equal to the scored active set |
| 23.24-SC2 | one class in generator metadata | static | FW-C1 |
| 23.24-SC3 | one owner | static | FW-C2 |
| 23.24-SC4 | BC/AI need a REVIEWED health contract before leaving shadow | static | FW-C3 |
| 23.24-SC5 | relay routes, lanes, LLM steps and approvals it calls are in scope | static | FW-S2, FW-W4, FW-G7 |
| 23.24-M1a | every run joins a host ledger receipt by run_id | **not_checkable_offline** | UNPROVEN until: ledger runs rows joined to n8n execution custom data run_id for the window (no orphan either side) |
| 23.24-M1b | successful executions saved with run_id custom data | static | FW-M1, FW-L1 |
| 23.24-M1c | instance saves successes | platform | FW-P1 |
| 23.24-M2 | settings.errorWorkflow set | static | FW-M2 |
| 23.24-M3a | executionTimeout + contract duration bound | static | FW-M3 |
| 23.24-M3b | p95 duration measured against the contract bound | **not_checkable_offline** | UNPROVEN until: p95 of execution durations over the contract window, from saved executions or ledger runs |
| 23.24-M4a | run class has an executor class cap | static | FW-M4 |
| 23.24-M4b | start lag measured; caps actually enforced | **not_checkable_offline** | UNPROVEN until: executor receipts with admitted_at - requested_at, and a cap-refusal row under load |
| 23.24-M5 | connects_to names every route and store | static | FW-M5 |
| 23.24-M5b | stores written by the lane are all named | **not_checkable_offline** | UNPROVEN until: lane receipt store list (LaneRunReceipt@v2) compared with connects_to |
| 23.24-M6 | exit 0 with nothing produced is a failure (operator 2026-10-15) | static | FW-M6 |
| 23.24-M6b | an empty success fails the run at the host | **not_checkable_offline** | UNPROVEN until: RunReceipt with output_verdict empty_output -> RUN_FAILED for a forced empty run |
| 23.24-A1a | failure routed to the incident router / fan-in (design) | static | FW-A1, FW-W3 |
| 23.24-A1b | a forced failure reaches the fan-in and an incident | **not_checkable_offline** | UNPROVEN until: comms_intents / incident row for a forced failure execution id |
| 23.24-A2a | freshness bound + priority in the contract | static | FW-A2 |
| 23.24-A2b | SLA breach watched by a monitor outside n8n | platform | FW-P6 |
| 23.24-A3a | duration bound + slow check declared | static | FW-A3 |
| 23.24-A3b | p95 over the bound raises a P2 | **not_checkable_offline** | UNPROVEN until: P2 incident row raised by a slow-run drill |
| 23.24-A4 | refusals routed by class; a policy refusal is data | static | FW-A4 |
| 23.24-A5 | AI/LLM exception is a typed event | static | FW-A5 |
| 23.24-A5b | AI exception becomes a typed event, P1 on a BC stall | **not_checkable_offline** | UNPROVEN until: typed event row for a forced bridge refusal / cap hit on the step |
| 23.24-A6 | every page carries a runbook_id | static | FW-A6 |
| 23.24-A7 | delivery stays with the host comms gateway (no send node) | static | FW-S3, FW-S4 |
| 23.24-L1 | RunRequested/RunReceipt with requested_by n8n:workflow:<id> | **not_checkable_offline** | UNPROVEN until: ledger rows with schema RunRequested@v1/RunReceipt@v2 and requested_by = n8n:workflow:<id> |
| 23.24-L2 | errors saved | static | FW-L2 |
| 23.24-L3 | ledger is the audit of record; n8n DB role not superuser | platform | FW-P2 |
| 23.24-L3b | ledger audit actually records each run | **not_checkable_offline** | UNPROVEN until: coordination ledger audit rows for the workflow's runs in the window |
| 23.24-L4 | relay / CC auth refusals logged (all calls through the relay) | static | FW-L4 |
| 23.24-L4b | auth refusals appear in relay_log.jsonl | **not_checkable_offline** | UNPROVEN until: relay_log.jsonl refusal row for a bad-bearer probe |
| 23.24-L5a | generated from git | static | FW-L5 |
| 23.24-L5b | deployed copy never edited in the UI (parity) | **not_checkable_offline** | UNPROVEN until: N8nWorkflowDriftReceipt@v1 for this workflow id with no drift, from a host-scheduled read |
| 23.24-L5c | drift check scheduled outside n8n, pages P1 | platform | FW-P3 |
| 23.24-R1 | retry has one owner | static | FW-R1 |
| 23.24-R2a | breaker + dead letter (runs go to the executor) | static | FW-R2 |
| 23.24-R2b | breaker half-open behaviour | **not_checkable_offline** | UNPROVEN until: ledger breakers transition open -> half_open -> closed in a drill (WS1-05) |
| 23.24-R3 | declared fallback (cron line or ROLLBACK_COMMANDS) | static | FW-R3 |
| 23.24-R3b | fallback executed successfully | **not_checkable_offline** | UNPROVEN until: rollback drill receipt (CutoverReceipt@v1 rollback) for the workflow |
| 23.24-R4 | dead-letter | static | FW-R2 |
| 23.24-R5 | manual recovery runbook_id resolves | static | FW-R5, FW-A6 |
| 23.24-R6a | semantic effect key armed for live work | static | FW-R6 |
| 23.24-R6b | both schedulers respect the key; owner row present | **not_checkable_offline** | UNPROVEN until: effect_owners row + an effect_already_claimed refusal for a duplicate fire |
| 23.24-SEC1 | authN: relay bearer / webhook header auth | static | FW-S1 |
| 23.24-SEC1b | bearer rotation slot + gateway HMAC claim enforced | **not_checkable_offline** | UNPROVEN until: relay refusal for an old/forged bearer and gateway refusal for a bad HMAC claim |
| 23.24-SEC2 | authZ: allowlist + relay routes | static | FW-S2 |
| 23.24-SEC2b | one reconciled live authority (allowlist/relay/registry) | **not_checkable_offline** | UNPROVEN until: reconciler receipt (WS1-07) agreeing for every lane this workflow fires |
| 23.24-SEC3 | only the relay credential; no secret literal | static | FW-S3, FW-S4 |
| 23.24-SEC3b | env access blocked, community packages off, pinned image | platform | FW-P5 |
| 23.24-SEC4 | loopback / bridge binds; bridge bind firewalled | platform | FW-P4 |
| 23.24-SEC4b | ingested text treated as data | **not_checkable_offline** | UNPROVEN until: prompt-injection drill: injected instruction in facts yields no branch change |
| 23.24-SEC5 | activation grants name workflow ids | **not_checkable_offline** | UNPROVEN until: scripts/check_n8n_activation_grants.py attribution row naming this workflow id |
| 23.24-AI1 | registered template, never an inline prompt | static | FW-G1 |
| 23.24-AI2 | process id only; model/fallback from the registry | static | FW-G2 |
| 23.24-AI3 | per-process caps declared | static | FW-G3 |
| 23.24-AI3b | caps enforced; consumption ledger rows | **not_checkable_offline** | UNPROVEN until: LlmStepAudit@v1 rows and an over_cap refusal under a cap drill |
| 23.24-AI4 | closed output schema; branches on enumerated fields only | static | FW-G4, FW-G5 |
| 23.24-AI5 | host re-checks recommended actions; numbers grounded | **not_checkable_offline** | UNPROVEN until: gateway re-check refusal for an out-of-catalogue action; grounding refusal for an unsupported number |
| 23.24-AI6 | output guardrails: behaviour-field + prompt-injection scans | **not_checkable_offline** | UNPROVEN until: bridge step-9b behaviour-field refusal and an output injection-scan refusal (P) for the process |
| 23.24-AI7 | HITL: side effects behind an approval request | static | FW-G7 |
| 23.24-AI7b | approval authority = host record; fail closed when n8n down | **not_checkable_offline** | UNPROVEN until: forged / expired / replayed approval refused before effect (DD13 fixtures) and n8n-down drill |
| 23.24-BAR | no activation/promotion unless every element passes or has an operator-accepted exception | **not_checkable_offline** | UNPROVEN until: --gate activation exit 0 recorded by the import/activation packet, plus live active flag history |
| 23.24-BAR2 | the check runs live (SELECT only) on a host schedule, receipt read by the fan-in | **not_checkable_offline** | UNPROVEN until: host timer receipt of this checker in live mode read by scripts/n8n_incident_fanin.py |
| 23.24-DEV | extra: deferral tier (off-peak rule, not a §23.24 line) | static | FW-G6 |
| 23.24-STRUCT | extra (audit DD09): graph validity — reachability, required nodes on a path, metadata = graph | static | FW-W1, FW-W2, FW-W3, FW-W4 |

### 12.3 Modes

- Default: a report, exit 0. `--strict` is a CI lint: exit 1 when any workflow element is `fail` (PARTIAL and
  platform failures do not fail it — it is not a gate).
- `--gate activation` is the **fail-closed promotion gate** (DD16): exit 1 unless every workflow has no `fail`, no
  `partial` on a critical element, every platform element `pass` (missing facts = refused), and evidence for every
  applicable runtime obligation (`--runtime-evidence`, `N8nFrameworkRuntimeEvidence@v1`: `{workflows: {<id>:
  {<obligation id>: {ref, observed_at}}}}`), each unless an unexpired exception accepted by the operator in a PR
  names it (`--exceptions`, `N8nFrameworkExceptions@v1`: `{exceptions: [{workflow_id | "*", element, accepted_by:
  "operator", pr, expires}]}`). Offline with no runtime evidence nothing is eligible — the honest answer today.
- Callers: `scripts/check_n8n_import_ready.py --framework-gate activation` runs the gate before an import (opt-in
  flag; off by default). Not yet wired (documented, not modified): `docs/ops/packets/n8n-fabric-phase1-20261014/`
  `00_preflight.sh` and `01_import_inactive.sh` (call `check_n8n_import_ready.py` without the flag), and the
  operator's activation step (`n8n update:workflow --active=true` / publish in a packet under a `cron` grant, §23.2),
  which has no script of its own; `scripts/n8n_cutover_checklist.py` (promotion evidence) does not consult it. Each
  packet adopts the flag in its own reviewed PR; no exhaustive activation-path audit is claimed.

## 13. The reference mature workflow

`docs/implementation/n8n-parallel/workflows/reference/tradeai-reference-mature-workflow.json` (INERT, `active:
false`, never imported) is generated by `scripts/build_n8n_reference_workflow.py` from the fabric helpers, carries
`meta.framework`, calls exactly one lane through Run Lane, routes refusals as data and failures to the error route,
sets every required setting, and ships a contract draft with a closed `expected_output` rule and a runbook beside it.

**What it passes:** every static element the checker evaluates offline (31 of 31 applicable, AI elements n/a),
including the structural checks of §12.1 on its own graph — the strengthened checker needed no change to it.

**What it cannot prove (and why the gate refuses it):** it has never run, so every runtime obligation applicable to
it is UNPROVEN (M1a run_id joins, M3b p95, M4b start lag, M6b empty-output enforcement, A1b incident delivery, A3b
P2, L1 request/receipt actor, L3b ledger audit, L4b refusal logging, L5b deployed parity, R2b half-open, R3b
rollback drill, R6b effect owner row / duplicate refusal, SEC1b rotation + HMAC, SEC2b reconciler, SEC5 activation
grant, BAR); its lane's effect key is staged, not armed (`n8n_claim: false`), so it would FAIL FW-R6 at canary; its
rollback relies on the lane's cron line (the cited `docs/ops/ROLLBACK_COMMANDS.md` holds no n8n unpublish command);
and the instance it would run on fails FW-P1..P4 and FW-P6 and is tag-pinned (FW-P5 partial). `--gate activation`
on it exits 1 with 24 blocking reasons. It is a reference for a reviewer's diff, not evidence of maturity.

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
`N8nFabricManifest@v1`, `RunLaneResult@v1`, `FabricStepResult@v1`, `FabricProcessResult@v1`,
`N8nFabricProcesses@v1` (`scripts/n8n_workflow_templates.py`); `RunRequested@v1`, `N8nCoordinationReceipt@v1`
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
`N8nWorkflowFrameworkReport@v2` (`scripts/check_n8n_workflow_framework.py`; v1 until the 2026-10-15 audit fix). **Proposed, not in code:**
`N8nWorkflowFrameworkMeta@v1` (carried only by the reference workflow and read by the checker),
`N8nExpectedOutput@v1` (read by the checker; carried only by the reference contract draft), `LaneRunReceipt@v2`,
`RunReceipt@v3`, `ApprovalRequest@v1`, `ApprovalDecision@v1`. The test
`tests/test_check_n8n_workflow_framework.py` re-greps the E list so this section cannot drift silently.

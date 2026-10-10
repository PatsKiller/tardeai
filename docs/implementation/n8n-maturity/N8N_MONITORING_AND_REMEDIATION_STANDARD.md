# N8N monitoring, SIEM, Telegram and LLM auto-remediation standard — per lane

```
Status:      ACTIVE
as_of:       2026-10-10T17:30:00-04:00
Measured at: origin/main 2aa2cc37d (#1664) / live af292381c-main-exact-phase2-20261010-113824; host ms01-openclaw
Owner:       platform (n8n maturity program)
Policy:      AGENTS.md 4.4.0 §2A, §9.1, §9.3, §12, §23.3, §23.4 (where this differs, AGENTS.md wins)
Parent:      docs/implementation/n8n-maturity/N8N_ONBOARDING_STANDARD.md (steps 3, 7, 11)
Entry point: docs/implementation/n8n-maturity/N8N_CONFIGURATION.md
```

Operator, 2026-10-10 ~16:40 ET: *"Does the documentation also have clear guidance on how stuff should be monitored and
logged to the SIEM and how the auto-remediations with the LLMs should be set up for each?"* — and ~16:45 ET: *"there
should be something that's developed for each particular workflow: What is it supposed to do? What does it connect to?
What does positive mean? What does degraded mean? What is it measuring against if it doesn't know?"*

This file answers both, per lane. Each rule names the code or config that implements it and the test or gate that
proves it. Sources: REMEDIATION_PLAN §5 (L1–L8), §6 (R1–R7), §8; `V9-llm-self-remediation.md`;
`packets/siem-diagnoser-schedule/` (all in `~/n8n-maturity-verification/`).

---

## 1. The chain at a glance

```
lane run (executor) ──► coordination ledger runs (RunReceipt@v2) ──┐
lane receipt data/runtime/<lane>_last.json (LaneRunReceipt@v1) ──┤
n8n Error Trigger ─► incident-router ─► relay POST /event ─► gateway lane n8n-workflow-error ─┤ (fan-in reader: not built, §4.4)
                                                                     ▼
                        scripts/n8n_incident_fanin.py (*/5, n8n per-lane workflow 722fac0e043ea5c4)
                          │  data/runtime/n8n_incident_fanin_last.json (P1/P2/P3 incidents)
            ┌─────────────┴───────────────┐
            ▼                             ▼
 scripts/n8n_siem_bridge.py      scripts/incident_notifier.py (cron L1052) ─► send_system ─► SYSTEM ops Telegram
 system_health_events n8n:<lane>         (P1 now, P2 batched, quiet hours, cap)
            ▼
 scripts/n8n_failure_diagnosis.py ─► governed bridge (grok ─► chatgpt ─► deepseek) ─► catalogue action or escalation
            │ diagnoses.jsonl + receipt escalations ─► fan-in ─► notifier ; bridge folds diagnosis into the SIEM row
            ▼
 Command Center: System Hub (n8n:* rows), Operator Inbox (CRITICAL/URGENT)
```

No lane and no n8n node sends anything (AGENTS.md §23.3; `NODES_EXCLUDE` drops every Telegram, email, Slack and chat
node in the compose file).

---

## 2. What makes a lane observable (required before shadow)

| Signal | Where | Written by | Proves |
|---|---|---|---|
| `RunReceipt@v2` per run (state, exit, duration, `output_signal_mtime_before/after`, `stderr_tail`, `verdict`, `worker_id`) | coordination ledger `runs.receipt_json`, `$STATE_ROOT/data/governance/n8n_coordination_ledger.sqlite` | `scripts/n8n_run_executor.py` | that the executor ran it, and how it ended |
| Ledger states `RUN_DONE`, `RUN_FAILED`, `RUN_TIMEOUT`, `RUN_REFUSED`, `RUN_SKIPPED_LOCK` | same | executor | typed outcome, never a silent exit (§23.3) |
| `LaneRunReceipt@v1` `ok_at` | `$STATE_ROOT/data/runtime/<lane>_last.json` | the lane, via `scripts/lib/lane_last_receipt.py` `write_lane_receipt` | that the work landed; a failed run keeps the old `ok_at`, so a failing lane goes stale |
| Registry `output_signal` | `config/lane_registry.json` | — | the artifact the lane monitor and heartbeat check |
| Relay log `op: due` / `op: run` / `op: event` | `$STATE_ROOT/data/runtime/n8n_relay/relay_log.jsonl` | `scripts/n8n_run_relay.py` | dispatcher liveness; that n8n asked |
| Health contract | `config/n8n_health_contracts.json` | owner (drafted by `scripts/build_n8n_health_contracts.py`) | what healthy / degraded / failed mean for this lane (§3) |

**Never** use an n8n execution's status as evidence: `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none` soft-deletes successes,
which keep `status = 'running'` with a `deletedAt` value. Read `execution_entity` only with `"deletedAt" IS NULL`
(errors live there), and prove success from the ledger and the receipts (W0 rollback, RC8).

---

## 3. The workflow health contract (N8nHealthContract@v1) — one per lane and workflow

**File:** `config/n8n_health_contracts.json` (`N8nHealthContracts@v1`). **Schema, targets and validation:**
`scripts/lib/n8n_health_contracts.py`. **Builder:** `scripts/build_n8n_health_contracts.py`. **Gate:**
`scripts/check_n8n_health_contracts.py`, run by `tests/test_n8n_health_contracts_20261010.py` (GATES entry
`n8n_health_contracts_20261010`).

**Why a separate file, not a block on each registry row.** `scripts/reconcile_lane_registry.py` regenerates
generated rows, so a block on 55 rows would force each to be `adopted_from_generator` and travel through the
one-registry-PR-at-a-time train (§23.11); the six generic workflows are not registry rows; and a contract is
reviewed by its owner on its own `review_by` cadence. The gate joins the files, so nothing drifts silently.

### 3.1 Fields — the operator's five questions

| Question | Field | Content |
|---|---|---|
| What is it supposed to do? | `purpose.text`, `purpose.business_function`, `purpose.source` | one sentence; source = inventory row (`inv_id`) or code docstring; `UNKNOWN — needs owner` when no source says |
| What does it connect to? | `connects_to[]` `{name, kind, direction, source}` | relay → gateway → executor path; runner argv; lock; receipt; registry output_signal; upstream inputs (`read`), downstream outputs (`write`), external providers (`calls`). Inventory free text is `kind: inventory_text` and marked DRAFT |
| What does positive mean? | `healthy[]` `{check, text}` | e.g. live: last run `RUN_DONE`, output advanced, younger than 2× cadence, duration ≤ baseline. Shadow: dry_run `RUN_DONE`, dry run wrote nothing, the cron twin keeps the output fresh |
| What does degraded mean? | `degraded[]` | late (2×–3× cadence), slow (> p95 or > 80 % of `timeout_s`), retried or lock-skipped twice, upstream stale, deferred off-peak (`llm`) |
| What does failed mean? | `failed[]` | `RUN_FAILED` / `RUN_TIMEOUT` / `RUN_REFUSED`, no receipt, older than 3× cadence, breaker/DLQ, stale output (live) or a dry run that wrote (shadow) |
| What is it measured against? | `baseline` | `OPERATOR_SLO` (an operator-set number); `LEARNED_PROVISIONAL` (≥ 14 finished **live** runs in the ledger: p50/p95 duration, failure rate, retried runs; freshness 2× / 3× cadence); `CLASS_DEFAULT_PROVISIONAL` (fewer runs: duration degraded above 80 % of `timeout_s`, freshness 2× / 3× cadence). Dry-run fires never set a baseline. A provisional baseline carries `review_by` |
| How loud? | `alerting.failed` / `alerting.degraded` | `siem_severity` (CRITICAL / URGENT / WARN / INFO) and `notifier_priority` (P1 / P2 / P3). Lane severity Critical/High → failed P1; Medium/Low → failed P2; degraded one step lower (Critical → P2, others P3) |
| What fixes it? | `remediation` | catalogue entry, actions with their `auto` flag and approval reason, `diagnosis_excluded` |
| Who and how to check | `owner`, `evidence.verify[]`, `review_by` | read-only ledger, SIEM and receipt queries |

Freshness factors are the ones the host already uses: 2× cadence is `lane_registry.evaluate_lane` SLOW, 3× is the
fan-in stale threshold (`GOVERNANCE_STALE_FACTOR`, `DIAGNOSIS_STALE_FACTOR`).

### 3.2 Status and the gate

- `DRAFT` = built by the script from sources; nothing inferred is presented as reviewed. `REVIEWED` = the owner
  checked every field. The builder keeps `REVIEWED` contracts byte for byte.
- `scripts/check_n8n_health_contracts.py` **fails** on: `MISSING_CONTRACT` (any registry row at shadow / canary /
  cutover, a dispatch block not `off`, a staged `r1_pending` row, a live `kind: n8n` row, a host monitor, or a
  generic workflow, without a contract); `INVALID_CONTRACT` (empty purpose / owner / connects_to / healthy /
  degraded / failed, no baseline basis, no `review_by` on a provisional baseline, no notifier priority);
  `DRAFT_NOT_GRANDFATHERED` (a DRAFT for a lane not in the file's `grandfathered_draft` list — a new lane needs a
  REVIEWED contract before its registry PR); `DRAFT_AT_LIVE_STAGE` (canary or cutover with a non-REVIEWED contract
  or any UNKNOWN); `ORPHAN_CONTRACT`. It warns `REVIEW_OVERDUE`.
- **Filled 2026-10-10:** 68 contracts, all DRAFT and grandfathered: 59 lanes (the 4 live per-lane n8n lanes and 55
  shadow lanes of waves 1–3, incl. the 19 staged R1 rows), 6 generic workflows, 3 host monitors (SIEM bridge,
  diagnoser, incident notifier). Baselines: 4 `LEARNED_PROVISIONAL` (the 4 live lanes, 50 live runs each), 64
  `CLASS_DEFAULT_PROVISIONAL`. 4 fields carry UNKNOWN (no registry output path or inventory edge for
  `agent-calibration-engine`, `crawl-v3-dashboard`, `finviz-health-check`, `hermes-pipeline-health`). 177 of 499
  edges are inventory free text awaiting owner review. `review_by` 2026-10-24.

### 3.3 Not wired yet — the next build item

Nothing at runtime reads a contract today: the SIEM bridge takes severity from the registry row `severity`, else the
fan-in priority (`scripts/lib/n8n_siem_bridge.py` `severity_for` :121); the notifier routes on the fan-in priority;
the diagnoser's evidence pack holds the SIEM row, registry row, catalogue row and recent runs, not the contract.
Next build (each its own PR with tests): (1) the bridge reads `alerting.failed.siem_severity`; (2) the fan-in
evaluates `degraded` / `failed` checks with the contract baseline; (3) the diagnoser adds `purpose` and
`connects_to` to the evidence pack so the model diagnoses against intent (scrubbed like every other field).

---

## 4. Monitoring and SIEM, per lane

### 4.1 Failures become SIEM rows

- **Writer:** `scripts/n8n_siem_bridge.py` (logic `scripts/lib/n8n_siem_bridge.py`), the **single writer** of
  `system_health_events` rows with component `n8n:<lane_id>` (AGENTS.md §9.4). It reads the ledger `runs`
  (sqlite `mode=ro`), the fan-in receipt and the diagnoser's `diagnoses.jsonl`. `--dry-run` uses a read-only
  transaction; `--apply` writes. Exit 0 / 1 / 2 are honest; receipt `data/runtime/n8n_siem_bridge_last.json`
  (`N8nSiemBridge@v1`, `ok_at`).
- **Idempotency:** one active row per (`n8n:<lane>`, `event_type`); identical repeat → skip; changed severity or
  detail → update in place; volatile timestamps do not cause an update; a finding resolves
  (`lifecycle_state = 'resolved'`) only when its source is healthy (ledger kinds: the lane's latest finished run
  is good; fan-in kinds: a fresh fan-in receipt).
- **Kinds:** ledger `RUN_FAILED`, `RUN_TIMEOUT`, `RUN_REFUSED`, `NO_RECEIPT`, `STALE_OUTPUT`; platform
  `N8N_DOWN`, `RELAY_DOWN`, `EXECUTOR_STALLED`; fan-in items by source. Each carries a default remediation text
  (`DEFAULT_REMEDIATION`) unless the registry row has `remediation`.
- **Severity mapping** (stored in the table's vocabulary): registry `severity` Critical → CRITICAL, High → URGENT,
  Medium → WARN, Low → INFO; else fan-in priority P0/P1 → CRITICAL, P2 → WARN, P3 → INFO (`REGISTRY_SEVERITY`,
  `PRIORITY_SEVERITY` :56–57). Every ledger kind is P2 (`RUN_PRIORITY` :63).
- **Open gap L6:** only 2 of 619 registry rows carry `severity` (n8n-siem-bridge, n8n-failure-diagnosis: High), so
  **every other lane's RUN_* failure lands as WARN today**. When L6 lands, set `severity` (and `remediation`) on the
  registry row in a registry-train PR, copying the lane's catalogue severity and the contract's
  `alerting.lane_severity`; until then the contract records the intended severity.
- **Tests:** `tests/test_n8n_siem_bridge_20261010.py` (GATES `n8n_siem_bridge_20261010`),
  `tests/test_registry_siem_diagnoser_crons_20261010.py`.

### 4.2 Liveness and staleness

- The fan-in (`scripts/n8n_incident_fanin.py`) raises: executor status older than 2× the shortest n8n cadence;
  relay silent (2×); dispatcher silent; a scheduled monitor's receipt older than 3× its cadence; and for the
  diagnoser (R5, `_diagnosis_findings` :617) `diagnoser:receipt_missing`, `diagnoser:receipt_stale`,
  `diagnoser:cycle_not_ok` and `diagnoser:blind` (≥ 2 cycles with eligible incidents and no call, not deferred),
  each **P1**. Liveness starts only when the row is ACTIVE and not shadow.
- The heartbeat watcher's host lane (`heartbeat-watch`, not yet a registry row) will check every registry row's
  output_signal at 2× cadence, including stay-behind cron lanes (L4, L5); until it exists the supervisor breach
  detector timer and the lab watchdog (`tradeai-n8n-lab-watchdog.timer`, n8n `/healthz` every 5 min) cover it.

### 4.3 Telegram routing (L8) — one chokepoint

- **Only** `scripts/incident_notifier.py --live` (cron L1052, ACTIVE since 2026-10-09 23:34 ET, cron grant
  2db296cd0e9e6a10) sends, through `send_system` → the shared transport's SYSTEM ops family (comms editor, ops bot +
  ops chat, gated by `SYSTEM_TELEGRAM_ENABLED` / `SYSTEM_TELEGRAM_INTERDICT`). It reads the fan-in receipt and the
  ledger; it never names a token, chat or family.
- **P1:** at once, every un-notified P1 in one message per run, never held by quiet hours, **never capped**.
- **P2:** one batch at most every 30 min (`TRADEAI_INCIDENT_NOTIFIER_P2_BATCH_MIN`), **held 22:00–07:00
  America/New_York** (`..._QUIET_START` / `..._QUIET_END`, DST-safe), released as one batch at 07:00.
- **Cap:** 24 messages per ET day (`..._DAILY_CAP`); P1 and a recovery that includes a P1 are never capped; a capped
  message is `CAPPED` on the receipt and its incidents stay un-notified.
- **Dedupe:** per incident key `source|item` (day-independent) for 24 h; a worse severity re-notifies at once; a
  flap within 60 min of recovery is noted, not re-sent. **P3 never sends.**
- **Proof of delivery:** `data/cio/system_telegram_sends.jsonl` `ok: true` with a `message_id`; the notifier's
  receipt `incident_notifier_last.json` (`IncidentNotification@v1`) and history `incident_notifications.jsonl`.
- Defaults live in `scripts/incident_notifier.py` :79–99. A lane never sends Telegram itself (onboarding §2.7).

### 4.4 The n8n workflow-error path

n8n Error Trigger (incident router, `errorWorkflow` of the other five) → relay `POST /event` with
`{lane_id: "n8n-workflow-error", workflow_id, execution_id, node, message}` (ids regex-checked, node ≤ 64 and message
≤ 160 chars, control-stripped, secret-redacted; idempotency key `wferr-<wf>-<exec>`; one `op: event` relay_log line)
→ gateway `accept_event` on lane `n8n-workflow-error` (allowed by `TRADEAI_N8N_GATEWAY_EXTRA_LANES`, drop-in
`20-workflow-error-lane.conf`, 2026-10-10 16:27 ET) → a ledger event on lane `n8n-workflow-error`. **Open item:**
design 02 §8 says the fan-in reads these events as P2 (P1 for the dispatcher or watcher); `scripts/n8n_incident_fanin.py`
has no reader for them yet (measured 2026-10-10: no `n8n-workflow-error` reference), so a workflow error is recorded
but reaches neither the SIEM nor Telegram until that reader lands (fan-in PR with a test). Tests: `tests/test_n8n_w0_relay_fix_20261010.py`, `tests/test_gateway_workflow_error_lane_20261010.py`.
Until the release carrying #1663 is promoted, the served relay answers 404 on `/event`.

### 4.5 Where the operator sees it

- **System Hub** (Command Center v3): SIEM rows filtered by `n8n:*`, with stored severity and event type
  (`scripts/api_v2.py` :32973).
- **Operator Inbox:** `GET /api/v2/inbox` accepts `CRITICAL` / `URGENT` as well as legacy `P0` / `P1`
  (`scripts/api_v2.py` :32610, fixed in the SIEM bridge build, L7).
- **Telegram:** SYSTEM ops chat (§4.3).

### 4.6 How to verify one lane (read-only)

```bash
S=~/trade-ai-releases/persistent-state
sqlite3 "file:$S/data/governance/n8n_coordination_ledger.sqlite?mode=ro" \
  "SELECT state, mode, started_at, duration_s, verdict FROM runs WHERE lane_id='<lane>' ORDER BY requested_at DESC LIMIT 10"
jq '{ok, ok_at, status}' "$S/data/runtime/<lane>_last.json"
# SIEM, in a read-only session (SET default_transaction_read_only = on):
#   SELECT severity, event_type, lifecycle_state, created_at, left(message, 160)
#   FROM system_health_events WHERE component = 'n8n:<lane>' ORDER BY created_at DESC LIMIT 10;
jq '.by_severity, .ok' "$S/data/runtime/n8n_incident_fanin_last.json"
grep '"<lane>' "$S/data/runtime/incident_notifications.jsonl" | tail -3
python3 scripts/check_n8n_health_contracts.py
```

---

## 5. LLM auto-remediation, per lane

### 5.1 The catalogue — the only actions an LLM may choose

- **File:** `config/n8n_remediation_catalogue.json` (`N8nRemediationCatalogue@v1`, status PROPOSED — operator review
  before activation, decision 4). **Generator / validator:** `scripts/lib/n8n_remediation_catalogue.py`;
  **builder:** `python3 scripts/build_remediation_catalogue.py --dry-run | --write | --check` from the verified
  inventory, the registry and the allowlist.
- **2026-10-10:** 53 lanes (54 before the scalp exclusion, #1655); severity Critical 15, High 9, Medium 13, Low 16;
  45 suggest-only; 18 lanes carry actions; **8 lanes have an automatic dry-run rerun**:
  crontab-snapshot-for-health-agent, finviz-view-contracts, maturity-remeasure, n8n-pilot-dispatch,
  n8n-research-intake-consumer, n8n-selftest-fail, n8n-workflow-drift-check, source-attribution-monitor.
- **Action ids** (`ACTION_IDS`): `rerun_dry_run` (one `dry_run` request through the gateway's own
  `coordination/run` path, `host_run_request` — never a direct ledger insert); `rerun_dry_then_live` (only for a lane
  at `scheduler.stage == "cutover"`; none today); `reap_orphan_run` (a RUNNING row with no live owner, overdue 2× its
  timeout → `RUN_TIMEOUT executor_lost`). Handlers: `ledger_request_run`, `ledger_reap_orphan` only.
- **How a lane gets an entry:** it needs an allowlist entry with `dry_run_arg` (otherwise `suggest_only`, reason
  recorded); regenerate the catalogue after its allowlist PR. An action is `auto: true` only when the lane severity
  is Medium or Low (`AUTO_SEVERITIES`; Critical/High → human approval) and `timeout_s` ≤ 600
  (`MAX_AUTO_TIMEOUT_S`; e.g. `storage-watch` 1200 s → `auto: false`). Caps: 1 action per incident, 3 per lane per
  day.
- **Never in the catalogue:** broker, order, stop, secret actions; sends; deletes; crontab or systemd edits; unit
  restarts; DLQ releases; clearing a stale lock (report-only since 2026-10-09). **Never a live rerun** for a lane
  not at cutover; the executor's stage clamp runs a shadow lane dry whatever was requested.
- **Exclusions:** `DIAGNOSIS_EXCLUDED_LANES = {"trade-ai-scalp-live"}` (:70; operator ruling 2026-10-10 ~13:00 ET,
  #1655): broker-adjacent logs never go to an external model. The generator skips, the validator refuses, the
  diagnoser records `lane_not_in_catalogue`; the SIEM bridge, fan-in and notifier still cover the lane. **To add an
  exclusion:** a PR adding the lane id to that set, regenerating the catalogue (`--write`, then `--check`), and a test
  beside `tests/test_n8n_diagnosis_exclude_scalp_20261010.py`. Any broker-, order-, stop- or account-adjacent lane
  must be excluded before it can appear in the catalogue.
- **Open finding:** the catalogue is stale against the host inventory (REMEDIATION_PLAN §8); regenerate after each
  wave and before activation.

### 5.2 The diagnoser

- **Lane:** `n8n-failure-diagnosis`, `scripts/n8n_failure_diagnosis.py` (logic `scripts/lib/n8n_failure_diagnosis.py`),
  cron `3-59/15`, `--apply --max-incidents 3`, `timeout -k 30 600`, lock `/tmp/tradeai_n8n_failure_diagnosis.lock`.
- **Evidence pack (§2A decision 1: lane metadata, error text, logs only):** the SIEM row, the lane's registry row,
  its catalogue row and its recent ledger runs (RunReceipt incl. stderr/stdout tail). `scrub_text` / `scrub_obj`
  drop secret and portfolio keys at any depth (`PORTFOLIO_KEYS`), redact secrets, and withhold any log line naming a
  portfolio field whole; `egress_violations` refuses a pack that still carries one (`egress_refused`).
- **Model route (decision 2):** process `n8n_lane_failure_diagnosis` → `n8n_model_job.run_model_job` (template
  `lane_failure_diagnosis.v1`, output schema `lane_failure_diagnosis/v1`) → `cio_governed_model_bridge`: grok (OAuth)
  → chatgpt (OAuth) → deepseek FAST (metered). **Claude is not provisioned** in the bridge; provisioning a provider
  is operator-only (§17).
- **Caps:** $0.05 per call (`PER_CALL_CAP_USD` :35), $0.10 per day (`DAILY_CAP_USD` :36 = the process row's
  `daily_cost_cap_usd`), 40 calls/day soft cap, 12,000 input / 1,024 output tokens, ≤ 3 diagnoses per lane per day,
  one per incident; all inside `LLM_GLOBAL_DAILY_USD_CAP = 2.00`.
- **Registry is the source of truth** (`config/llm_process_registry.json`); the DB row is seeded by `_seed_registry`
  (#1651: new rows get lanes + cap, NULL caps filled, operator caps never overwritten). The diagnoser row was synced
  2026-10-10 16:27 ET to `{grok, chatgpt, fast, deepseek-flash}`, cap 0.10 (`packets/llm-seed-sync/`).
- **Off-peak:** the line runs behind `scripts/run_with_deepseek_offpeak.sh --scheduled --defer-in-process` (#1652).
  Out of window the wrapper prints `PEAK_DEFER_IN_PROCESS`, exports `LLM_DEFER_OFFPEAK=1` and runs the diagnoser,
  which defers the paid call in-process and still writes its receipt (`deferred` counted, not blind); the diagnoser
  escalates a **P2 `deferred_offpeak`** (`scripts/n8n_failure_diagnosis.py` :320), which the fan-in passes through. Without the flag the wrapper PEAK_SKIPs with exit 0 and no receipt, which
  the R5 check would page P1 every night (RC4). If `lib/llm_deferral` cannot load, it falls back to PEAK_SKIP. Use
  the repo wrapper: the older copy in `~/.config/tradeai/bin` (17 active crontab lines) has no `--defer-in-process`.
- **Verdict → action:** the strict JSON `{cause, confidence, action_id, rationale, citations}` is validated;
  `action_id` must be in the lane's catalogue row (or `suggest_only`) and every citation must name an evidence id.
  Confidence < 0.7 (`CONFIDENCE_MIN` :39) or ungrounded → **P1** escalation; a refused action or a failed
  remediation → P1; a suggestion → P2. Only an `auto: true` action executes, through the deterministic handlers.
  Model text is never a command.
- **Writes:** `data/runtime/n8n_diagnoses/diagnoses.jsonl` (`N8nLaneDiagnosis@v1`, append-only), the receipt
  `data/runtime/n8n_failure_diagnosis_last.json` (with `escalations`) and its state file. It **never** writes
  `system_health_events` (the bridge folds the diagnosis into the row: `‖ diag:` suffix) and never sends.
- **Tests:** `tests/test_n8n_llm_remediation_20261010.py`, `tests/test_n8n_diagnosis_exclude_scalp_20261010.py`
  (GATES `n8n_llm_remediation_20261010`), `tests/test_llm_process_seed_sync_20261010.py`,
  `tests/test_offpeak_wrapper_defer_in_process_20261010.py`.

### 5.3 What auto-remediation may never do

Run a lane `live` unless it is at cutover; touch a broker, order, stop, position or secret; send anything; edit a
crontab, unit, registry, allowlist or any config; restart a unit; delete anything; release a dead letter; clear a
lock; exceed a cap; send portfolio data to a provider (§2A); act on a lane in `DIAGNOSIS_EXCLUDED_LANES`.

---

## 6. R6 — per-lane validation (before a lane's cutover)

**Harness** (`~/n8n-maturity-verification/packets/siem-diagnoser-schedule/`): `r6_harness.py`, `r6_per_lane.sh`,
`r6_summary.py`, `r5_liveness_check.py`; lane `n8n-selftest-fail` (`scripts/n8n_selftest_fail.py`, arm
`--arm exit1 --count 1 --ttl-min 30 --dry-run` first, then without `--dry-run`; classes `ok`, `exit1`, `timeout`,
`no_receipt`, `stale_output`).

1. **Sandbox (no live write):** inject an exit-1 failure into a **copy** of the ledger; run the served release's
   bridge `--apply` into an in-memory DB (one `n8n:<lane>` RUN_FAILED row; second pass idempotent); run the diagnoser
   `--apply` with a fixture model and the paid call patched to raise (low confidence → P1; high → auto rerun
   requested in the sandbox ledger or suggest_only; cap reached → no call, P2); bridge fold (R3); fan-in
   `_diagnosis_findings` (P1 item); `incident_notifier.run(live=False)` with a raising sender (`p1:DRY_RUN`,
   `would_send: true`). Done 2026-10-10 for all 54 catalogue lanes: `evidence/r6_harness_report.json`,
   `evidence/r6_per_lane_summary.tsv`, 0 paid calls.
2. **Live (after install):** the first scheduled bridge `--apply` (SIEM rows), a real governed call with its
   `llm_consumption_log` row (`process_id = 'n8n_lane_failure_diagnosis'`), the row in System Hub and the Inbox, a
   Telegram `message_id` in `system_telegram_sends.jsonl`, and an executor run of a `rem-…-dry_run` request. The full
   S1–S8 selftest needs an allowlist + registry PR for `n8n-selftest-fail` first.
3. **Record to keep, per lane:** the R6 row (lane, failure class, SIEM row id or sandbox id, diagnosis id, cost,
   action/escalation, notifier result, date) linked from the lane's onboarding template (§7) and its health contract
   `evidence`.

---

## 7. Per-lane onboarding template (fill one per new n8n lane, keep it in the lane's PR)

| Field | Value |
|---|---|
| lane_id / n8n workflow id | |
| Health contract | `config/n8n_health_contracts.json#<lane>` status REVIEWED, owner, review_by |
| Purpose (one sentence) / business function | |
| Class / stage / wave | |
| Receipt path (`LaneRunReceipt@v1`) | `data/runtime/<lane>_last.json` (`ok_at`) |
| Registry `output_signal` | |
| Lock (= cron lock) / timeout_s | |
| Severity (Critical/High/Medium/Low) and basis | |
| Failed → SIEM severity / notifier priority | |
| Degraded → SIEM severity / notifier priority | |
| Catalogue entry? actions + auto? | |
| Excluded from LLM diagnosis? why | |
| Governed LLM route (llm class only) | process id, caps, off-peak flag |
| R6 evidence | sandbox report row / live ids |
| Rollback | registry PR / `_cutover.py rollback --lane` / packet rollback.sh |

---

## 8. Current state (2026-10-10)

| Item | State | Evidence |
|---|---|---|
| SIEM bridge row `n8n-siem-bridge` (`1-59/5`) | merged **PAUSED** (#1657), not installed | `packets/siem-diagnoser-schedule/` |
| Diagnoser row `n8n-failure-diagnosis` (`3-59/15`) | merged **PAUSED** (#1657), not installed; needs #1652 promoted | same |
| Install order (operator ruling) | bridge first, diagnoser ~2 h later; each under a `cron` grant; then a registry PR flips PAUSED → ACTIVE | packet README steps 3–6 |
| Incident notifier | ACTIVE (L1052) | registry #1654 |
| Catalogue | 53 lanes after the scalp exclusion; PROPOSED; stale vs host inventory | `config/n8n_remediation_catalogue.json` |
| Severity | 2 of 619 registry rows set → RUN_* lands WARN (L6 open) | §4.1 |
| Diagnoser DB row | synced 16:27 ET | `packets/llm-seed-sync/apply-20261010.txt` |
| Health contracts | 68 DRAFT, not read at runtime yet | §3 |
| Wrapper copies | 17 lines on `~/.config/tradeai/bin` copy (no `--defer-in-process`), 2 on the repo copy | crontab, measured 2026-10-10 |

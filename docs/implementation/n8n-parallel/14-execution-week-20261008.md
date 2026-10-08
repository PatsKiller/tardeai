# Execution plan — cron close-out and n8n Phase 2 in one week (2026-10-07 → 2026-10-14)

Operator decisions 2026-10-07 ~17:10 ET: (1) tranche B starts as soon as tranche C step 3 is done, not "from tomorrow"; (2) the roadmap's Phase 2 (`11-target-state-blueprint-20261007.md`, "days 31–90") is compressed: implement and test this week. DB tranches are finished (retention registry, archive-first trim, hygiene gate, nightly pipeline all live; the four duplicate price-table indexes stay unless the operator says otherwise).

Standing rails for every item: AGENTS.md §0 (MBI_BEHAVIOR = 0; dry-run before live; receipts not exit codes; never delete, archive; operator-only decisions §17). Grants per host change (cron / config-write / release-write), 30-minute windows. One registry-touching PR in flight at a time — two parallel agents conflicted on `config/lane_registry.json` and the GATES anchor twice on 10-07.

## Day 0 — Wed 2026-10-07 evening

| # | Item | Grant | Proof |
|---|---|---|---|
| 0.1 | Release #1482 + #1489 + #1490 (exact-main prepare/promote, operator runs with `!`) | release-write 2169ba15faa43edb | `health_tick_last.json` `ok: true`, `system-health-agent rc=0` on the next tick |
| 0.2 | Tranche C step 3: delete the 17 old lines + duplicate `db_retention` 04:10 line (`install_cron_tranche_c_step3.sh --apply`, backup first); registry: options-thesis-lifecycle / options-memory-projector / options-runtime-export / code-mirror-drive-sync → RETIRED `superseded_by`; prune baseline | cron | third-cycle receipts with `RAN` (no `LOCK_HELD`) for lifecycle / scalp / docs sync; `check_lane_registry --fail-on-new --state-drift` clean |
| 0.3 | Tranche B day 0: install **all nine stage lines in `--dry-run`** at their stage times (after_close close-capture / broker-truth / planning, premarket, hermes learn / tune / night / close) + repoint the three `DEV_TREE_WRAPPER` lines to CURRENT; declare the stage lanes ACTIVE (`scheduler.kind=cron`) in the same PR | cron (same grant if uses remain) | each `data/runtime/pipeline_<name>_<stage>_last.json` `PipelineRun@v1` with `mode: dry-run`; old lines untouched |

Compression rationale for 0.3: a `--dry-run` stage executes nothing and writes only its own summary, so all nine can observe in parallel; the design's "five days per stage" becomes two to three observed firings per stage, then cutover stage by stage.

## Day 1 — Thu 2026-10-08

- 07:00 ET: read `platform_maintenance_nightly_last.json` (first 01:15 run; 11 steps incl. db_retention and report_db_hygiene). Read `health_tick_last.json` after the release.
- Tranche B: first dry-run summaries from premarket 05:45 and the after-close stages at 16:05 / 16:30 / 17:30.
- **Phase 2 PR-A — notification outbox projection.** Dispatcher reads `communication_outbox` + `telegram_outbox` states (sent / SUPPRESSED / WITHDRAWN with reason) → `accept_event` per state change (artifact-stable timestamps); projection `/api/v2/coordination/events?source=outbox`; CC `/v3/coordination` tab. n8n never sends. Test: hermetic rows → events → projection.
- **Phase 2 PR-B — lane-registry drift events.** `check_lane_registry.py --state-drift --json` output → one event per NEW / drift finding (idempotency key = lane + finding), consumed by the incident fan-in (already live). Test: fixture registry with one drift → one event, second run → duplicate.

## Day 2 — Fri 2026-10-09

- **Phase 2 PR-C — approval board.** `approval_packages.jsonl` + guard grant state (scope, uses, expiry) → events; board on `/v3/coordination` with age and time-to-expiry; Telegram inline ack through the live callback poller → `consumer_ack`. Authority unchanged (grants and 2FA untouched). Test: expired package → event; ack → CONSUMED row.
- Tranche B cutover 1: `after_close --stage broker-truth` (2 steps) and `hermes_learning --stage learn` (4/6 verified) flip to `--apply`, absorbed lines commented with a dated tag, registry RETIRED rows, baseline pruned. Grant: cron.

## Day 3–4 — Sat/Sun 2026-10-10/11 (off-peak: paid-LLM work allowed)

- **Phase 2 PR-D — research intake chain.** `research_request` event (CIO wake / operator / Maria) → gateway → Trade AI consumer enqueues into `ri_research_queue` / Hermes under the existing caps → `run_id` receipt → consumer_ack. n8n never calls Hermes. Test: request → queue row → receipt; over-cap → typed refusal.
- **Phase 2 PR-E — governance packet + model job #1.** Weekly per-lane report (fire coverage, refusals) + monthly governance packet rendered by Trade AI scripts, state tracked as events. `model_job` #1 (material-change digest draft, deepseek-only, schema-validated) run on the receipts available now instead of waiting four weeks; fixtures valid / invalid JSON / over-cap / outage.
- Tranche B cutover 2: `close-capture` (13 steps) once p95 sum fits 1,680 s on the dry-run summaries; `planning` (14 steps).

## Day 5 — Mon 2026-10-12

- **Phase 2 PR-F — MCP read-only surface.** Only if the secrets ADR allows one scoped header credential in n8n; otherwise the same tools are exposed by the gateway over tailscale with HMAC claims and n8n is not involved. Tools: `coordination.status`, `list`, `incidents`. No MCP Client Tool.
- **DOF read-only views** only if decision 3 (dof_reader role + policy merge) has landed.
- Tranche B cutover 3: `premarket` (40 steps; the 06:10 pair measured by then), hermes `night` / `close` / `tune`.

## Day 6 — Tue 2026-10-13

- pgvector migration of `content_embeddings` jsonb → `vector(768)` + HNSW behind `ollama_embedding_policy` (Trade AI side; needs disk headroom check first; stretch item — if disk < 20 % free it is deferred with a finding).
- Buffer for anything that slipped; registry gate clean on the host; all tranche B stages cut over or explicitly deferred with a reason row.

## Day 7 — Wed 2026-10-14

- Week acceptance: served proofs for each PR (receipt or ledger row with source SHA), projection returns them, `check_lane_registry --fail-on-new --state-drift` clean, CI green, grant-bound promote. Memory + ledger updated. Crontab target: ≤ 300 job lines (from 477 this morning).

## Operator decisions this week needs

1. Secrets ADR status line → ACCEPTED (zero credentials) or "one scoped gateway key" (needed for PR-F).
2. DOF: `dof_reader` role + policy merge (PR-F's DOF views).
3. Whether to arm the health agent's self-heal retries (`sys.executable` instead of `.venv/bin/python`); today every retry is exit 127.
4. Optional: drop the four duplicate price-table indexes (DDL saved by db_trim).

## Not in scope this week

Any lane cutover into n8n (Phase 5 packet), queue mode, n8n AI Agent nodes, Slack/Teams/CRM.

## Model job #1 — how to run the first live draft (added 2026-10-08, G1)

Wiring now in the tree: process `n8n_ops_summary_draft` in `config/llm_process_registry.json` (deepseek-only, FAST, $0.10/day, soft cap 1/day, schema `ops_summary_draft/v1`); the bridge maps caller `n8n_model_job` + task type `ops_summary` to it server-side (`CALLER_TASK_PROCESS_MAP`), and both n8n model-job processes are in the bridge's policy map (they were registered but unmapped, so Step 3 refused them as `UNKNOWN_PROCESS` — the digest job could never have run live either). `scripts/report_lane_governance_packet.py --draft-mode plan` resolves mapping, registration, policy, caps and prompt size without a call.

Order, after the release that carries this change has re-resolved `cio-governed-bridge.service` (the bridge reads the registry and the map at start):

```
cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && set -a; . /run/user/$(id -u)/tradeai/env; set +a
export TRADEAI_STATE_ROOT=/home/johnclaw/trade-ai-releases/persistent-state PROJECT_ROOT=$PWD
PY=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python
$PY scripts/report_lane_governance_packet.py --write --period weekly --draft --draft-mode plan     # expect "ready": true
$PY scripts/report_lane_governance_packet.py --write --period weekly --draft                       # ONE live Flash call, ≤ $0.10
```

What proves it: `data/governance/ops_summary_draft_weekly_<YYYY-Www>.json` with `receipt.state == "ARTIFACT_WRITTEN"`, `receipt.cost.settlement == "MEASURED"` and `receipt.cost.provider_cost_event.client_request_id` equal to the job's `correlation_id` (`corr-ops-weekly-<key>`); `lane_governance_packet_last.json.ops_summary.state`. Correction 2026-10-08 (Agent C, Day 0): `--draft` does **not** call `n8n_model_job.write_receipt` — `draft_ops_summary` embeds the full `N8nModelJobReceipt@v1` under `receipt` in the `data/governance` artifact and updates the packet receipt, nothing else. `data/runtime/n8n_model_jobs/<correlation_id>.json` is written only by the coordination gateway's `model_job` operation. Three defects that refused every live draft were fixed in the same PR (`fix/n8n-model-job-live-shape`): (1) the bridge returns `governance_pass`, `process_id`, `reservation_id`, `model_id`, `provider`, `cost_estimate` under `_tradeai` while `run_model_job` read them top-level, so every live success was `governance_refused: governance_pass false`; (2) the bridge HTTP handler dropped the body's `request_id`, so the `provider_cost` event's `client_request_id` never equalled the job's `correlation_id` and settlement stayed `NOT_MEASURED`; (3) the gateway sent task type `model_job` for every job, so the bridge selected `n8n_material_digest_draft` regardless of `job.process_id` — the task type is now derived server-side from `PROCESS_TASK_TYPE` in `n8n_model_job.py` (unknown process → typed refusal `process_not_registered`) and `--draft-mode plan` reports `ready: true` only when that derivation and the server-rendered prompt template (`config/n8n_prompt_templates.json`) agree with the live path. A typed refusal (`governance_refused`, `over_cap`, `provider_outage`, `schema_invalid`) is recorded the same way and spends nothing. No lane posts the draft as a coordination event yet (receipt note `no lane for ops summary yet`).

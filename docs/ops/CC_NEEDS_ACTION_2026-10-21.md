# Command Center — the "Needs action" inbox and the failures that had no page (2026-10-21)

```
Status:      MERGED-NOT-SERVED (branch feat/cc-needs-action-20261021)
as_of:       2026-10-21T09:30:00-04:00
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0
Tests:       tests/test_cc_needs_action_20261021.py (gate cc_needs_action_20261021); CC-v3 node tests
             overnightQueueHealth / dataPlausibility / pipelineFailures / needsAction / commsDeliveryHealth
```

An audit on 2026-10-21 found real failures in places the operator does not look, or on no page at all. This change
adds the missing views and a single inbox on Home. Nothing here writes, sends, restarts or approves anything.

## What was hidden and where it is now

| Failure | Before | Now |
|---|---|---|
| telegram_outbox "failed" sends (about 149 a day) | Visible only in Coordination → Events outbox. **They were digest holds, not failures** (see `COMMS_HUB_2026-10-07.md`, 2026-10-21 update). | Archive rows are `held`. Real Telegram failures are a separate figure on the `/v3/communications` strip. |
| Overnight LLM queue (`deep_overnight_llm_queue`) | `/api/v2/queue/summary` existed, but no page used it | `/v3/system` → **Jobs**: backlog, failed, done (24 h), drain estimate, cap/night, OK/WARN/CRIT. `queue/summary` now carries `measured: false` when the table can't be read. |
| Data plausibility | No API. The receipt held counts only. | `GET /api/v2/system/data-plausibility` (`scripts/lib/data_plausibility_view.py`) serves `<state_root>/data/runtime/data_plausibility_last_run.json` and shows it on `/v3/system` → **Data Sources**. `data_plausibility_monitor.py` now also writes `violations`, `blocking` and one `results` row per rule (no sample values). |
| pipeline_runs failures | `/api/v2/pipeline-health` returns the latest 100 rows (mostly finviz successes). Its `stats` was always `{}` because it filtered on the missing column `run_type`. | `GET /api/v2/system/pipeline-failures?hours=24` (`scripts/lib/pipeline_failures.py`) groups failures by pipeline with count, last failure, last error and zombie-cleared count, on `/v3/system` → **Pipeline**. `stats` now filters on `run_label`. |

Each view shows UNAVAILABLE / NO_RECEIPT / STALE when its source can't answer. None of them turns a missing answer into zero.

## The inbox — `GET /api/v2/needs-action`

`scripts/lib/needs_action.py`, cached for 30 s in `api_v2._needs_action`. Each item has
`{severity P0–P3, title, why, where (CC route), source, since, evidence}`.

| Source | Probe | Rule |
|---|---|---|
| health | `/api/v2/health` | `critical` finding → P1 (P0 for `risk_protection`); snapshot older than 3 h → P2 |
| systemd | `systemctl --user list-units 'tradeai*' --state=failed` (read-only) | each failed unit → P1 |
| n8n | n8n-today projection (`live_lane_states` was added to `N8nToday`) | a live lane whose every run today failed → P1; a relay workflow with ≥ 3 errors today → P2 |
| approvals | approval board | expiring → P1; open package → P2; expired in the last 24 h → P3 |
| queue | `queue/summary` | CRIT (≥ 1500 pending / ≥ 200 failed / ≥ 7 nights) → P1; WARN (≥ 500 / ≥ 50 / ≥ 3) → P2 |
| data_plausibility | the receipt view | each BLOCK item → P1; stale receipt → P2 |
| data_sources | `/api/v2/data-source-health` | `dead` / `error` → P2 (the first 8, then one rollup item) |
| comms | delivery summary | un-settled for more than 15 min → P1; failed deliveries → P2; Telegram sends failed → P2; telegram_outbox unreadable → P2 |
| pipelines | pipeline-failures | each failing pipeline → P2 |

**Never silently dropped.** Every probe runs on its own worker with a 5 s budget. A probe that raises, times out or
answers UNAVAILABLE becomes one P2 item, "source X unavailable", and sets `sources.X.status = UNAVAILABLE`.
`all_sources_answered` is true only when all nine answered. The Home card (`components/home/NeedsActionCard.tsx`,
`lib/needsAction.ts`) shows "Nothing needs action" only in that case. A fetch error, a missing payload or a partial
answer is shown as UNAVAILABLE or STALE, never as all-clear.

**Measured 2026-10-21 ~09:25 ET.** The aggregate ran read-only on this branch. API-backed sources were fed from the
live GET payloads, and the file, systemctl and DB sources were read directly. Result: all 9 sources answered,
P0 0 / P1 5 / P2 13 / P3 4.
- **P1:** the health agent's 0700 underfill and the kill switch; n8n `registry-runtime-truth` (every live run failed
  today); overnight queue CRIT (1928 pending, 268 failed); `tradeai-portfolio-backup-cadence.service` failed.
- **P2:** Finnhub dead; ledger:finnhub and ledger:polygon in error; `tradeai-dispatcher` with 14 workflow errors; 9
  failing pipelines, 243 failed runs in 24 h (symbol_enrichment 164, mostly "zombie run cleared").
- **P3:** 4 grants expired in the last 24 h.

## Verify

```bash
curl -s :7777/api/v2/needs-action | jq '{status, all_sources_answered, counts, sources}'
curl -s :7777/api/v2/system/data-plausibility | jq '{status, checked, violations, blocking, ran_at}'
curl -s ':7777/api/v2/system/pipeline-failures?hours=24' | jq '{status, failed_runs, pipelines: [.pipelines[]?.pipeline]}'
python3 -m pytest -q tests/test_cc_needs_action_20261021.py
```

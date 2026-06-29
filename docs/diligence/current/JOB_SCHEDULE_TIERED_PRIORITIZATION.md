# Job-Schedule Tiered Prioritization + GPU/LLM Optimization

_2026-06-29. Root-cause + design + fixes for the Monday GPU/LLM overload that hung the dashboard
(`ERR_CONNECTION_RESET`). Source/scheduler/server/monitoring hardening only — no live trades, no broker
writes, operator/2FA untouched, no gate weakened. LLMs remain advisory only._

## The incident chain

1. **Systemic overload**: **361 cron jobs, 73 LLM-touching, 20–26 colliding every market hour** on one
   local GPU with no time-of-day priority (the audit: `job_schedule_audit.py` / `JOB_SCHEDULE_AUDIT.md`).
2. **Acute trigger — a feedback loop**: the health agent investigated DEGRADED findings via
   **gemma4:31b** (`claude_escalation_handler` Tier-3a, `llama-server` :8081), which burns ~3 CPU cores
   (288–345%) via CPU-spilling Vulkan. That starved the **single-threaded dashboard server** → endpoint
   timeouts → more findings → more 31B investigations → load 8+ and `ERR_CONNECTION_RESET`.
3. **Amplifiers**: a Monday proposal-worker scheduling gap (overnight worker was Tue–Sat), `nomic-embed-text`
   embed timeouts (30s) starving the proposal-review worker, and health-agent false-positives (fixed
   earlier) adding escalation noise.

## Tier model (market-time-sensitivity)

| Tier | What | Window priority |
|------|------|-----------------|
| **T1 market-critical** (22) | finviz scan, signal sync, proposal gen, proposal-review worker, validation fast path, premarket-scalp catalyst, protective stops | 06:00–12:00 ET — never yields |
| **T2 supporting** (18) | news→catalyst, SEC context, enrichment | runs, yields to T1 |
| **T3 background/research** (42) | hermes research/discovery/scoring, topic ingestion/synthesis, inference cycles, RAG index, reports | **defer out of 06:00–12:00 ET** / offload to cloud |
| **INFRA** (279) | watchdogs, health, monitors, telegram, backups | light, always-on |

## Fixes shipped

| Fix | File | Effect |
|-----|------|--------|
| **Dashboard server threaded** (bounded) + thread-local DB conns | `portfolio_server.py`, `db_adapter.py` | `/api/health` 8–12s timeout → ~2ms; a slow endpoint no longer blocks the others. Concurrency capped (`DASHBOARD_MAX_CONCURRENCY`=16). |
| **Escalation 31B guard** | `claude_escalation_handler.py` | skip gemma4:31b in the market window or load1 > 4.0 → lighter lane; breaks the feedback loop |
| **LLM priority guard** | `llm_priority_guard.sh` + `apply_llm_priority_guard_to_crontab.py` | 13 frequent T3 LLM jobs defer 06:00–12:00 ET; market-window LLM contention 20–26 → **12–16** |
| **Monday worker-gap fix** | crontab (`0-5 2-6` → `1-6`) | 4am-enqueued proposal_review jobs always have a drainer |
| **Embed timeout** 30s → 90s | `rag_retrieval.py` | proposal-review worker stops spinning on cold-embed timeouts |
| **Zombie reaper** | `reset_stuck_agent_jobs.py` | resets `processing`>30m jobs → `queued` (the worker died mid-job; no `updated_at` to age them) |
| **Cloud-OAuth usage monitor** | `cloud_oauth_usage_monitor.py` | per-lane calls/day + auth-fail + **paid-fallback** detection (Grok :8645 / ChatGPT :8646) |

See `LLM_ROUTING_MATRIX.md` for the local-vs-cloud routing + the **"gemma4:31b is the wrong local
model for this box"** assessment (keep gemma3:12b local; offload heavy T3 to the free cloud-OAuth lanes).

## Monitoring & auto-fix (health agent)

`health_agent.collect_infra_optimization_health` (registered in COLLECTORS) watches the new work and
auto-remediates safely:

* **`agent_jobs_processing_stuck`** — zombie `processing` jobs → **auto-remediated** by
  `reset_stuck_agent_jobs.py --apply` (added to the auto-remediation **safety allowlist** + policy
  `remediation_map`; source/DB-state only, no broker writes; cooldown + circuit-breaker apply).
* **`cloud_oauth_*`** — lane unreachable / **paid-fallback (critical)** / auth-failures / overuse.
* **`llm_market_window_contention`** — alerts if an unguarded T3 LLM job creeps back into 06:00–12:00 ET
  (re-run the guard applier).

## Rollback

* Crontab is backed up before every change (`~/.crontab_backup_*`). The LLM guard only makes T3 jobs
  *defer* during the window — removing the `llm_priority_guard.sh &&` prefix reverts a line.
* `LLM_GUARD_FORCE=1` / `DISABLE_GEMMA4_31B_ESCALATION` / `ESCALATION_31B_LOAD_CAP` / `EMBED_TIMEOUT_S`
  / `DASHBOARD_MAX_CONCURRENCY` env vars tune or disable each guard without code changes.
* The server change is additive; `git revert` restores the single-threaded server.

## Remaining (next)

* Offload the **8 morning single-shot T3 LLM jobs** (pre-open inference, morning synthesis, 9am topic
  ingestion) to the cloud-OAuth lanes (they can't be guarded without killing them — they must run in the
  morning, just not on the local GPU).
* Drop/relocate **gemma4:31b** off the local box (or only overnight); make `gemma3:12b` the local ceiling.
* Operator: `systemctl restart tradeai-portfolio-server` once to confirm systemd owns the threaded server
  cleanly (already running it as of this change; sudo wasn't available to the agent).

## Safety

No live trades, no broker writes (24/24 schwab-write guards green). No gate/freshness/TTL/route/liquidity/
risk/account/kill-switch weakened. The guards only yield **background/advisory** LLM work to time-sensitive
market work and the dashboard. Operator confirmation / 2FA untouched. Validation sample unchanged (2/30);
no strategy maturity claim.

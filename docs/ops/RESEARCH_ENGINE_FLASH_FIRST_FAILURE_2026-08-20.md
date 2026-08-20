# Research engine Flash-first failure — 2026-08-20

Authority: READ_ONLY_ADVISORY (no broker / order / stop / 2FA).
Scope: Command Center research-ops strip + watchlist agent job queue.

## Symptom

Ops strip showed roughly **Created 311 / Failed 312 / Completed 8**, provider mix
`gemma3:4b=8`, **zero DeepSeek Flash**. Flash-first governance (PR #401) is live in
code but not producing successes in the worker process.

## Root cause (measured)

Today's `watchlist_events` failure messages are dominated by:

1. `LLM error: COST_CONFIGURATION_INVALID: global daily USD cap required` (~111)
2. Cascading `CIRCUIT_OPEN: agent_flash circuit breaker open … last=COST_CONFIGURATION_INVALID…`

Flash fail-closed when `LLM_GLOBAL_DAILY_USD_CAP` is unset in the **agent-jobs
worker** environment. After the error threshold, the circuit opens and remaining
jobs fail without a provider call. The few completions that land are local
`gemma3:4b` fallback/legacy paths — not Flash successes.

Evidence (operator host, 2026-08-20):

- `watchlist_agent_jobs` today: failed=312, completed=8, queued≈146
- Cap is commented in `config/systemd/agent_runtime/tradeai-agent-runtime@.service`
  (`# Environment=LLM_GLOBAL_DAILY_USD_CAP=0.50`) while some other user units set it.
- Command Center process may show `CONFIGURED` if its own env has the cap; the
  worker that executes jobs may not. Trust the ops strip `dominant_failure_class`
  and worker journal, not the UI process alone.

## What we changed in code (this hardening)

- `/api/v3/cio/agent-research-ops` now surfaces:
  - `failure_classes_today` / `dominant_failure_class`
  - `flash_first.provider_attempted_today` / `provider_actual_today` / `fallback_reason_today`
  - `operator_finding` pointing at this doc when cap-missing is observed
  - explicit `requeue_suppressed: true` (do **not** silently re-queue)
- CC research-ops strip renders the dominant failure + Flash-first attempt/actual.

## Operator fix (config only — not applied by this PR)

1. Set a numeric `LLM_GLOBAL_DAILY_USD_CAP` on the **watchlist agent jobs** systemd
   unit / drop-in that actually runs `process_watchlist_agent_jobs.py`
   (uncomment or add `Environment=LLM_GLOBAL_DAILY_USD_CAP=0.50` — value is an
   operator decision; docs historically discuss $0.25–$1.50).
2. Confirm the worker process sees it (`systemctl --user show … -p Environment`
   or a one-shot env dump in the job log). Do not print secrets.
3. Restart the worker after the drop-in lands.
4. **Do not** bulk re-queue the failed backlog automatically. After the cap is
   live, enqueue a small deliberate canary (few symbols) and confirm Flash
   appears in `flash_first.provider_attempted_today` / `provider_actual_today`.
5. Only then drain/re-enqueue remaining work with eyes on the daily cap.

## Non-goals

- No silent re-queue of the 300+ failed jobs.
- No change to broker / order / stop / 2FA paths.
- No inventing Flash receipts when the provider was never called.

## Resolution (2026-08-20) — supersedes the "CAP missing" root cause above

Re-investigation showed the "missing `LLM_GLOBAL_DAILY_USD_CAP`" framing was **stale**.
The 8-19 cron→wrapper migration already sourced `agent-operator.env` on the live
drain path (`run_watchlist_agent_jobs_offpeak.sh` logs `LLM_GLOBAL_DAILY_USD_CAP_ok=yes`
every run). The two **real** gates blocking the governed Flash-first path
(`agent_flash_governance` / `watchlist_maria_flash_narrative`) were:

1. **Canonical containment flag absent** — `~/.local/state/tradeai/AGENT_JOBS_P0_CONTAINED`
   did not exist, so the market-hours governed canary fail-closed `exit=78` every 15m.
2. **`daily_soft_cap=120` request cap exhausted** overnight for
   `watchlist_maria_flash_narrative`, so every governed maria call rejected with
   `COST_CAP_EXCEEDED: daily request cap` before reaching the provider; 8 errors
   then tripped `agent_flash` for the rest of the run.

**Applied fix:** armed containment via `agent_jobs_containment.activate()`, added the
process-scoped containment override to the offpeak wrapper, and raised the maria
`daily_soft_cap` 120→240. Result: 5/5 governed `--scheduled-canary` Flash calls
succeeded on exact `deepseek-v4-flash` (no `gemma3`), cost recorded, `fallback_used=false`.
Failure churn (CAP_MISSING / CIRCUIT_OPEN) stopped once containment was armed.

See `docs/ops/FLASH_ACTIVATION_AND_THESIS_CANARY_2026-08-20.md`.

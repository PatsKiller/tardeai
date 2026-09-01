# v3 LLM-Review Ollama Health Gate + Retry (2026-06-06)

Status:      ACTIVE
as_of:       2026-06-06T10:38:55-04:00
Measured at: efcc51365 / not measured

## Root cause
`trade_llm_reviews`: 2102 rows, 1778 errors. The `--structured --apply` backtest-review path ran even when
Ollama was unavailable and only *warned* (advisory preflight), grinding through the batch and writing a
per-trade error row each time. Breakdown: 1671 INFRASTRUCTURE (924 timeout + 709 connection-refused + 29
conn-closed + 9 HTTP-500) + 60 parser + 47 unknown. The UI showed these as "Errors", implying analytics/
trade failure when it was Ollama availability.

## Implementation
- **Health helper** `scripts/llm_health_gate.py::check_ollama_health` — /api/tags reachability + model
  presence + tiny bounded /api/generate probe; short timeouts; normalized failure_class
  (connection_refused/timeout/connection_closed/http_500/model_missing/invalid_response). Healthy probe 7-8ms.
- **Hard cron preflight** in `trade_close_llm_analyzer.py` (`--structured --apply`): if unhealthy →
  record ONE `llm_review_runs` row `SKIPPED_LLM_UNHEALTHY` + exit 0; **does NOT** create per-trade error
  rows. If healthy → proceed, then record a `COMPLETED` run.
- **Run-level table** `llm_review_runs` (status COMPLETED|PARTIAL|SKIPPED_LLM_UNHEALTHY|FAILED_INTERNAL_ERROR,
  health_status JSONB, counts). `migrate_llm_review_health.py`.
- **Error classification** (additive cols on trade_llm_reviews: error_class, retryable, retry_after,
  retry_count, llm_review_run_id, trade_instance_id). Backfilled: ollama_* infra = retryable; parse_error/
  unknown = non-retryable. Result: 1671 retryable infra, 60 parse, 47 unknown.
- **Retry mode** CLI flags `--retry-infra-failures --max-retries 1 --max-rows 50` (bounded; health-gated).
  NOT auto-run; the 1671 backlog is operator-approved batches only (no bulk regen).

## Endpoint / UI
- `/api/v2/lifecycle/llm-review-status` now returns `error_breakdown` {infrastructure_errors 1671,
  parser_errors 60, empty_null_reviews, retryable 1671, invalidated_stale_basis 10, by_class}, live
  `ollama_health`, and `runs` {last_skipped_at/reason, last_successful_at}. Plus a "not failed trades" note.
- v3 LLM Review Coverage tab: health banner (green healthy / yellow last-run-skipped / red unhealthy),
  6 categorized cards (Total/Complete/Infra errors/Parser errors/Empty-null/Retryable), explanatory text
  "Infra errors are model/service availability failures, not failed trades or strategy logic."

## Validation (11/11 PASS — scripts/validate_llm_review_health_gate.py)
health helper structured · bad-port→unhealthy/classed · **unhealthy skip = NO per-trade flood (2102→2102)**
· one run record written · infra retryable / parser non-retryable · endpoint separates categories + health
+ run history · retry flags present · paper mode.
Healthy live run: gate PASSED (7ms) → 3 evaluated (2102→2105) → COMPLETED run recorded (gemma3:12b).

## Before → after
- infra errors: 1671 (now CLASSIFIED + retryable, separated in UI from parser)
- parser errors: 60 · empty/null: 0 · unknown: 47
- run records: 0 → 3 (1 COMPLETED, 2 SKIPPED_LLM_UNHEALTHY from tests)
- flood when Ollama down: ELIMINATED (skip + 1 run record, 0 per-trade rows)

## Remaining retry backlog & recommendation
1671 retryable infra-failure rows remain — drain via bounded `--retry-infra-failures --max-rows N` runs
(health-gated), operator-approved, NOT bulk. The Sun 23:00 review cron will now self-skip cleanly if Ollama
is down rather than re-flooding.

## Safety
ALPACA_MODE=paper, live disabled. Infra hygiene + analytics only. No broker/order/stop/proposal/GO-WAIT/
strategy/live/Phase-205 changes; Hermes drain mode untouched; no bulk regen.

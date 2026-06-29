# Momentum Scalp Source Lifecycle

_Inventory of the discovery → scan → signal → proposal → validation path for momentum_scalp, and the
cadence/latency gaps this hardening closes. Source/scheduler/reporting only — no broker writes._

## The lifecycle

```
Finviz screen / social discovery
  → normalized scanner row
  → trade_ai_scans  (+ scalp_scan_results for social)
  → strategy_signal_sync  → strategy_signals
  → auto_proposal_generator  → paper_trade_proposals
  → momentum_scalp_validation_fast_path  → sandbox/simulated validation submit
```

## Components (as built)

| Stage | Script(s) | Writes | Notes |
|-------|-----------|--------|-------|
| Finviz source refresh | `finviz_screener_runner.py --run` (29 screeners, throttle-safe via `finviz_throttle`); `finviz_ingestion.py` (Elite CSV) | watchlist / source tables | momentum_scalp had **no dedicated screener** (operator-excluded in `add_winning_strategy_screeners.py`) |
| Main scan → scan rows | `trade_ai_orchestrator.py --run-label NNNN` (screener→enrichment→scalp critic→GO/WAIT/NO-GO) | `trade_ai_scans` | hourly-ish (0900/1000/1200/1400/1600/1730) |
| Social scalp scan | `social_scalp_scanner.py` | `scalp_scan_results`, `trade_ai_scans` (+ route/scout fields via `route_social_candidate`, `stamp_route_fields`, `stamp_scout_fields`) | `0,30 6-9` + `0 10-16` ET (every 30 min early) |
| Signal sync | `strategy_signal_sync.py --today` | `strategy_signals` | route-enforced (`route_enforced_strategy`); scout/social-only/large-float blocked from momentum_scalp signal |
| Proposal gen | `auto_proposal_generator.py --today --apply` | `paper_trade_proposals` | env-gated validation hook (`MOMENTUM_SCALP_VALIDATION_FAST_PATH=1`) fires the fast path after each batch |
| Validation fast path | `momentum_scalp_validation_fast_path.py --submit-sandbox` | sandbox `paper_trades` (legacy alias) | deterministic gates; sandbox/simulated only; `*/2 6-11` cron + generation hook |

## Quote / liquidity, catalyst, scout inputs

* **Quote/liquidity**: `market_quote_provider` / `check_fresh_quote` — fast-path DEFERs on stale quote
  (freshness never weakened).
* **Catalyst**: `finviz_news.py`, `finviz_enrichment.py`, RAG catalyst confirmation → `catalyst_verified`.
* **Social Scout pillars**: `social_scout_pillars.py` via `social_route_policy.route_social_candidate`
  (market_confirmation / structure_tradeability / strategy_risk_fit / catalyst_evidence from Finviz +
  social_velocity from social sources). See [SOCIAL_SCOUT_PILLARS.md](SOCIAL_SCOUT_PILLARS.md).

## Known gaps (pre-hardening)

1. **Finviz cadence too sparse in the early window.** `finviz_screener_runner` ran only at
   07/08/10/12/14/16/18 ET; social scalp scan every 30 min. The validation fast path runs `*/2` but only
   helps if fresh candidates/proposals exist — source discovery was not equally aggressive 06:00–12:00.
2. **No momentum-scalp-targeted Finviz screen** aligned to the `momentum_scalp.yaml` `screen_filters`.
3. **No early-lane orchestration**: scan → signal → proposal → validation was time-scattered, not
   chained immediately after a fresh scan.
4. **No source-maturity / source-latency reporting** to prove candidates flow fast enough.

## What this hardening adds

* `config/finviz_momentum_scalp_screen.yaml` — targeted Finviz filters mirroring `momentum_scalp.yaml`.
* `run_finviz_momentum_scalp_scan.py` — window-gated (06:00–12:00 ET) wrapper, dry-run default,
  optional handoff; cron every 5 min.
* `momentum_scalp_early_lane_runner.py` — one command runs scan → signal sync → proposals → validation,
  per-stage JSON + latency, dry-run default.
* `momentum_scalp_source_maturity_report.py` — per-source maturity (source vs validation separated).
* `momentum_scalp_source_latency_sla.py` — source→validation latency SLA by window.

All stages are idempotent, reuse existing proven scripts, and perform **no live broker writes**. The
remaining blocker to strategy maturity 4.5 is unchanged: the **empirical validation sample** (2/30
confirmed closed simulated validation trades) — this work feeds it fresh candidates, it does not claim it.

## Health monitoring & auto-fix

The health agent (`health_agent.py`) monitors the early lane and **auto-remediates** it:

* `collect_momentum_scalp_source_health()` — **schedule-aware** (judges only inside 06:00–12:00 ET on
  trading days, so no weekend/off-hours floods). It reads `logs/finviz_momentum_scalp_scan.log`:
  * log missing or stale >12 min (cron is `*/5`) → `momentum_scalp_finviz_scan_stale` (warning;
    critical >30 min);
  * last run `status=PARTIAL/FAIL` or `failed_stages` → `momentum_scalp_early_lane_error` (warning).
* **Auto-fix**: both finding types are in `health_agent_policy.json` `auto_remediate.finding_types` with
  a `remediation_map` command that re-runs the lane **fast** (`run_finviz_momentum_scalp_scan.py
  --skip-finviz-refresh --sync-signals --generate-proposals --run-validation-fast-path`). The script is
  on the auto-remediation **safety allowlist** (source/sandbox only — no broker writes), governed by the
  existing cooldown + circuit-breaker (escalates to operator/code review if a fix proves ineffective).

This makes the every-5-min source lane self-healing without weakening any gate or touching the
operator/2FA path.

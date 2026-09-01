# Phase 207B — Daily Report Advisory-Draft Classification — 2026-06-07

Status:      DRAFT
as_of:       2026-06-07T10:47:33-04:00
Measured at: efcc51365 / not measured

## Launcher chain
`portfolio-daily.timer` → `linux_launchers/run_portfolio.sh` → (daily):
- `python scripts/portfolio_orchestrator.py --project-root . --run-label morning --run-type daily`
- `backfill_acct_periods_v3.py` (non-fatal helper)
- `session_hygiene.py`, `refresh_soul.py` (non-fatal advisor-skill housekeeping)

## What `portfolio_orchestrator.py --run-type daily` does
- **DB writes (review-only):** `advisor_observations` (`save_advisor_observations`),
  `advisor_recommendations` **drafts** with explicit `"status": "draft"` (`save_advisor_recommendations`),
  advisor escalations queued; expires stale drafts/escalations (date-based housekeeping).
- **File writes:** portfolio report artifacts (state/reports).
- **LLM usage:** advisor pipeline (dual-AI advisory for monthly; daily advisor scoring) — local models;
  `LLM_DISABLE_LIVE_EXECUTION=true`.
- **Telegram/SIEM:** the legacy timer path does not `--telegram` (run_portfolio.sh has no telegram flag;
  that is a separate `run_alex_daily.py` cron, out of scope).
- **Broker/order/proposal/protection references:** **NONE** — grep for
  `submit_order|place_order|proposal-execution|protection-mutation|GO_WAIT|strategy_scoring` in the daily
  path returns nothing. Recommendations are created with `status="draft"` and never executed.

## Classification
- static report outputs: **YES** (portfolio report artifacts)
- advisory draft outputs: **YES** (`advisor_recommendations` status=draft, observations)
- action-queue review-only outputs: **YES** (escalations queued for review; not executed)
- non-executing confirmation: **YES** (drafts only; no broker/order/proposal-execution)
- risk concerns: none beyond ordinary DB draft writes; drafts are date-expired, reversible, review-only.

## Required conclusion
- review-only advisory drafts: **YES** → cadence label `PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY`
- broker/order execution: **NO**
- proposal/trade/protection mutation: **NO**
- acceptable for daily cadence migration: **YES** (the controller already labels it review-only and
  excludes destructive steps)

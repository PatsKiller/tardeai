# Backlog — Reposition / Defensive Rotation = advisory decision page (operator requirement 2026-11-14 ~18:20 ET)

Layout: the approved v02 `#reposition/*` tabs (rotation, reentry, exits, capital, comparison, plan-lab, event) are kept as they are. This is a real-data functionality and acceptance requirement, not a redesign.
Author/owner: **cc-deepseek-7** · Independent reviewer: **cc-deepseek-5** · Lead acceptance: claude-lead.
Not part of the frozen design-preview candidate.

## Products (n8n-owned, stored, page reads only)
| Product | Cadence | Content | Must never |
|---|---|---|---|
| RepositionDaily@1 | session-aware: premarket and after close on each trading day; weekend/holiday = references last completed session | next-session tactical guidance; confirms, challenges or invalidates the weekly thesis | run synthesis on page load; show an empty list as success |
| RepositionWeekly@1 | weekly, after the last session of the week | strategic allocation/rotation review; thesis retained across days | invent weights, targets, stops, tax or P&L |

Both products need: input/output schema, source clocks + session label (regular / premarket / after-hours / closed), coverage/freshness contract, idempotency key, overlap lock, bounded retry, missed-run detection, escalation, success/failure receipt (LaneRunReceipt@v2), recovery proof. Registered per the scheduler ruling (n8n only; no cron/systemd business job).

## Card contract (each actionable suggestion)
action ∈ {reduce, exit-review, hold, add/rotate, wait} · exact account + security IDs · current exposure (canonical read model) · supported proposed destination incl. cash/wait · rationale + alternatives · horizon ∈ {short-term, swing/intermediate, long-term} with an intended holding window + next review time · evidence with quote/session/source times · valuation-assessment@1 / quality / income context where applicable · entry/confirmation conditions · downside/protection · exit/invalidation conditions · upcoming catalysts · coverage/confidence with reasons · sourced fact vs CIO inference vs uncertainty vs suitability limits, separated. A sizing input that isn't supported is named as missing; it is never filled with a made-up %.
History: prior recommendation, what changed, acted-on (only when evidence exists), outcome, all held in retained CIO memory, so they survive rebuild and restart.

## Backend mapping — FIRST TASK: audit (verdicts REUSE / EXTEND / MISSING per row, before any new code)
| Need | Candidate existing capability (unaudited) |
|---|---|
| portfolio-aware capital plan, per account | `/api/v2/cio/capital-plan`, `lib/cio_capital_plan.py`, `cio_capital_plan_decision_store.py` |
| decision identity + per-account split | `lib/cio_decision_semantics.py`, `cio_command_center.py` (OP-064 O3/F1 patch READY, -6/-9) |
| rotation candidates/alternatives | `/api/v2/rotation/summary`, `/api/v2/aegis/rotation-alternatives`, `lib/rotation_publication.py`, `rotation_stocks.py`, `/api/v2/strategy-rotation/*` |
| re-entry / exits | `/api/v2/reentry/decision-desk`, `/api/v2/reentry/status`, `/api/v2/stops/reentry-watch`, `/api/v2/journal/exit-intelligence`, `/api/v2/time-exit-proposals` |
| capital pools / cash | `/api/v2/redeploy/capital-pools` |
| recommendation history/outcomes | `lib/recommendation_registry.py`, `recommendation_comparison.py`, `trade_recommendation_linkage.py`, `cio_memory_integration.py` |
| weekly review | `/api/v2/weekly-report`, `/api/v2/weekly-learning-digest/latest` |
| market regime / outlook | `/api/v2/market-risk/latest` (score is NOT a probability), `lib/market_outlook*` (LQ-946 reader gap) |
| ask CIO / feedback (safe actions) | `/api/v2/rotation/ask`, `/api/v2/rotation/feedback` — still to verify whether they are paid LLM calls; no paid reruns without the operator |
Excluded as actions: `/api/v2/rotation/propose-etf`, the grok-* review triggers and `/time-exit-proposals/decide`. They stay out until the audit shows what each one does. Nothing touches orders, approvals or 2FA.

## Acceptance
Daily and weekly products are distinct and produced automatically, with receipts. History survives a rebuild/restart. The same account/security/source/session data agrees with Home/Portfolio/Watch. Horizon labels and material changes are consistent. Every tab/card/detail works at 1440 and 390. Failed or missing evidence is shown explicitly.

## Slices (bounded, each with BEFORE/AFTER + an independent review)
R1 audit + register rows (no code) → R2 RepositionDaily@1 schema + stored product (fixture-free, synthetic tests) → R3 Weekly@1 + thesis retention → R4 history/outcome join → R5 v02 tab port on real data.

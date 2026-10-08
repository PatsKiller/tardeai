# Watch decision standards — the Communications standards on the Watchlist (2026-10-08)

Operator 2026-10-07, after the Communications hub shipped: "watchlist etc". The Command Center standards apply to
the Watchlist. Every item carries a category, a priority, a confidence score, a TTL with an expiry timestamp, a
status and an actionability indicator. Items are sortable by priority, confidence, risk, reward and time
sensitivity, and the page answers the six at-a-glance questions.

## Where it lives

| Piece | File |
|---|---|
| Rules, TTLs, thresholds | `config/watch_decision_standards.yaml` |
| Computation (read-only, zero provider calls) | `scripts/lib/data_broker/watch_decision.py` |
| Projection wiring | `scripts/lib/data_broker/watch_intelligence.py` → `/api/v3/data-broker/watch-intelligence` (`card.decision`, `decision_board`, view `expired`, decision filters and sorts) |
| UI | `apps/command-center-v3/src/components/watch/WatchDecisionParts.tsx` on `/watch` → Intelligence (`WatchIntelligenceUnified.tsx`) |
| Tests / gate | `tests/test_watch_decision_standards_20261008.py`, gate `watch_decision_standards_20261008` |

## Inputs

Batched once per request: the latest `watchlist_entry_plans` row, `watchlist_strategy_cards`, the latest
non-superseded `watchlist_final_synthesis`, `symbol_profiles.next_earnings_date`, and the deterministic re-entry
desk (`lib/data_broker/reentry_decision_desk.build_decision_desk`, cached 120 s). The card itself supplies the
quote, near-trigger, street upside, Trade AI state, proposal eligibility and review times.

## Rules (first match wins)

| Rule | Category | Base priority | Actionable |
|---|---|---|---|
| held + synthesis SELL / TRIM / AVOID | Risk | high | yes |
| held + Trade AI AVOID / BLOCKED / FAIL | Risk | high | yes |
| re-entry desk READY TO REVIEW | Re-Entry (confirmed) | high | yes |
| re-entry desk NEAR ENTRY | Re-Entry (potential) | medium | yes |
| re-entry desk WAIT / OVERBOUGHT / MISSING | Re-Entry (opportunity) | low | no |
| proposal allowed | High Conviction Opportunity | high | yes |
| ready plan, in zone, confidence ≥ 0.6, R:R ≥ 2 | High Conviction Opportunity | high | yes |
| ready plan | Reward | medium | yes |
| near trigger | Reward | medium | yes |
| near-entry plan | Reward | low | no |
| held, nothing negative | Held Position | low | no |
| anything else | Watchlist Candidate | low | no |

Scores (0..1):
- **Confidence:** planner → strategy card → synthesis → 0.3.
- **Reward:** R:R ÷ 6, or street upside ÷ 30%.
- **Risk:** stop distance ÷ 15%, raised for held-and-negative, earnings within 7 days, a blocked state, or a stated risk.
- **Time sensitivity:** 1.0 in zone, READY or proposal; otherwise from distance to the trigger, plan urgency and earnings.

`priority_score = 100 × (0.35·time + 0.25·max(risk, reward) + 0.20·confidence + 0.20·tier)` is the same formula
as Communications. The label never falls below the rule's base priority and rises at most one tier above it.

## TTL and status

- TTL: 96 h for Re-Entry, Risk, Reward and High Conviction; 168 h for Watchlist Candidate and Held Position. It
  counts from the newest evidence: a fresh entry plan (≤ 7 d), a synthesis (≤ 14 d), a completed review, or, for
  re-entry, the desk's quote time (the desk recomputes, so new data reaffirms it).
- **active:** evidence inside the TTL.
- **needs_data:** no evidence at all (shown, flagged "needs fresh analysis").
- **expired:** past the TTL.
- **invalidated:** a non-held idea the CIO synthesis marked AVOID / IGNORE / SELL, or Trade AI AVOID / BLOCKED / FAIL.
- **What expires is the signal, never the membership.** Expired and invalidated items leave the active views and
  appear under view `expired`. Nothing is deleted, and removing a name stays an operator action
  (`watchlist_hygiene.py` keeps its own weekly rules).
- **Held positions never leave the views.** A held name with an old signal shows "signal expired — review".
- **A search always finds the name,** with its status badge.

## Measured on live data (2026-10-08 ~03:30Z, view `all`, 188 symbols)

- **Live and actionable:** 141 live, 7 actionable.
- **Status:** 16 active, 122 needs fresh analysis, 3 expired, 50 invalidated.
- **Top Ideas:** unchanged at 21, mostly held positions.
- **Response time:** about 3.6 s, against a 3.2 s baseline.

122 of 188 symbols having no plan, synthesis or review inside the window is the main finding. The pipeline is not
producing evidence for most of the watchlist. The page now says so instead of showing every name as equally live.

# Social Scout Pillars

_Operator-awareness surfacing for partial social setups. Implemented in
`scripts/social_scout_pillars.py::evaluate_social_scout_pillars`, wired through
`scripts/social_route_policy.py::route_social_candidate`; covered by
`tests/test_social_scout_pillars.py` + `tests/test_social_route_policy.py`._

## What a Social Scout is

A **Social Scout** is an **operator-awareness state**, not an execution state. When a social-discovery
candidate is *not yet* validation-ready or momentum_scalp/GO-ready, but satisfies at least **two of the
five** defined pillars, TradeAI surfaces it to the operator with a distinct **Social Scout** pill so the
operator understands at a glance:

* this is interesting,
* it is **not quite there yet**,
* it is **not a GO**,
* it is **not validation-fast-path eligible**,
* it is **not a standard momentum_scalp trade**.

A Social Scout pill **never** unlocks validation submit, strategy-signal creation, GO alerts, or live
trading. Validation maturity is **unchanged** by Social Scout surfacing — this is visibility, not
empirical sample evidence.

## The five pillars

| # | Pillar | Met when (deterministic) |
|---|--------|--------------------------|
| 1 | `social_velocity` | mention count ≥ 8, OR ≥ 2 distinct sources, OR social score ≥ 25, OR an unusual-acceleration flag |
| 2 | `market_confirmation` | RVOL ≥ 2.0, OR \|gap%\| ≥ 3, OR \|change%\| ≥ 5 (market action confirms the social attention) |
| 3 | `catalyst_evidence` | a **verified** (non-rumor) catalyst — news / filing / event / contract / FDA / insider (reuses `catalyst_is_verified`) |
| 4 | `structure_tradeability` | price & float present and interpretable; no missing critical data; no halt / offering / dilution / reverse-split risk |
| 5 | `strategy_risk_fit` | plausibly maps to a scout/scalp/manual-review lane: price ≤ $50, float known, RVOL present, not a portfolio/income name |

Thresholds are deliberately **lighter** than the tradeable momentum_scalp GO gates — a Scout is
"interesting, not there yet," so confirmation here is weaker than the scalp boundaries (RVOL ≥ 5,
float ≤ 20M, price ≤ $25, verified catalyst). Pillar boundary constants are imported from
`social_route_policy` so the two stay in lock-step.

## Threshold behavior

| Pillars met | Result |
|-------------|--------|
| **0 / 5** or **1 / 5** | No Social Scout pill. Remains WATCH / WAIT / AVOID per route policy. |
| **2 / 5**, **3 / 5**, **4 / 5** | **Social Scout pill appears** — `SOCIAL SCOUT · N/5`. Never GO, never tradeable, never validation-eligible. |
| **5 / 5** | Does **not** automatically mean GO. The candidate must still pass the existing route policy + deterministic gates. A 5/5 verified micro-float that meets the momentum_scalp gates routes to `momentum_scalp` / GO through the **normal** path (and the scout pill is suppressed in favor of GO). A 5/5 large-float routes to `large_float_social_scout` / manual review — never the validation fast path. |

A graduated GO carries `scout_status = NONE` (the route policy suppresses the pill on GO), so the
GO/scout states are mutually exclusive on any one row.

## Output shape

```json
{
  "pillar_count": 2,
  "pillars_met": ["social_velocity", "market_confirmation"],
  "pillars_missing": ["catalyst_evidence", "structure_tradeability", "strategy_risk_fit"],
  "scout_status": "SOCIAL_SCOUT",
  "operator_pill": "SOCIAL SCOUT · 2/5",
  "operator_subtitle": "Not quite there yet",
  "operator_color_token": "socialScout",
  "not_validation_ready": true,
  "not_tradeable": true,
  "reason_codes": ["SCOUT_SOCIAL_VELOCITY", "SCOUT_MARKET_CONFIRMATION"]
}
```

* **Large-float** scouts surface as `SOCIAL SCOUT · LARGE FLOAT · N/5` (manual-review only).
* Missing critical pillars emit tooltip reason codes: `NEEDS_CATALYST` ("Needs catalyst verification"),
  `NEEDS_MARKET_CONFIRMATION` ("Needs market confirmation"), `NEEDS_TRADEABILITY_CHECK`
  ("Needs tradeability check").

## Hard invariants (enforced + tested)

* A Social Scout is **always** `not_tradeable` and `not_validation_ready`. The pillar module can never
  assert otherwise.
* `momentum_scalp_paper_fast_path` (validation fast path) **rejects** any `scout_status = SOCIAL_SCOUT`
  or `SCOUT` actionability → `SOCIAL_SCOUT_NOT_VALIDATION_ELIGIBLE` (P0-6).
* `strategy_signal_sync.route_enforced_strategy` returns **no signal** for a scout.
* `continuous_runner.classify_social_injection` surfaces a scout for visibility but marks it
  **never tradeable**.
* Social-only candidates remain WATCH / WAIT / SCOUT only, **never GO**.
* Large-float social scouts remain **manual-review only**.
* Operator confirmation / 2FA and the live execution path are untouched and out of scope.

## UI

Color token `--social-scout` (violet `#a855f7`, deliberately not green/GO, amber/WAIT, or red/AVOID).
The pill renders in the Trading hub Scalp screen rows + a "Social Scouts" summary metric, with a
tooltip of `operator_subtitle` + missing-pillar hints. There is **no** Buy / Submit / Validate / Trade
affordance on a Social Scout — it is a watch/surface/awareness state only.

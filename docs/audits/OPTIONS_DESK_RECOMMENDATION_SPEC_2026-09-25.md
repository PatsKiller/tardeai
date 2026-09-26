# Options Desk Recommendation Enhancement Specification — 2026-09-25

**Status:** served comparison corrected on branch `wt/options-decision-truth-20260925`. `risk_reward` is max profit ÷ max loss (`reward_to_risk`). Loss ÷ capital is `risk_to_capital`. A desk-wide thesis pin is not this proposal's review. Policy 1.2.7 is not stamped. A CIO status requires `cio_review_id`. Advisory only. Not an order.
**Authority:** advisory-only; no sizing, order, stop, risk-limit, or 2FA authority

## Canonical recommendation comparison

Every equity or options recommendation should expose this normalized object, whether a field is populated or explicitly unavailable:

```yaml
recommendation_comparison:
  underlying: {symbol, security_guid, as_of}
  thesis: {verdict, direction, thesis_version, evidence_refs}
  stock_play:
    action: buy | hold | avoid | unavailable
    capital_required: number | null
    maximum_loss_model: string
    expected_return: number | null
    time_horizon: string | null
    risk_notes: [string]
  options_play:
    structure: string | null
    legs: [contract identity and side]
    capital_required: number | null
    maximum_risk: number | null
    expected_return: number | null
    probability_of_success: number | null
    expiration_rationale: string | null
    strike_rationale: string | null
    liquidity_status: pass | warn | block | unavailable
  comparison:
    capital_efficiency: string | null
    risk_reward: number | null
    opportunity_cost: string | null
    cash_preservation: string | null
    concentration_effect: string | null
    preferred_structure: stock | options | neither | review_required
  oversight:
    cio_commentary: string | null
    review_status: unreviewed | reviewed | challenged | deferred
    authority: READ_ONLY_ADVISORY
  provenance: {sources, generated_at, freshness, model_or_engine, policy_versions}
```

The contract must never infer a stock alternative from an options card without sufficient underlying price, thesis, and risk data. Missing facts render `unavailable` or `review_required`; they do not become zero or a synthetic pass.

## Required strategy validation matrix

| Strategy family | Must validate | Required negative cases |
|---|---|---|
| Covered call | share coverage, strike/expiration, upside cap, assignment, income yield, stock alternative | fewer than 100 shares, stale quote, missing chain, concentration conflict |
| Cash-secured put | cash reserve, assignment economics, breakeven, downside, underlying thesis | insufficient cash, deteriorating thesis, event gap risk, missing assignment disclosure |
| Protective put | hedge need, notional covered, convexity, premium drag, replacement timing | no held exposure, hedge no longer needed, stale chain, excessive premium |
| Long call/put | thesis direction, delta, theta, premium at risk, expiration, defined maximum loss | weak thesis, excessive premium, theta burn, missing catalyst or horizon |
| Vertical spread | leg identity, width, debit/credit, max loss/profit, package liquidity, POP | incomplete leg, crossed/inconsistent expiry, unproven multi-leg route, slippage breach |
| Income/volatility structures | volatility regime, edge source, event exposure, lifecycle/adjustment plan | edge below floor, IV unavailable, event window unresolved |
| Portfolio hedge | portfolio exposure, hedge ratio rationale, correlation/regime, cost | hedge disconnected from book, duplicated exposure, unsupported risk reduction |

## Recommendation display standard

The card or detail view must answer, in order:

1. Why direct stock?
2. Why options instead?
3. What is the maximum risk under the stated structure?
4. What capital is committed and what remains available?
5. What is the expected return and time horizon?
6. What portfolio concentration or hedge effect results?
7. What would invalidate the thesis?
8. What did CIO review or challenge?

## Deterministic acceptance rules

- Maximum risk must be structure-specific; covered-call risk must not be described as premium-only while shares remain held.
- Spread risk must use package economics, not one-leg economics.
- POP, EV, R:R, and expected return must carry their calculation basis and timestamp.
- Stock and options returns must not be compared without matching horizon and capital basis.
- A recommendation cannot be `preferred_structure=options` when required option data is stale, unavailable, or blocked.
- A recommendation cannot be marked CIO-reviewed merely because an LLM or ensemble ran; a durable review record is required.
- Every blocked proposal remains queryable with an explicit blocker code.


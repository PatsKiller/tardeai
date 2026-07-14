# FCNTX Event #144 — A–G Acceptance Fixture (Part H)

**Date:** 2026-07-14 · Sale: FCNTX $107,023.01 (schwab_rollover_ira, settled/verified)
Engines: candidate_research 1.0.0 · pro_forma 1.0.0 · performance 1.0.0 (plan legs v3)
All numbers computed from the local 5-year cache (ticker_prices / ticker_dividends /
instrument_facts) with look-through; whole-share modeling; production evidence only.

## Per-plan results (income Δ vs post-sale state; 1Y = dollar-weighted total return)

| Plan | Legs | Modeled deploy | Income Δ/yr | 1Y | 3Y | 5Y | Remaining gaps (look-through) |
|---|---|---|---|---|---|---|---|
| A Strategic | QQQ + SCHD + BND | $106,821 | +$2,274 | 24.9% | 63.6% | 65.1% | Comm Services, Consumer Cyclical |
| B Diversified | QQQ + XLC + XLF + XLY + XLI + BND | $106,260 | +$1,558 | 13.1% | — | — | Technology |
| C Income | JEPQ + JEPI | $106,948 | **+$9,756** | 15.6% | — | — | Comm Services |
| D Defensive | BND + SCHD | $106,787 | +$4,010 | 12.4% | — | — | Comm Svcs, **Technology**, Cons Cyclical |
| E Tactical | ITA + XLE | $106,984 | +$1,760 | 27.4% | — | — | Comm Svcs, **Technology**, Cons Cyclical |
| F Staged | JEPQ + QQQ (tranche 1) | $26,079 | +$1,636 | 24.4% | — | — | Comm Services, Consumer Cyclical |
| G Hold | cash | $0 | $0 | — | — | — | all sale-removed exposure remains |

Sold-fund reference: FCNTX total return 1Y **28.9%** / 3Y **99.4%** / 5Y **95.1%**,
trailing yield 4.21% (computed from distribution history; facts yield reports 0),
expense ratio 0.74%. No plan is presented as replicating FCNTX — the deltas above
are shown against it, not hidden.

## Part H verification checklist

- ✅ **Tactical defense (E) not misrepresented as FCNTX replacement** — its remaining
  gaps explicitly include Technology, Comm Services, Consumer Cyclical.
- ✅ **JEPQ labeled income + partial growth** — leg role `partial_growth_restore+income_enhance`,
  never "pure growth replacement".
- ✅ **BND classified fixed income, never equity** — asset-class test
  (`test_bnd_classified_fixed_income`) + sector bucket "Fixed Income".
- ✅ **Entries always identify their plan** — every entry card carries the selected
  plan pill; the Entries tab refuses to render legs without a selected plan.
- ✅ **All quotes refreshable** — REFRESH QUOTES + RECOMPUTE (all legs) and per-leg
  refresh actions; stale badges show per-leg quote age.
- ✅ **No test fixture affects production metrics** — the 3 quarantined phase_e fills
  are excluded from every number here (deployed $0 across all plans); the event
  banner and Audit tab flag them until the approved cleanup runs.

## Where each requirement surfaces in the workstation

exact legs/dollars/shares → PLANS + ENTRIES · before/post-sale/post-plan → PRO-FORMA
sector/factor/look-through deltas → PRO-FORMA + LOOK-THROUGH · return history → PERFORMANCE
income/fee impact → PRO-FORMA scalar deltas + PERFORMANCE vs-sold · volatility/drawdown → PERFORMANCE
overlap → LOOK-THROUGH issuer table · entries → ENTRIES · rejected alternatives → REJECTED
PM conclusion → PM MEMO · audit trail → AUDIT · portfolio-wide book → CAPITAL BOOK

Screenshots: `docs/ui_redesign/screenshots/redeploy_workstation/*.png` (1680px, live data).

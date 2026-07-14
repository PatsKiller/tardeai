# FCNTX event #144 — operator decision packet (Phase 19)

Generated 2026-07-14 · generator `phase_b_2.0.0` · decision policy `decision_1.0.1` · plan version 25
· **advisory only — this desk places no orders.**

## 1. Event

Sold **FCNTX** (Fidelity Contrafund) in `schwab_rollover_ira` on 2026-07-14. Net proceeds
**$107,023.01** — settlement **verified**, fully deployable. Regime at generation: **risk-off**.
No production fills recorded. FCNTX trailing-distribution yield 4.27% (KNOWN — trailing distributions
include capital-gain distributions; ordinary-vs-capital-gain split unavailable; not guaranteed recurring).

## 2. System-recommended lean

**Plans B (partial multi-sector restoration) and F (staged deployment) are effectively tied**
(~54–58 depending on the quote refresh; each recompute shows the live scoreboard). The race is honest:
B wins on sector-restoration/fees when sector-ETF quotes are fresh; F wins on risk-suitability in the
risk-off regime. Weights are operator-configurable (`config/redeploy_decision_weights.yaml`) — raising
`regime_suitability` above its default 5% tilts the lean decisively to F. Alternatives and do-not-choose
reasons render on the DECISION tab with quantified gaps. The leg table below shows the B allocation at
the packet's generation snapshot; the live DECISION tab always shows the current one.

| Leg | Role | Dollars | Shares | Competition (lost to winner) |
|---|---|---:|---:|---|
| XLK | sector restoration: Technology | $18,148.68 | 99 | QQQ (higher fee) |
| XLC | sector restoration: Comm Services | $18,077.58 | 162 | — |
| XLF | sector restoration: Financials | $18,162.18 | 321 | — |
| XLY | sector restoration: Consumer Cyclical | $18,063.24 | 156 | — |
| XLI | sector restoration: Industrials | $17,878.41 | 99 | — |
| AGG | fixed-income ballast | $15,977.26 | 163 | BND, TLT, SHY (fee/yield/history score) |

**Exact accounting:** legs $106,715.32 + reserve $0.00 + whole-share residual **$307.69**
= **$107,023.01** = deployable. Reconciles: **TRUE**. (Every plan A–G reconciles exactly; residuals
$0–$556 are displayed, never dropped.)

**Income impact:** expected $1,567/yr on the plan (whole-plan yield 1.46%, invested-sleeve 1.47%) vs
FCNTX trailing $4,570/yr — an explicit **income reduction** in exchange for restored diversified equity
exposure (the income-oriented Plan C shows +$7,172/yr instead; see trade-off below).

## 3. Why B, and why not the others (scoreboard: B 57.9 · F 57.1 · C 54.9 · G 47.4 · D 47.0 · E 46.8 · A 44.2)

- **B (primary):** restores **68% of removed sector dollars**, 6 legs / 0 overlap flags, weighted ER
  0.073% on the invested sleeve.
- **F (runner-up, choose when timing risk should be staged):** tranche 1 = 25% toward an explicit
  ultimate target (VOO 45% / DIVI 35% / AGG 20%), reserve in BIL at 3.85% while waiting; tranche
  triggers: regime exit OR −5% growth-leg pullback (T2), +30 trading days OR −10% market drawdown (T3).
- **C (choose when income > upside):** +$7,172/yr income vs sold, but covered-call/BDC structure caps
  upside participation and restores growth only partially.
- **G (hold):** BIL at 3.85% ≈ $4,120/yr, revisit 2026-08-13; opportunity-cost reference: VOO trailing-1Y
  +12.7% (history, not a forecast).
- **A:** honestly relabeled a **strategic redesign** (45% growth / 35% dividend / 20% bonds is not a
  close replacement for an active growth mandate).
- **E (do not choose for this purpose):** gap rotation only — ITA $21,348 + XLE $2,881, **sized to the
  documented gaps** (Defense $23.5k, Energy $2.8k), surplus $82,635 reserved. Never a substitute for
  the sold mandate.
- **D:** deliberately does not restore ~$51k of removed growth exposure (stated on the plan).

## 4. Governance state (honest)

Every plan shows **ANALYTICS READY — OVERSIGHT PENDING** (B: QUOTES STALE when XLC ages out).
Oversight lanes ran for real: **Grok passed B**; the ChatGPT lane returns `needs_review`
(it declines to bless trade proposals as a matter of its own policy) — so `oversight_status`
stays **pending** and **no plan claims OPERATOR-READY**. This is the required behavior:
pending ≠ ready. Next operator action: review the lane outputs (System → oversight runs),
adjudicate, then approve the chosen plan for operator implementation review.

## 5. What could change the decision

Regime exits risk-off (favors fuller deployment / accelerates F tranches); a growth-leg −5%/−10%
entry trigger fires; portfolio gaps change materially; income priorities change (switch to C);
XLC/sector-ETF quotes stale out (refresh before implementing B).

## 6. Audit lineage

25+ rows on event #144: event created (2026-07-14), settlement verified (inferred flag — exact
time not recorded), 22+ plan-version generations with real timestamps, fixture cleanup
(operator-approved 2026-07-14), oversight runs, plan-version 24/25 generations, export requests.
Unprovable historical moments are labeled `INFERRED_FROM_CURRENT_STATE`, never given fabricated
timestamps.

## 7. Data honesty notes

- ARKQ's 23% "trailing yield" (266-day broken series) is excluded from income roles by plausibility
  guards — implausible short-series yields are data artifacts, stated in the role method.
- NVDA rejected `HISTORY_GAPPED` (price-basis break in cache — cache repair needed, not an instrument
  judgment); FANS/LPIH/SHOT/TOO `HISTORY_PROVIDER_FAILED` (no provider data).
- Prose tokens (FORUM, WOULD, UNI…) are rejected at intake as `INVALID_SYMBOL`.
- Recession scenario: **UNAVAILABLE FOR RISKY LEGS** (5Y cache predates COVID) — never rendered 0%.

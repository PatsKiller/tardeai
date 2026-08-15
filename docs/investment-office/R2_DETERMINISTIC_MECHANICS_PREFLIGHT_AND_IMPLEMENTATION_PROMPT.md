# R2 — Deterministic Mechanics: Preflight + Implementation Prompt

Parallel workstream (research governance). Isolated from live CIO/retrieval and
the production-hardening remediation line. Additive and **unwired**.

Authority: `READ_ONLY_ADVISORY`. No provider calls, no broker calls, no
production DB writes, no change to live Alex behavior.

---

## 0. Preflight (Phase 0)

Re-establish fresh remote truth before editing. `main` is actively moving under
the parallel CIO release-manifest pinning agent; never trust a remembered SHA.

```text
git fetch --prune origin
REMOTE_MAIN_SHA="$(git ls-remote origin refs/heads/main | awk '{print $1}')"
```

Return an `R2_PREFLIGHT` packet with: `remote_main_sha`, `merge_base`, `ahead_by`,
`behind_by`, `worktree_clean`, and confirmation that R1 is merged
(PR #312, merge commit `c005551a1e5da5a8d3f46d9e3018bff9bd516e7c`).

Create a fresh branch off `origin/main`:

```text
feature/research-governance-r2
```

Rebase discipline identical to R1: if `main` moves during R2, rebase again and
rerun everything. Do not merge onto a stale base.

---

## 1. Scope (additive, unwired)

R2 builds the **DETERMINISTIC_MECHANICS** and **VALUATION_MODEL** foundations.
R1 already declared the type-specific promotion gates for these evidence types
as context-dict checks; R2 supplies the actual, independently-validated
implementations those gates are meant to guard.

New modules (flat under `scripts/lib/research_governance/`, matching R1 layout):

- `fixed_income.py` — bond pricing/yield, Macaulay + modified duration,
  convexity, yield-to-worst (YTW).
- `etf_mechanics.py` — ETF premium/discount from time-aligned NAV vs market price.
- `valuation.py` — reverse-DCF and general valuation mechanics (deterministic
  math, assumption-conditional).

Tests: `tests/test_research_governance_r2_*.py` (one file per module, plus one
acceptance/adversarial file).

**Not in R2:** no wiring into `promotion_gate.py` production path beyond adding
the deterministic/valuation **result payloads + golden validators** the gates
already reference. No live Alex, CIO synthesis, production retrieval, or broker
changes. R3 (Almanac) and R4 (integration) remain unauthorized.

---

## 2. Non-negotiable distinctions (must be enforced, not just documented)

1. **Deterministic only given complete, verified inputs and explicit
   conventions.** A mechanics function never silently defaults a missing
   required input. Missing/incomplete inputs → `UNAVAILABLE` (fail-closed), not
   a guessed result.
2. **YTW is UNAVAILABLE without the call schedule.** A bond with an embedded
   call cannot compute yield-to-worst without the call dates/prices. Absent a
   call schedule, return `UNAVAILABLE` with a reason; never silently fall back to
   yield-to-maturity and label it YTW.
3. **ETF premium/discount requires time-aligned NAV and market price.** NAV and
   price must share the same as-of timestamp (same trading day at minimum, and
   fail closed on timezone/mixed-precision mismatches — reuse R1's datetime
   fail-closed conventions). Non-time-aligned inputs → `UNAVAILABLE`.
4. **Reverse DCF is deterministic mathematics CONDITIONAL on assumptions, not
   financial truth.** The output is `VALUATION_INPUT` influence, never a
   standalone truth claim. Every reverse-DCF result must carry
   `assumption_provenance` and `scenario_sensitivity`; a result without both is
   non-promotable.

These map directly to the existing R1 `promotion_gate` type-specific gates
(`DETERMINISTIC_MECHANICS` and `VALUATION_MODEL`); R2 must supply typed result
objects those gates can validate.

---

## 3. Fixed-income mechanics (`fixed_income.py`)

Golden-validated, stdlib-only, convention-explicit.

- `bond_price(coupon, yield_, maturity_years, frequency, face, ...)` — standard
  present-value with explicit `day_count_convention` (e.g. `ACT/ACT`, `30/360`),
  `compounding` (periodic vs continuous), `frequency` (coupons/year).
- `macaulay_duration(...)` and `modified_duration(...)` — closed-form with the
  SAME conventions; cross-check against a finite-difference bump.
- `convexity(...)` — second-order price sensitivity.
- `yield_to_maturity(...)` — inverse pricing (bounded root solve, fail-closed on
  no-root / non-finite).
- `yield_to_worst(...)` — REQUIRES a `call_schedule` (list of call date/price).
  Empty/missing `call_schedule` → `UNAVAILABLE`, reason `"call_schedule_required"`.
  Otherwise returns the min over maturity-yield and each call-yield.

Golden vectors must be computed independently (closed-form for
price/duration/convexity; a hand-checked YTW example with an explicit call
schedule) and asserted to high tolerance — never "value in a plausible range".

---

## 4. ETF mechanics (`etf_mechanics.py`)

- `premium_discount(nav, market_price, nav_as_of, price_as_of)` →
  `(market_price - nav) / nav` expressed in basis points AND percent.
- Fail-closed time alignment: `nav_as_of` and `price_as_of` must parse to the
  same trading date (strict ISO-8601, timezone-aware, reuse R1 `retrieval_contract`
  datetime conventions). Mismatched/missing dates → `UNAVAILABLE`,
  reason `"not_time_aligned"`.
- Optional `intraday_staleness` guard: reject NAV/price pairs whose as-of gap
  exceeds a caller-declared threshold when NAV is point-in-time EOD.

Golden: a hand-checked premium/discount example; fail-closed cases for
time-aligned vs non-aligned, missing NAV, missing price, negative NAV.

---

## 5. Valuation / reverse-DCF (`valuation.py`)

- `reverse_dcf(market_price, cash_flows, discount_rate, terminal_growth, ...)`
  solves for the implied growth rate (or implied discount rate) that equates the
  DCF to the market price. Bounded root solve; fail-closed on no-root/divergence.
- Every result is wrapped in a typed `ReverseDCFResult` carrying:
  - `assumption_provenance` (each assumption: source_id + value + rationale),
  - `scenario_sensitivity` (base/bear/bull deltas),
  - the `calibration` block (dataset/metric/split) referenced by R1's
    `_valuation_calibration` gate.
- The module returns **deterministic math**, never a truth label. Influence is
  `VALUATION_INPUT`; no promotion may claim the output IS the price.

Golden: an analytically-constructed perpetuity/growing-perpetuity case with a
closed-form implied rate, plus a multi-period case checked against a
forward-computed NPV to a tight tolerance.

---

## 6. Typed results + validators (consume R1 contracts)

Add typed result dataclasses in `results.py` (or a new `mechanics_results.py` if
cleaner) for:

- `BondMechanicsResult` (price/duration/convexity/ytw + conventions + status)
- `ETFPremiumDiscountResult` (nav, price, as-of pair, premium_bps, status)
- `ReverseDCFResult` (implied rate, assumptions, sensitivity, calibration)

Each carries `status` (`OK` / `UNAVAILABLE`) and a `validate()` returning problems
([] = coherent). Reuse R1's `_stable_hash`, `FrozenDict`, and fail-closed numeric
checks. `status="OK"` MUST require all material outputs to be present and finite
(mirror R1's P1-4 rule).

---

## 7. Acceptance (R2_mechanics profile)

Replace the current `not_implemented: True` `R2_mechanics` profile with real
phase-aware gates. R2 reuses R1's required foundation gates (a regression —
R1 must still pass) and adds mechanics-specific required_runtime gates:

```text
R2_mechanics:
  required_runtime:
    RGA-1 .. RGA-14 (R1 foundation regression — unchanged)
    RGA-17 fixed_income_golden        (duration/convexity/ytw vectors + call-schedule rule)
    RGA-18 etf_premium_discount_golden(time-aligned rule + premium/discount vectors)
    RGA-19 reverse_dcf_golden         (closed-form + forward-NPV cross-check)
  required_contract:
    RGA-20 mechanics_typed_results    (typed results + validators + status-OK completeness)
  not_in_scope: RGA-15 (R3), RGA-16 (R4)
```

`NOT_IN_SCOPE` never counts as PASS. RGA-17/18/19/20 must FAIL on:
- YTW without a call schedule,
- ETF premium/discount with non-time-aligned NAV/price,
- reverse-DCF without `assumption_provenance` + `scenario_sensitivity`,
- `status="OK"` with a missing material output.

---

## 8. Scope guard

Update `pr_scope_guard.py` allowlist to cover R2's additive files (already
matched by `scripts/lib/research_governance/*` and `tests/test_research_governance*`).
Do **not** weaken the denylist. Any shared CIO/retrieval/release file still
fails. Keep the strict remote-base merge-acceptance rule from R1 P2-1.

---

## 9. Isolated CI

Reuse the R1 `research-governance` workflow (runs `tests/test_research_governance*.py`)
so R2's new tests execute in the isolated lane with `READ_ONLY_ADVISORY=1`,
`ENABLE_TELEGRAM=0`, `CIO_TELEGRAM_INTERDICT=1`, zero provider/broker/DB calls.
Do not add a new `main` required check.

---

## 10. Final validation + return packet

After fixes and fresh-main rebase:

```text
python3 -m pytest tests/test_research_governance*.py -q
python3 scripts/run_research_governance_acceptance.py R2_mechanics
python3 scripts/lib/research_governance/pr_scope_guard.py
```

Push exact final head; require all three workflows
(`research-governance`, `cio-production-hardening-ci`, `release-readiness`) green
on that exact head; update the PR body to exact parity (base/head/test-count/
acceptance/scope-guard/CI/deferred-limits/R3-R4-unauthorized); keep the PR draft;
do **not** merge automatically.

Return `R2_MECHANICS_RESULT`:

```text
pr, branch, base_sha, head_sha, rebased_current
fixed_income_golden, ytw_call_schedule_rule
etf_premium_discount_golden, time_aligned_rule
reverse_dcf_golden, assumption_conditional
typed_results_validate, status_ok_requires_outputs
scope_guard, r2_acceptance, tests_total, tests_failures
ci_exact_final_head {research_governance, cio_hardening, release_readiness}
provider_calls: 0, broker_calls: 0, production_db_writes: 0
live_cio_behavior_changed: false
authority: READ_ONLY_ADVISORY
R3_authorized: false, R4_authorized: false
merge_recommended: (true only when every gate above is green)
```

---

## Definition of done (R2)

- Every deterministic-mechanics function is golden-validated against an
  independently computed reference, not a plausible range.
- YTW cannot be produced without a call schedule; ETF premium/discount cannot be
  produced without time-aligned NAV/price; reverse-DCF always carries
  assumptions + sensitivity and is never labeled financial truth.
- Typed results enforce `status="OK"` ⇒ all material outputs present and finite.
- The branch is rebased on current `main`, scope-guard passes on the fresh remote
  base, all three workflows are green on the exact final head, and the PR body is
  at exact parity.
- `READ_ONLY_ADVISORY` remains intact; R3/R4 remain unauthorized.

Final principle: R2 is deterministic mathematics + conventions, governed by the
R1 contracts. It is **not** financial truth, and it does **not** wire anything
into live behavior.

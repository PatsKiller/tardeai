# R1 Formula & Reference Audit

Status:      HISTORICAL
as_of:       2026-08-14T22:06:15-04:00
Measured at: efcc51365 / not measured

Research governance — PR #312, branch `feature/research-governance-v1`.

This is the authoritative R1 record of **which formula is implemented, against
which version-of-record source, where the code lives, what the golden fixture
proves, and what the boundary/unit conventions are**. It is a governance
artifact, not a tutorial: every entry ends with an explicit **review status**.

Scope note: R1 is **contract-only** for retrieval and **statistical-foundation
only** for the rest. CPCV *path* construction, durable persistence, production
retrieval wiring, and the knowledge-base integration are **deferred** (R2+).

---

## Statistical family

| Method | Version of record | Working paper (if any) |
| ------ | ----------------- | ---------------------- |
| Bonferroni | Bonferroni (1936) / Dunn (1961) FWER control | — |
| Holm | Holm (1979) *Scand. J. Statist.* | — |
| Benjamini–Hochberg (BH-FDR) | Benjamini & Hochberg (1995) *JRSS-B* | — |
| PSR | Bailey & López de Prado (2012) SSRN 1821643 | yes |
| DSR | Bailey & López de Prado (2014) *Journal of Portfolio Management* 40(5):94 | SSRN 2460551 |
| PBO / CSCV | Bailey, Borwein, López de Prado & Zhu (2017) *Journal of Computational Finance* 20(4) | SSRN 2326253 (2015) |
| White Reality Check | White (2000) *Econometrica* 68(5):1097 | — |
| STW trading-rule bootstrap | Sullivan, Timmermann & White (1999) *Journal of Finance* 54(5):1647 | — |
| STW calendar-family use | Sullivan, Timmermann & White (2001) *Journal of Econometrics* 105(1):249 | — |
| Purging | López de Prado (2018) *Advances in Financial Machine Learning*, Wiley, Ch. 7 | — |
| Embargo | López de Prado (2018) *Advances in Financial Machine Learning*, Wiley, Ch. 7 | — |
| Combinatorial purged splits | López de Prado (2018) *Advances in Financial Machine Learning*, Wiley, Ch. 12 | — |

> **Explicit distinction (P1-2):** PBO uses **CSCV** (Combinatorially Symmetric
> Cross-Validation) from Bailey et al. (2017), a *Journal of Computational
> Finance* paper. AFML **CPCV** (Combinatorial **Purged** Cross-Validation) is a
> different method from Chapter 12 of López de Prado's book and is modeled as a
> `book_chapter` source. They are **not** conflated.

---

## 1. Bonferroni

- **method**: Bonferroni (FWER control)
- **version_of_record**: Bonferroni (1936) / Dunn (1961)
- **working_paper**: none
- **formula/algorithm**: adjusted p = min(1, m · p_i); reject if adjusted ≤ α.
- **code location**: `scripts/lib/research_governance/multiple_testing.py::bonferroni`
- **golden fixture**: `[0.001, 0.01, 0.2, 0.5]`, α = 0.05 → rejected `[T, T, F, F]` (`acceptance_checks._check_multiple_testing`)
- **units/frequency convention**: n/a (p-values)
- **boundary convention**: malformed / non-finite / out-of-[0,1] p-values **raise** (never clamped); α ∈ (0,1).
- **Trade AI extension**: Grade A/B confirmatory use is restricted to Bonferroni/Holm (BH-FDR is exploratory only).
- **known limitation**: most conservative member of the family.
- **review status**: `PASS` (golden + strict input validation)

## 2. Holm

- **method**: Holm–Bonferroni step-down (FWER control)
- **version_of_record**: Holm (1979)
- **working_paper**: none
- **formula/algorithm**: sort p ascending; adjusted p_(k) = max( prior adjusted, (m − k + 1) · p_(k) ).
- **code location**: `scripts/lib/research_governance/multiple_testing.py::holm`
- **golden fixture**: monotone non-decreasing adjusted p-values; rejection consistency (`results.MultipleTestingResult.validate`)
- **units/frequency convention**: n/a
- **boundary convention**: same strict input validation as Bonferroni.
- **Trade AI extension**: allowed for Grade A/B confirmatory; recomputed from the complete frozen family.
- **known limitation**: FWER control still conservative vs FDR for large families.
- **review status**: `PASS`

## 3. Benjamini–Hochberg (BH-FDR)

- **method**: Benjamini–Hochberg FDR step-up
- **version_of_record**: Benjamini & Hochberg (1995)
- **working_paper**: none
- **formula/algorithm**: q_(k) = min( (m/k) · p_(k), running_min ) from largest to smallest; reject if q ≤ α.
- **code location**: `scripts/lib/research_governance/multiple_testing.py::benjamini_hochberg`
- **golden fixture**: distinct from Bonferroni/Holm; never silently conflated.
- **units/frequency convention**: n/a
- **boundary convention**: strict input validation.
- **Trade AI extension**: **exploratory only** — rejected for Grade A/B confirmatory promotion (`promotion_gate._CONFIRMATORY_MT_METHODS`).
- **known limitation**: assumes independent/positively-dependent tests (no dependence correction).
- **review status**: `PASS`

## 4. Probabilistic Sharpe Ratio (PSR)

- **method**: PSR
- **version_of_record**: Bailey & López de Prado (2012)
- **working_paper**: SSRN 1821643
- **formula/algorithm**:

  z = (ŜR − SR*) · √(n−1) / √( 1 − γ₃·ŜR + ((γ₄ − 1)/4)·ŜR² )

  PSR = Φ(z); γ₃ = skewness, γ₄ = **raw** (Pearson) kurtosis (normal = 3).

- **code location**: `scripts/lib/research_governance/deflated_sharpe.py::psr`
- **golden fixture**: translation invariance of the deflated benchmark; degenerate higher-moment denominator → `UNAVAILABLE`.
- **units/frequency convention**: per-period Sharpe for confirmatory use (see DSR).
- **boundary convention**: denominator-square validated **before** sqrt; non-positive / non-finite → `UNAVAILABLE` (never a silent 0 or a raise).
- **Trade AI extension**: fail-closed — the DSR wrapper never upgrades an underlying PSR `UNAVAILABLE` to `OK`.
- **known limitation**: assumes i.i.d. returns (no autocorrelation/HAC).
- **review status**: `PASS`

## 5. Deflated Sharpe Ratio (DSR)

- **method**: DSR
- **version_of_record**: Bailey & López de Prado (2014) *JPM* 40(5):94, DOI `10.3905/jpm.2014.40.5.094`
- **working_paper**: SSRN 2460551
- **formula/algorithm**:

  SR\* = μ + σ · maxZ

  maxZ = (1 − γ) · Z⁻¹(1 − 1/N) + γ · Z⁻¹(1 − 1/(N·e))

  DSR = PSR(ŜR, SR\*), where μ/σ are the mean/std of the N trial Sharpes, γ is
  Euler–Mascheroni, e is Euler's number, Z⁻¹ is the normal inverse CDF.

- **code location**: `scripts/lib/research_governance/deflated_sharpe.py::deflated_sharpe` (+ `deflated_benchmark_sr`)
- **golden fixture**: `_dsr_trials()` → benchmark = `0.503279766668363` (frozen, 1e-9 tolerance); translation invariance; frequency-normalization golden equivalence.
- **units/frequency convention (P0-10)**: confirmatory DSR operates on **per-period** Sharpe. `ANNUALIZED` input requires a positive integer `periods_per_year` and is divided by √(periods_per_year) **before** the nonlinear PSR/DSR equation, so economically equivalent inputs produce identical z/benchmark. Mixed/missing conventions → `UNAVAILABLE`.
- **boundary convention**: trial count must be known and consistent (`n_trials == len(trial_sharpes)`); zero Sharpe variance → `UNAVAILABLE`.
- **Trade AI extension**: translation-invariant benchmark (trial-distribution mean is part of SR\*).
- **known limitation**: benchmark assumes the search family's trial-Sharpe distribution is fully enumerated; effective-trials estimation is **not** implemented.
- **review status**: `PASS`

## 6. Probability of Backtest Overfitting (PBO / CSCV)

- **method**: PBO via CSCV
- **version_of_record**: Bailey, Borwein, López de Prado & Zhu (2017) *JCF* 20(4), DOI `10.21314/JCF.2016.322`
- **working_paper**: SSRN 2326253 (2015) — held as a **separate** field, never mixed with the version-of-record
- **formula/algorithm**:
  1. Split T into S disjoint equal submatrices (S even).
  2. Enumerate C(S, S/2) IS/OOS combinations.
  3. Select IS-best config n\* (ties → all tied configs, average their ω).
  4. ω = mean rank / (N+1); λ = ln(ω/(1−ω)).
  5. PBO = fraction of combinations with λ < 0.
- **code location**: `scripts/lib/research_governance/pbo.py::cscv_probability_of_backtest_overfitting`
- **golden fixture**: stable winner → low PBO (< 0.5); rotating winner → high PBO (> 0.5); tie permutation-invariance; default full enumeration (`C(8,4)=70`).
- **units/frequency convention**: matrix is **N configs × T observations**; `performance ∈ {sharpe, mean}`.
- **boundary convention (P1-1)**: λ == 0 (ω == 0.5, exact OOS median) **counts as NOT overfit** — `lambda_zero_policy = "counts_as_not_overfit"`. Zero-variance stream → Sharpe undefined → `UNAVAILABLE`.
- **Trade AI extension**: full-enumeration resource ceiling (`1_000_000` combos → `COMPUTATION_INFEASIBLE`); reservoir-subsampled approximation is explicit and **not** allowed for confirmatory use; tie rate reported.
- **known limitation**: approximation does not quantify uncertainty; only full enumeration is confirmatory-valid.
- **review status**: `PASS`

## 7. White Reality Check

- **method**: Reality Check (data-snooping)
- **version_of_record**: White (2000) *Econometrica* 68(5)
- **working_paper**: none
- **formula/algorithm**:

  V = √n · max_k mean(f_k)

  Null: recenter each rule to zero mean (least-favorable config), then apply the
  **same** stationary-bootstrap index sequence across all rules (preserving
  cross-rule dependence). p = (count{V\* ≥ V} + 1) / (B + 1).

- **code location**: `scripts/lib/research_governance/bootstrap_reality_check.py::reality_check_pvalue`
- **golden fixture**: null family not spuriously rejected; obvious alternative rejected; family correction not more favorable than winner-only.
- **units/frequency convention**: stationary bootstrap (Politis–Romano), `mean_block_length ≥ 1`.
- **boundary convention**: p-value resolution = 1/(B+1); confirmatory use requires resolution < α and a bound family (`family_id` + `family_definition_hash` + `trial_family_id`).
- **Trade AI extension**: recentering under H0 is enforced (raw-resample bug is rejected by design).
- **known limitation**: stationary bootstrap block-length choice is user-supplied; no automatic block-length selection.
- **review status**: `PASS`

## 8. STW calendar-family use

- **method**: Sullivan–Timmermann–White calendar-family Reality Check
- **version_of_record**: STW (2001) *Journal of Econometrics* 105(1)
- **working_paper**: none
- **formula/algorithm**: wraps `reality_check_pvalue` over the **entire frozen searched family** of a calendar rule (never the lone winner).
- **code location**: `scripts/lib/research_governance/bootstrap_reality_check.py::calendar_family_reality_check`
- **golden fixture**: calendar-family path delegates to the RC fixture; confirmatory requires `family_definition_hash` + `confirmatory=True`.
- **units/frequency convention**: same stationary bootstrap as RC.
- **boundary convention**: a calendar family is a named collection of differentials — a lone best variant is not a family.
- **Trade AI extension**: pairs with the separately-governed `stock_traders_almanac` source; STW is the challenge study.
- **known limitation**: no Almanac integration in R1 (deferred).
- **review status**: `PASS` (contract-level; calendar-family integration deferred)

## 9. Purging

- **method**: label-overlap purging
- **version_of_record**: López de Prado (2018) *AFML*, Wiley, Ch. 7
- **working_paper**: none
- **formula/algorithm**: a training sample is removed if its label interval overlaps **any** test sample's label interval (inclusive overlap).
- **code location**: `scripts/lib/research_governance/cv.py::purge_train_indices` (+ `_excluded_indices`)
- **golden fixture**: purged k-fold removes post-test overlap; multi-block CPCV removes sandwiched group 1.
- **units/frequency convention**: integer label steps or `timedelta` labels.
- **boundary convention**: samples must be **chronologically ordered by label start** (validated); unordered input → `ValueError`.
- **Trade AI extension**: embargo is applied **after each test block**, not just the global last test index.
- **known limitation**: single-label (point-in-time) overlap only; no probabilistic-label overlap (AFML §7.5) in R1.
- **review status**: `PASS`

## 10. Embargo

- **method**: post-test embargo
- **version_of_record**: López de Prado (2018) *AFML*, Wiley, Ch. 7
- **working_paper**: none
- **formula/algorithm**: a **post-test** training sample whose label begins within `test_end + embargo` is removed; **pre-test** samples are never embargoed (future-direction leakage control only).
- **code location**: `scripts/lib/research_governance/cv.py::_excluded_indices`
- **golden fixture**: walk-forward embargo erases only post-test history; sample just outside window is retained.
- **units/frequency convention**: integer steps or `timedelta`; `0` disables.
- **boundary convention**: chronological ordering precondition (same as purging).
- **Trade AI extension**: per-block embargo geometry for non-contiguous test groups.
- **known limitation**: embargo width is user-supplied.
- **review status**: `PASS`

## 11. Combinatorial purged splits (CPCV step 1)

- **method**: combinatorially-symmetric purged train/test splits
- **version_of_record**: López de Prado (2018) *AFML*, Wiley, Ch. 12 (hardcover ISBN `9781119482086`, e-book ISBN `9781119482109`)
- **working_paper**: none
- **formula/algorithm**: partition the index axis into G contiguous groups; for every combination of `n_test_groups`, produce one `{train, test}` partition with label-overlap purging and per-block embargo.
- **code location**: `scripts/lib/research_governance/cv.py::combinatorial_purged_splits` (+ legacy alias `combinatorial_purged_cv`)
- **golden fixture**: test groups {0,2} → sandwiched group 1 embargoed, sample 5 retained; `C(4,2)=6` partitions.
- **units/frequency convention**: n/a
- **boundary convention**: `1 ≤ n_test_groups < n_groups`; `n_samples ≥ n_groups`.
- **Trade AI extension**: explicit R1 boundary — **splits only**.
- **known limitation**: **CPCV path construction (chaining splits into full P&L paths/scenarios) is DEFERRED**, not implemented in R1.
- **review status**: `PASS` (split generation; path construction deferred)

---

## Cross-cutting conventions

- **Self-digest ≠ provenance**: every statistical result must be carried by a
  verified `GovernedResultReceipt` inside one immutable `PromotionEvidenceBundle`
  for a Grade A/B promotion. A bare self-digested typed result is rejected.
- **Cross-result identity**: hypothesis, protocol, trial family, family
  definition, dataset, and code must match **exactly** across all child results.
- **Frozen family**: `FrozenTrialFamilyReceipt` is deeply immutable; OOS economic
  identity excludes `oos_generation`; a consumed period cannot be refreshed by
  ID/generation changes.
- **Review status legend**: `PASS` = golden-validated and acceptance-green; `DEFERRED` = out of R1 scope.

## Review status summary

All R1 statistical foundations are `PASS`. No CPCV path construction, no
production retrieval, no Almanac/knowledge-base wiring, no durable persistence,
and no R2/R3/R4 behavior is present in this PR.

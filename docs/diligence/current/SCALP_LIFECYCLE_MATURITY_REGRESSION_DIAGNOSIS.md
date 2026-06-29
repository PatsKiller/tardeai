# Scalp Lifecycle Maturity — 3.25 Regression Diagnosis

_Why `SCALP_LIFECYCLE_MATURITY.md` regressed to 3.25/5 after PR #20, and the fix. No scores were
inflated — the underlying alert/liquidity/trace behavior was already correct; the detector was fragile._

## Symptom

After PR #20 the generated `SCALP_LIFECYCLE_MATURITY.md` read:

* Combined 3.25/5, Momentum Scalp 3.8/5, Social Scalp 2.5/5
* `alerts_test: False`, `liquidity_test: False`, `trace_test: False`

## Root cause — environment-dependent evidence runner (NOT a code regression)

`compute_scalp_lifecycle_maturity._run_test` executed each evidence test with **`sys.executable`** — the
interpreter that happened to invoke the generator. The three failing evidence tests import modules that
call `from dotenv import load_dotenv` at module top:

| Evidence test | Imports | First line that fails |
|---------------|---------|-----------------------|
| `test_social_scalp_decision_alerts.py` (`alerts_test`) | `social_scalp_scanner` | `from dotenv import load_dotenv` |
| `test_momentum_scalp_liquidity_unknown.py` (`liquidity_test`) | `market_quote_provider` | `from dotenv import load_dotenv` |
| `test_social_traceability.py` (`trace_test`) | `social_scalp_scanner` | `from dotenv import load_dotenv` |

When `SCALP_LIFECYCLE_MATURITY.md` was regenerated under the **bare sandbox python** (which has no
`dotenv`), all three tests raised `ModuleNotFoundError` **at import** — before any assertion ran. The old
`_run_test` returned `returncode != 0` → `False`, which `score_dimensions` scored as **0.0** for
`social_only_catalyst_discipline`, `liquidity_data_freshness`, and `traceability`, dragging the combined
score to 3.25.

Under the **venv interpreter** (`.venv/bin/python` — the real runtime, and the same interpreter cron and
CI use, which HAS `dotenv`), all three tests pass and the generator computes the correct **4.4/5**.

## Per-check classification

| Check | Stale detector or real regression? | Evidence |
|-------|-----------------------------------|----------|
| `alerts_test` | **Neither — environment fragility.** Alert semantics are correct: social-only never GO; SCOUT/WATCH/WAIT only; GO alert suppressed when route≠GO. | `test_social_scalp_decision_alerts.py` = 15/15 under venv |
| `liquidity_test` | **Neither — environment fragility.** Validation fast path stays fail-closed on stale/missing/unknown quote; no gate weakened by source maturity 4.5. | `test_momentum_scalp_liquidity_unknown.py` = 10/10 under venv |
| `trace_test` | **Neither — environment fragility.** `discovery_trace_id` + route/scout fields persist scan→signal→proposal→validation; SEC adds `source_trace_id`. | `test_social_traceability.py` = 11/11 under venv |

None of the three was a real regression, and none was stale logic looking for old "paper"/pre-Scout
names — the tests themselves are current. The defect was solely that the generator ran them under an
interpreter that could not import their runtime dependency.

## Fix applied

`scripts/compute_scalp_lifecycle_maturity.py`:

1. **Evidence runs under the venv first.** `_evidence_interpreters()` returns `.venv/bin/python` ahead of
   `sys.executable`, so evidence reflects real behavior, not the caller's environment. The generator now
   produces 4.4 deterministically regardless of which interpreter invokes it.
2. **Tri-state evidence** (`_run_test_state` → `PASS` / `FAIL` / `ENV_ERROR`). A `FAIL` (assertions ran
   and failed) is a real regression and still scores 0. An `ENV_ERROR` (test could not be imported in any
   available interpreter) is **indeterminate** — it is surfaced as a prominent `evidence_indeterminate`
   warning telling the operator to re-run under `.venv`, rather than silently emitting a phantom low score.
3. Report now records `evidence_interpreter` + `maturity_separation` (engineering vs empirical sample;
   source maturity / latency readiness reported separately and do NOT lift this score).

## Result

* Combined **4.4/5**, momentum 4.4, social 4.4, engineering/control 5.0, `meets_4_5: False`.
* Capped at 4.4 by the **empirical validation sample (2/30 confirmed closed, trade IDs 45 & 22)** — the
  intended cap, unchanged. **Strategy maturity 4.5+ is NOT claimed.**

## Safety impact

None. No scores were inflated (the cap is unchanged; the fix restores correctly-earned evidence). No
gate, freshness, TTL, route policy, liquidity, risk, account policy, or kill switch was touched. Social
Scouts remain non-tradeable; social-only stays WATCH/WAIT/SCOUT; large-float scouts stay manual-review.
No live broker writes; operator confirmation / 2FA untouched.

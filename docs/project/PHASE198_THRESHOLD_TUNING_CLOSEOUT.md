# PHASE 198 — Advisory Threshold Tuning Framework — CLOSEOUT

Status:      HISTORICAL
as_of:       2026-06-02T13:48:02-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~13:40 ET · Alpaca **paper** only · learning/backtest; no execution

---

## What shipped
- `scripts/tune_advisory_thresholds.py` — replays the live 191D `score()` (globals monkeypatched per
  candidate) over bar-validated closed-trade MFE-peak states; sweeps thresholds; recommends.
- Table `advisory_threshold_tuning` + endpoint `GET /api/v2/atm/advisory-threshold-tuning`.
- Added to `run_protection_pipeline.sh` (refreshes each run).

## Result
24 measurable closed cases, 20 gave back. **Current thresholds capture 55%** of give-back trades at
peak (false-positive flag rate 62.5%). **Recommended** LOCK 8→10 holds capture, cuts flag rate to
58.3% (FP 4→3). Capture caps at 55% across all combos — the rest are tiny (<3%) give-backs not worth
flagging.

## Closeout fields
- **Phase 198 complete:** ✅ YES (framework operational)
- **Tuner implemented + run:** ✅ YES (reuses live `score()` — no divergence)
- **Backtest over bar-validated outcomes:** ✅ 24 cases
- **Recommendation produced:** ✅ LOCK 8→10 (marginal; fewer false positives, same capture)
- **Applied to live thresholds:** **NO — deliberately not** (small/synthetic sample; advisory params,
  operator decision)
- **Endpoint live:** ✅ `/api/v2/atm/advisory-threshold-tuning`
- **Scheduled:** ✅ in protection pipeline
- **No execution / no stop changes / no GO-WAIT / no strategy:** ✅ YES
- **Live trading:** ZERO · **Level 7:** PROHIBITED
- **Next recommended gate:** **Phase 199 — wait-and-tune:** re-run the framework once real advised
  trades (ANY/SNOW + future) close and the reconciler produces `confirmed`/`contradicted` accuracy;
  apply a threshold change only when the sample is real and large enough. Optionally surface the
  tuning recommendation in the v3 Journal Protection tab.

## Honest stance
The framework is the deliverable; the *recommendation is intentionally not applied*. With 24
retrospective cases and zero live-advised closes, changing the model now would be overfitting to a
synthetic sample. The harness is wired to re-run automatically so the recommendation sharpens as real
outcomes accrue.

## Guardrail attestation
No live account/endpoint/broker mode, no live trades, no holdings mutated, no stops moved, no
strategy/config/GO-WAIT changes, Level 7 not enabled, auto-update not run. Reused live scoring logic;
no thresholds auto-applied. DB writes limited to the tuning summary table.

# Catalyst Calibration Monitor (2026-06-08)
Tracks per-type calibration multipliers over time so the calibration loop is observably sharpening.

- `scripts/catalyst_calibration_monitor.py` (daily cron `40 5 * * *`, read-only): snapshots per-type
  {samples, hit_rate, weight_multiplier, trusted} + totals → data/runtime/catalyst_calibration_history.json
  (last 90). Detects newly-trusted types, lost-trust, and multiplier shifts (|Δ|≥0.10) vs prior; status
  SHARPENING / STABLE / REGRESSED.
- Baseline: 4529 settled, 4310 credible, 7 trusted types of 16.
- v3: `/api/v2/hermes/catalyst-calibration` (per-type table + trend + recent transitions); System→Hermes
  "Catalyst Calibration" card (type / samples / hit-rate / multiplier / trusted).
- As classifier-labeled catalysts settle on news-covered symbols, hit-rates + multipliers refine and more
  types cross MIN_SAMPLES → trusted; this monitor makes that sharpening visible. Read-only; no scoring change.
Cadence: calibration 05:30 → this monitor 05:40 → maturity pipeline 05:45 → attribution/tier monitor 06:00.

# PHASE 212C — Hermes Shadow Install (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T15:33:32-04:00
Measured at: efcc51365 / not measured

**N/A — no newer build exists** (212B: 0.16.0 is latest). A shadow install of a *newer* build is impossible;
shadowing the same 0.16.0 would only reproduce the known limitation (no value). No shadow venv created; prod
venv and ~/.hermes untouched; no service changes; no credentials copied. Instead, 212E tested alternative
**command shapes** on the current build (the only remaining avenue for a headless fix without an upgrade).

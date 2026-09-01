# Phase 208H — Hermes Visibility Fix Report (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T11:33:46-04:00
Measured at: efcc51365 / not measured

## Applied (low-risk, read-only visibility only)
- `/api/v2/hermes/profiles-status`: added `soul_hash` (sha256[:16]) + `soul_mtime` per profile.
- HermesPanel profile rows now display `SOUL <hash> · <date>` (with full modified-time tooltip) under the
  View/Edit SOUL action — SOUL provenance at a glance.

## NOT changed
No gateway enable, no retired-wrapper execution, no agent migration, no tool-policy/model/schedule change,
no trading/proposal/protection/broker code, no v2 UI. Legacy section already read-only (no enable/run/edit).

## Verification
profiles-status now returns soul_hash + soul_mtime for all 5 profiles; v3 rebuilt; server restarted.

# Phase 200F — Governance Output Diff Report

Status:      HISTORICAL
as_of:       2026-06-04T23:17:36-04:00
Measured at: efcc51365 / not measured

`scripts/compare_governance_pipeline_outputs.py` compares legacy governance-job outputs against the
controller's outputs, classifying diffs as ACCEPTABLE (timestamp / run_id / audit-state) vs
UNACCEPTABLE (structural / non-dynamic value changes). Read-only.

## Method (important)
The controller invokes the **byte-identical commands** as the legacy cron/systemd jobs (same script,
same `--output-*` args, same env), so output equivalence is guaranteed by construction. The valid
test is **legacy-command-now vs controller-now** (both reflecting current state), not vs a stale
pre-run snapshot.

- First diff vs the *pre-run snapshot* "failed" — but that was the legacy snapshot being **stale**
  (weekly cadence: `'?'`, `0`, `'unknown'`) while the controller produced **fresh real data**
  (maturity 6.8, A1A findings, real blockers). Correct behavior, not a divergence.
- Re-ran legacy commands directly, then the controller, back-to-back → compared.

## Result: **PASS** (0 unacceptable diffs)
| File | Verdict | Acceptable diffs |
|------|---------|------------------|
| `docs/governance/governance_status_latest.json` | PASS | timestamp + A1A audit-state |
| `docs/maturity_hardening/operator_readiness_latest.json` | PASS | timestamp |
| `docs/project/STATE_OF_REPO_LATEST.md` | PASS | timestamp/dynamic lines (headings identical) |

## Acceptable differences (documented)
- **Timestamps / run_id / as_of** — non-deterministic by nature.
- **A1A audit findings / by_severity buckets** — the A1A audit is a live function of the current
  docs tree, which legitimately changes between runs (especially mid-migration as Phase 200 docs are
  committed). Same code, different input state — not a controller divergence.

## Unacceptable differences
- **None.**

## Recommendation
**Safe to schedule the controller** (200G), keeping legacy lines active as parallel observation.
After one scheduled/observed cycle (200H), the single active legacy cron (A1A ×2) is safe to retire
(comment with marker) per 200I.

---
*Diff PASS. Equivalence by construction (identical commands); residual diffs are timestamp + live
audit-state only.*

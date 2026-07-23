# Stage 1–13 Execution Recommendation

**Run ID:** 20260722-01 · **Date:** 2026-07-22 · Litmus verdict: CONDITIONAL_PASS

## Recommendation: PROCEED, with four adjustments

Stages 1–13 are implementable against the audited baseline. The repository is healthier than
the program assumes in some places (strong fail-closed rails, capability registry seed, CI write
fences) and weaker in others (no migration framework, no test DB, no feature-flag system, no
session-2FA, e2e not in CI). Recommended sequencing notes:

1. **Do not start Stage 1 until OPERATOR_TODO items A.1–A.3 are done** (test DB + lab Bitwarden
   project are hard Stage 1 inputs; the wedged production checkout should be resolved to remove
   the standing repo hazard even though the worktree isolates us).
2. **Stage 1 must introduce a real migration discipline for the new tables only** (per-migration
   up/down SQL pairs + a tracking table scoped to active-trader schema), because the existing
   ad-hoc raw-SQL convention cannot prove the program's required rollback path. Do not retrofit
   the legacy 78 migrations.
3. **Stage 5 design must resolve litmus BF-2** (dual place/modify token buckets) and Stage 5's
   Moomoo work should begin by evidencing BF-1 (broker-resident stop capability) since a negative
   answer changes the P14 plan.
4. **Add the /v3 regression baseline the program assumes**: current Playwright e2e is not in CI
   and covers only Portfolio; Stage 1 should add a minimal /v3 smoke (routes render + build
   marker) to CI so "current /v3 regression green" (night-run gate #4) is actually measurable.

## Risk notes for the overnight controller
- Gmail-send proof is currently impossible from the harness alone (drafts only) — night-run
  preflight will fail until OPERATOR_TODO A.4 lands. This is by design (§16K.10).
- Drive sync via claude.ai integration is proven (upload + download + SHA-256 verified in
  Stage 0); the repo's `gog` lane is the alternative for the unattended controller.
- The engine host runs Python 3.14.4 while CI runs 3.12/3.13 — keep new code 3.12-compatible.
- pgvector absent: any KB/embedding stage work must go through the P1 upgrade lab first.

## Suggested stage order
Unchanged from the program (1 → 13 sequential), with the Stage 5 BF-1 evidence task pulled
forward into Stage 2's capability-probe design so the Moomoo question is answered early.

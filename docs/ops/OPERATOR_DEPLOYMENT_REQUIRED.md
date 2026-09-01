# OPERATOR_DEPLOYMENT_REQUIRED

Status:      ACTIVE
as_of:       2026-08-25T09:10:05-04:00
Measured at: efcc51365 / not measured

Canonical deploy (`cio_phase2_exact_main_deploy.sh`) **refuses** unless `HEAD == origin/main`.

PR #506 head `5947d801` is **not** on protected main `9a1e2da5`.

Exact operator sequence:

1. Merge https://github.com/PatsKiller/tardeai/pull/506 (merge authority).
2. `git fetch origin && git checkout origin/main` in the canonical source tree.
3. `bash scripts/cio_phase2_exact_main_deploy.sh prepare && bash scripts/cio_phase2_exact_main_deploy.sh promote`.
4. Prove `SOURCE_COMMIT` equals the merge SHA.
5. Only then consider `CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY=1` (`docs/ops/OPERATOR_ACTION_REQUIRED.md`).

Do not deploy a feature branch as CURRENT. Do not invent cash policy.

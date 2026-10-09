# Portfolio child launcher execution roots

Status: SOURCE_ONLY patch with TEST_ONLY validation; not deployed.
Owner: platform / portfolio-maintenance owners.
as_of: 2026-10-09T01:35:00Z.
Base: current main 4673f135f001b59f01a2b8fd938738542200d5f8.

The CURRENT portfolio-maintenance controller derives `PROJ` from its installed location and invokes its own `linux_launchers` children. Six children reset `PROJECT_ROOT` to the development checkout. A top-level CURRENT WorkingDirectory therefore did not pin the actual Python code used by those lanes.

The patch derives each child's default from its installed `BASH_SOURCE[0]` location. Because measured immutable releases ship no `.venv`, activation reuses the deliberate shared interpreter convention in `run_continuous.sh`; a fixture/local venv remains preferred when present. Backup enforcer Python honors the configured shared interpreter while its script path stays release-local. Explicit weekly/monthly `PROJECT_ROOT` and lookthrough positional overrides remain supported. The direct daily, backup and price-cache launchers retain their existing non-overridable behavior. No scheduler expression, output writer, notification flag, model route, lock, timeout, backup retention or financial authority changes. Monthly launcher comments no longer falsely name retired Ollama or assume a provider; the existing governed host route still decides.

| Child | Caller / behavior preserved | Corrected default root |
|---|---|---|
| run_pg_backup.sh | portfolio backup cadence; existing dump directory, lock, retention and receipt | installed release |
| run_portfolio.sh | daily cadence; existing report/state and host notification paths | installed release |
| run_portfolio_weekly.sh | weekly cadence; explicit fixture override and nonzero report failure | installed release |
| run_portfolio_monthly.sh | monthly cadence; explicit fixture override and nonzero report failure | installed release |
| run_lookthrough.sh | lookthrough cadence; holdings guard and explicit positional override | installed release |
| run_price_cache.sh | direct legacy caller; existing writer behavior, not added to maintenance pipeline | installed release |

`tests/test_scheduler_launcher_roots.py` is already registered in the CIO gate runner. Tests copy the actual controller/child preludes into isolated versioned releases, execute them from a neutral cwd directly and through a CURRENT symlink, and stop before credential/env loading, backups, writes, model calls or sends. Twelve root checks fail on the prior code, with six preservation/existing tests passing (`27-launcher-negative-prior.log`). After the complete patch, 82 targeted launcher/cadence/projection tests pass (`27-launcher-regression-final.log`). Six additional shared-interpreter tests fail on the root-only patch because the release has no `.venv`, while 24 other checks pass (`27-runtime-negative-prior-verified.log`); all 30 launcher tests pass after the runtime selection fix. The earlier `27-runtime-negative-prior.log` records a harness-boundary adaptation and is not acceptance proof. Six `bash -n` checks and Ruff lint/format checks pass. This proves source root resolution, not natural production execution of these children.

Read-only release alias verification is needed before deployment; the release must retain its deliberate shared interpreter and persistent data/log/report mappings. Never manually run backup/report/price-cache to manufacture runtime acceptance. Natural cadence receipts and process/code-root observations remain required after exact-main deployment.

Rollback is a revert of the six default-root changes and comments, followed by canonical deployment of an approved immutable release. Do not modify host scheduler ownership as part of this source patch. Restoring a dev-tree default is a known defect, so prefer the previous approved release while diagnosing a new failure rather than patching a live release in place.

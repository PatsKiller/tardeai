# Phase 204C — Safe Reproduction (no secret leak)

Status:      HISTORICAL
as_of:       2026-06-05T12:08:22-04:00
Measured at: efcc51365 / not measured

- **Reproduces failure: YES** — `bash scripts/backup_secrets_state.sh` (no arg) → `usage: ... {env|data}`,
  exit 2. Deterministic.
- **Failure only in controller (no-arg): YES** — legacy passes `env`/`data` and succeeds.
- **Safe checks:** `gog --version` → v0.12.0 (OK). gog binary executable. No secrets printed; no upload
  to wrong folder; no credential change.
- **Suspected root cause: CONFIRMED** — missing required argument in the bundled controller's call,
  not a gog/Drive/auth problem.

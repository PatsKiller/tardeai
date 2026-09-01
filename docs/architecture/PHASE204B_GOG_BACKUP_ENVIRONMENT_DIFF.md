# Phase 204B — gog Backup: Controller vs Legacy Environment Diff

Status:      HISTORICAL
as_of:       2026-06-05T12:08:22-04:00
Measured at: efcc51365 / not measured

| Aspect | Legacy cron | Old bundled controller | Diff matters? |
|--------|-------------|------------------------|---------------|
| **Argument** | `env` and `data` (two calls) | **none** | **YES — root cause** |
| env load (.env) | sourced | sourced (same) | no |
| working dir | $PROJ | $PROJ | no |
| PATH / gog | ~/.local/bin/gog | same | no |
| user / shell | johnclaw / bash | same | no |
| Drive acct/folder | john@jwwhiting.com | same (script-internal) | no |

**Classification: CONTROLLER_CALL_ARG_MISMATCH (local).** Ruled OUT: GOG_AUTH_EXPIRED,
DRIVE_FOLDER_MISSING, LOCAL_FILE_MISSING, PATH_DIFFERENCE, PERMISSION_FAILURE, NETWORK_FAILURE — the
script exited at arg-parse before touching gog/Drive/network. The only difference that matters is the
missing `{env|data}` argument.

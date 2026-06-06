# Drive Sync — Hermes Runtime-Dump Excludes (2026-06-06)

**Status:** Complete. Sync-hygiene fix only. No trading behavior changed.

## Root cause

`scripts/sync-docs-to-drive.sh` mirrors most files under `$SRC/docs` to the curated
`Trade_AI_Docs_v2` Drive folder. The Hermes drain/runtime writes **non-documentation** JSON dumps
under `docs/hermes/**`, which were being uploaded to Drive each hourly run:

- `docs/hermes/phase3b_dryrun/hermes_auto_ticker_challenger_*_payload.json` — drain payload dumps (~300)
- `docs/hermes/backlog_health/latest_backlog_health_summary.json` — snapshot JSON
- `docs/hermes/observations/latest_observation_summary.json` — snapshot JSON

Because the `.sh` uploader does not de-dupe by name, repeated snapshot uploads accumulated multiple
stale copies of the same file on Drive.

These are runtime payload/snapshot dumps, not project docs. They should stay local (or in runtime
logs) and not pollute the curated Drive folder.

## Implementation

`scripts/sync-docs-to-drive.sh`:

- Added an `is_runtime_dump_excluded()` helper (single source of truth):
  ```sh
  docs/hermes/phase3b_dryrun/*                              # drain payload dumps
  docs/hermes/backlog_health/*.json                         # snapshot JSON (keeps .md reports)
  docs/hermes/*hermes_auto_ticker_challenger_*_payload.json # nested drain payloads
  docs/hermes/*_payload.json                                # any hermes payload json
  docs/hermes/*latest_*_summary.json                        # latest_* snapshot summaries
  ```
- **Candidate filtering:** the helper is applied in the upload loop *before hashing*; excluded files
  are logged `SKIPPED runtime dump: <relpath>` and never uploaded.
- **Cleanup/manifest handling:** the cleanup pass now removes a Drive file when the local source is
  gone **or** when it is now an excluded runtime dump (even if it still exists locally), logged
  `CLEANUP excluded runtime dump: <relpath>` → `DELETED from Drive`, and prunes the manifest.
- Curated Hermes markdown (architecture docs, `*_report.md`) is intentionally **not** matched.
- Delete-before-upload / manifest behavior and secret scanning are unchanged (not loosened).

`scripts/sync-docs-to-drive.py` (paused variant): added matching `EXCLUDE` regexes for parity, so it
cannot re-mirror these dumps if re-enabled.

## Validation

- `bash -n scripts/sync-docs-to-drive.sh` → OK; `py_compile` of the `.py` → OK.
- Helper unit test: excludes phase3b payloads + both `latest_*_summary.json`; **keeps**
  `backlog_health/*_report.md`, Hermes architecture `.md`, project docs, and the Playwright tarball.
- Dry candidate check: `OK: runtime dumps excluded`; **212 curated Hermes `.md` still present**.
- Real sync run (exit 0): `SKIPPED runtime dump` ×2, `CLEANUP excluded runtime dump` ×2,
  `cleanup done: 2 files removed from Drive`; curated docs still synced (`1 uploaded, 2349 unchanged`).
- Stale duplicates purged directly from Drive (not in manifest): backlog_health 5 + observations 5 = **10**.
- Drive re-verify: `phase3b_dryrun json=0`, `backlog_health json=0 md=7`, `observations json=0 md=7`.

**Deleted from Drive this task:** 12 snapshot JSONs (2 via manifest cleanup + 10 stale duplicates).
(The ~296 `phase3b_dryrun` payloads were excluded + purged in the prior commit `b8ddb36`.)

## Safety proof

`ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true`, no `LIVE_TRADING`. No broker/order/stop/
proposal/GO-WAIT/strategy mutation. No live enablement. No Phase 205 work. Hermes drain logic
untouched. No local runtime payloads deleted. No curated docs deleted. Only Drive-sync
include/exclude behavior changed.

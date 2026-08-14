# PHASE 1 CLOSEOUT — Exact Release Convergence

**UTC:** 2026-08-14  
**Authority:** `READ_ONLY_ADVISORY` unchanged  
**Status:** **production** (not release_candidate)

## Goal

Make **Git main = deployed backend = release manifest = Drive pin** on one full SHA.

## Executed

| Step | Result |
| --- | --- |
| Source | `origin/main` @ `e7b722b3b0a84baa41dfb202765d7c744faf128e` |
| Checkout | `/home/johnclaw/tradeai-wt-investment-office-convergence` hard-reset to main |
| Immutable release | `…/e7b722b3-main-exact-phase1-20260814-094715` |
| Stamp | `BUILD_SHA`, `GIT_SHA`, `BUILD_BRANCH`, `BUILD_COMMIT_TIMESTAMP`, `BUILD_STAMPED_AT`, `BUILD_MIGRATION_HEAD`, `BUILD_CONFIG_HASH`, `BUILD_FRONTEND_SHA`, `BUILD_STAMP.json` |
| Pipeline data | symlinked to canonical `trade-ai-v12-rebuild` (state/cio/runtime/health) |
| Promote | health ok, `/v3/cio` 200, `/api/v2/cio/capital-plan` 200 |
| Rollback proof | CURRENT → previous canary `ac997871…` → health ok |
| Re-promote | CURRENT → exact main release → health ok |
| Manifest | status **`production`**, pins full SHA |
| Drive | `RELEASE_MANIFEST.md` + `.json` replaced in `investment-office` folder |

## SHA truth (post-promote)

| Layer | Value | Match |
| --- | --- | --- |
| origin/main | `e7b722b3…` | — |
| LIVE BUILD_SHA | `e7b722b3…` | **YES** |
| Manifest canonical | `e7b722b3…` | **YES** |
| Manifest backend | `e7b722b3…` | **YES** |
| Manifest status | `production` | **YES** |
| Manifest hash | `0c2971fdf72547adc715a453c5b10b8d1a3310e33daff58839bb52b48f13c70f` | |
| Rollback SHA | `ac997871…` (prior canary) | preserved |
| Deploy path | `…/e7b722b3-main-exact-phase1-20260814-094715` | |

## Frontend stamp

`apps/command-center-v3/build-meta.json` stamped with `git_sha=e7b722b3…` for this release pack.  
Dist was present (copied if missing from prior release so `/v3` keeps serving).

## Generator change

`scripts/cio_release_manifest.py`:

- status **`production`** when HEAD == origin/main and live backend SHA matches HEAD, or `CIO_RELEASE_STATUS=production`
- optional `CIO_ROLLBACK_SHA` for rollback pin

## Rollback

```bash
# previous canary still on disk
ln -sfn /home/johnclaw/trade-ai-releases/portfolio-server/ac997871-cio-rc-phase13-20260814-083443 \
  /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
# restore systemd WorkingDirectory to that path, daemon-reload, restart
# or:
bash scripts/cio_phase13_canary_deploy.sh rollback \
  /home/johnclaw/trade-ai-releases/portfolio-server/ac997871-cio-rc-phase13-20260814-083443
```

Pre-canary baseline also remains: `20260813-210818`.

## Exit gate

| Gate | Status |
| --- | --- |
| LIVE_BACKEND_SHA == ORIGIN_MAIN_SHA | **PASS** |
| Manifest == live | **PASS** |
| Drive updated to production pin | **PASS** (upload replace) |
| No “release_candidate” on production pin | **PASS** |
| Rollback proven | **PASS** |
| Re-promote | **PASS** |
| Broker / Telegram mutations this phase | **none** (no new send) |

## Residual (not Phase 1)

Health still **degraded** (stale cio_decisions / indicators) — Phase 2–3 financial/freshness work.  
Overlay canary is no longer CURRENT; exact main tree is.

## Safety

## REAL TELEGRAM SENDS: 0 (this phase)  
## BROKER CALLS: 0  
## FINANCIAL AUTHORITY CHANGED: NO  

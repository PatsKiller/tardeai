# PHASE 10 CLOSEOUT — Git / Release Manifest / CI / Drive Truth

**UTC:** 2026-08-14  
**Branch:** `wt/cio-phase1-notify`  
**Content SHA:** `18587528` (pin tip may be pin-only `RELEASE_MANIFEST` follow-up)  
**Authority:** `READ_ONLY_ADVISORY` unchanged  

## Goal

Make investment-office release truth **machine-checkable**: one generator for
`RELEASE_MANIFEST`, validation that fails on stale pins, CIO hardening CI gates,
and an explicit Drive parity observation. No broker / Telegram / deploy mutations.

## Deliverables

| Artifact | Role |
| --- | --- |
| `scripts/cio_release_manifest.py` | `generate` / `validate` / `check` / `print-json` |
| `docs/investment-office/RELEASE_MANIFEST.md` | Human pin table (do not hand-edit) |
| `docs/investment-office/RELEASE_MANIFEST.json` | Machine twin for CI |
| `scripts/run_cio_hardening_ci.py` | Local + CI ordered unit gates |
| `.github/workflows/cio-production-hardening-ci.yml` | GitHub Actions path-filtered workflow |
| `tests/test_cio_release_manifest.py` | Generate/validate + stale-fail unit tests |

## Required pin fields

`canonical_source_sha` · `frontend_build_sha` · `backend_release_sha` ·
`deployed_release_path` · `migration_head` · `docs_pin` · `runtime_config_hash` ·
`report_version` · `rollback_sha` · `created_at`

Forbidden as **current** pins (Phase 0 preliminary): `0a9b6c41…`, `d9b63ed6…`.

## CLI

```bash
python scripts/cio_release_manifest.py generate --write
python scripts/cio_release_manifest.py check          # exit 1 on fail
python scripts/run_cio_hardening_ci.py                # full local gate suite
```

`check` compares disk MD+JSON to live HEAD and product versions. CI does **not**
auto-regenerate — a stale committed manifest fails the gate.

## Hermes score weights ownership

| Classification | Path |
| --- | --- |
| `runtime_state_with_release_seed` | `config/hermes_score_weights.yaml` |

Seed defaults may be version-controlled; `auto_grafted_at` / live weight mutations
are runtime state and may dirty the worktree. Do not treat runtime grafts as
undeclared source drift without an ownership note.

## Branch protection (operator action — not auto-applied)

Observed: `main` unprotected (Phase 0).

Recommended (requires operator repo-governance approval):

- require pull request before merge
- require CIO hardening CI + release-readiness checks
- block force-push to main
- block merge with failing required checks

This script does **not** enforce GitHub branch protection.

## Deploy truth (host observation)

| Field | Observed |
| --- | --- |
| CURRENT symlink | `/home/johnclaw/trade-ai-releases/portfolio-server/20260813-210818` |
| BUILD_SHA / GIT_SHA files | **missing** in release dir |
| backend_release_sha pin | `UNKNOWN_NOT_STAMPED_IN_RELEASE_DIR` |
| RC vs deploy | deploy lags RC HEAD until controlled Phase 12–13 deploy |

Date-stamped release directory names are **not** treated as git SHAs.

## Drive reverify (2026-08-14)

| Item | Result |
| --- | --- |
| Drive folder | `investment-office` (`1sVHlO8v-NStl2HRbk1bJqwqI67bxGUM8`) under Trade_AI_Docs |
| Drive `RELEASE_MANIFEST.md` | **STALE Phase 0 preliminary** — pins `0a9b6c41…` / `d9b63ed6…` |
| Local manifest | Regenerated RC pin (this branch HEAD + product versions) |
| Drive parity | **FAIL** vs local — Drive still has forbidden preliminary SHAs |
| Drive missing closeouts | Phase 1–3, 4 report-arch, 5 visuals, 6 analytics, 7 pipeline, 8 consistency, 9 telegram product, this Phase 10 closeout |
| Sync action | **Operator-only** — re-run `scripts/sync-docs-to-drive.sh` from the canonical tree after merge/commit; not auto-pushed by this phase |

Drive is a read-only mirror of MS-01 docs. Canonical truth is **git** + local
`RELEASE_MANIFEST.{md,json}`. Until operator sync, treat Drive investment-office
pins as **not release-authoritative**.

## CI gates (ordered)

1. notification_no_network (Phase 1 + 9 Telegram)
2. capital_ledger
3. decision_semantics (+ office consistency)
4. sector_taxonomy
5. report_model_and_parity (v2 / architecture / analytics / charts / pipeline)
6. command_center
7. release_manifest unit tests
8. `cio_release_manifest.py check` (committed pins == HEAD)

HTML export smoke is in the GitHub workflow; DOCX/PDF smokes are optional
(`continue-on-error`).

## Exit gate

| Gate | Status |
| --- | --- |
| MANIFEST_GENERATOR | **PASS** |
| STALE_PRELIMINARY_SHA_FORBIDDEN | **PASS** (unit + validate) |
| COMMITTED_MANIFEST_MATCHES_HEAD | **PASS** after pin regenerate on this commit |
| CIO_HARDENING_CI_LOCAL | **PASS** (all gates) |
| BRANCH_PROTECTION_ENFORCED | **NO** — operator action required |
| DRIVE_PARITY | **FAIL documented** — Drive still Phase 0; sync operator-gated |
| DEPLOY_STAMPED_WITH_GIT_SHA | **NO** — release dir lacks BUILD_SHA (gap for Phase 12–13) |
| BROKER / TELEGRAM MUTATIONS | **0** |

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## SECRETS PRINTED: 0  
## FINANCIAL AUTHORITY CHANGED: NO  
## BRANCH PROTECTION AUTO-CHANGED: NO  
## DRIVE AUTO-WRITTEN: NO  

## Related (not this phase)

`PHASE10_OUTCOME_LEARNING.md` is the **earlier investment-office convergence**
Phase 10 (disposition → calibration). This closeout is **CIO production-hardening**
Phase 10 (git / release / CI / Drive truth). Names collide; scopes do not.

## Next phase allowed

Phase 11 — adversarial suite / safety scan (no live canary without explicit env approval).

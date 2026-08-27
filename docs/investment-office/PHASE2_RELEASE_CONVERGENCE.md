# PHASE 2 CLOSEOUT — Exact-main deploy + manifest/Drive convergence

**UTC:** 2026-08-14  
**Authority:** `READ_ONLY_ADVISORY`

## CI split (no more regenerate-before-validate)

| Command | Role |
| --- | --- |
| `cio_release_manifest.py check-committed` | Read-only integrity of **committed** files |
| `cio_release_manifest.py candidate` | Isolated generated copy + informational diff |
| `cio_release_manifest.py check` | Full HEAD pin (production). CI does **not** write over git files. |

PR **#308** (`2bbd8848`).

## Exact-main deploy

| Layer | Value |
| --- | --- |
| origin/main | `af5eddab1fdfb5d93201ac8ae270e130ea6b6532` |
| live BUILD_SHA | `af5eddab1fdfb5d93201ac8ae270e130ea6b6532` |
| report `source_sha` | `af5eddab…` |
| frontend `build-meta.git_sha` | `af5eddab…` (rebuilt from this source line) |
| CURRENT | `af5eddab-main-exact-phase2-pin-20260814-152423` |
| Content SHA named by pin | `2bbd8848b1f7f32bff6eae8b9d1fcf93d640852e` |
| rollback | `fff9253a…` and `2bbd8848-main-exact-phase2-20260814-152053` |
| Telegram | `CIO_TELEGRAM_INTERDICT=1` |

`git diff 2bbd8848..af5eddab` is **only** `RELEASE_MANIFEST.md` + `.json` (pin-only parent).

Production pin: PR **#309**.

## Drive

Folder `1sVHlO8v-NStl2HRbk1bJqwqI67bxGUM8`:

- Canonical current: `RELEASE_MANIFEST.md` / `.json` (replaced in place; same file IDs)
- Git JSON sha256 == Drive JSON sha256 `8fdf912fdcc755222011ab8a0b7fc2680f10bd8c2b0d301f4d453ea017dd4145`
- Older copies renamed: `RELEASE_MANIFEST.history.20260814-135321.md` / `.json`

## Rollback

```bash
bash scripts/cio_phase2_exact_main_deploy.sh rollback \
  /home/johnclaw/trade-ai-releases/portfolio-server/2bbd8848-main-exact-phase2-20260814-152053
```

## Not claimed

Phase 2 does **not** claim production acceptance. Financial book, PDF, Advisory UI, Almanac remain open (Phase 3+).

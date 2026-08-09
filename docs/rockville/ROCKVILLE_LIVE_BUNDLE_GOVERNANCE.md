# ROCKVILLE_LIVE_BUNDLE_GOVERNANCE

## Approved-style build (design-guard PASS)

- Source: `feat/rockville-watch-cio-v1` (working tree post-correction)
- Command: `cd apps/command-center-v3 && npm run build`
  (runs design-token guard + chip-scope tests + tsc + vite)
- Dist: `apps/command-center-v3/dist`
- Asset after correction: `index-D5NoIzaG.js`
- UI version: see `dist/build-meta.json`

## Owner-override build (NOT approved)

- Prior asset: `index-BskIX8If.js`
- SHA256: `200ad09caf373c6c53f7dbadc3c97931b7ce55d2d6f4fada9e1f5c82eb90024a`
- Recorded: `data/runtime/rockville/dist_backups/MANIFEST.txt`
- Used only for diagnosis; replaced by design-guard-passing build.

## Rollback

1. Restore release dist from
   `/home/johnclaw/trade-ai-releases/portfolio-server/cdab641c-main-20260803-223104/apps/command-center-v3/dist`
   into `$PROJ/apps/command-center-v3/dist`, **or** rebuild from `main`.
2. Restart portfolio-server.
3. Hard-refresh `/v3/watch`.
4. Paid flags remain false in `config/rockville/ROCKVILLE_WATCH_CIO_MODEL_POLICY.json`.

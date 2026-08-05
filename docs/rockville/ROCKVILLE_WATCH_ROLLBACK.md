# ROCKVILLE_WATCH_ROLLBACK

## Instant UI rollback

1. Ensure flags in `config/rockville/ROCKVILLE_WATCH_CIO_MODEL_POLICY.json` (or override `data/runtime/rockville/feature_flags.json`):
   - `watch_card_v2_visible: false`
   - `watch_card_v2_shadow: false` (optional hide)
   - `watch_deepseek_flash_enabled: false`
   - `watch_cio_daily_enabled: false`
   - `watch_cio_deep_review_enabled: false`
2. Hard-refresh `/v3/watch` — prior WatchlistHub / WatchlistCardV4 remains the default path.
3. `/api/v2/*` consumers are untouched.

## Code rollback

```bash
git revert <rockville-merge-sha>
# or
git checkout main -- apps/command-center-v3/src/pages/WatchHub.tsx \
  scripts/operator_presentation.py scripts/api_v2.py
```

Remove routes `/api/v3/watch/*` if full API rollback required.

## Data

CIO artifacts under `data/runtime/rockville/` are advisory mirrors. Safe to archive:

```bash
mv data/runtime/rockville data/runtime/rockville.bak.$(date +%Y%m%d)
```

## Verification after rollback

- `/v3/watch` loads prior card  
- No CIO panel if flags off  
- FTH may still show DETERMINISTIC FAIL header if operator_presentation fix retained (recommended keep)  

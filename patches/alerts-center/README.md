# Alerts Center + false-ticker containment (2026-09-29)

**Base:** `6243c7ee7db4` (#1355)
**Mode:** Diagnose + implement — not promoted to ms01 CURRENT

## Apply

```bash
# on tardeai worktree at/after 6243c7e
git apply docs/alerts-not-showing-and-alerts-center-20260929.patch
# or copy files from this tree over the repo root
cp -a patches/alerts-center/. .
```

## Verify

```bash
cd apps/command-center-v3 && node --experimental-strip-types src/lib/alertsCenter.test.ts
python3 -m pytest tests/test_alert_chrome_stopwords_20260929.py -q
```

## Contained

1. `_STOP` chrome: ENTRY, ALERT, SETUP, TARGET, LIMIT, ADVISORY, INVALIDATION
2. Entry planner Telegram scoped via `set_primary_symbols([sym])`
3. CC v3 header ⚑ ALERTS → Alerts Center modal (Entry / Telegram / Setups)
4. Scalp deep links keep `symbol`; chrome never opens `/watch/intelligence/ALERT`

## Not done here

Push to PatsKiller/tardeai, CURRENT promote, live Telegram re-fire, mail.

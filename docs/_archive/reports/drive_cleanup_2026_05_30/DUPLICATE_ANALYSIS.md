# Duplicate Analysis — 2026-05-30

## Summary

| Category | Count |
|----------|-------|
| Total duplicate name groups | 1207 |
| Total files with duplicate names | 3758 |
| Caused by duplicate `docs/` folder | ~majority (estimated) |
| Root file vs synced doc | 77 |
| Duplicate TGZ archives | 3 |
| Same-parent duplicates (true duplicates) | 574 |
| Other | 1121 |

## Root Cause

The **primary source** of duplicate file names is the **two `docs/` folders** under the canonical root. Both contain overlapping subfolders (`archive`, `design`, `diagrams`, `llm_fleet`, `maturity_hardening`, `phase_b1_baseline`, `sync_drift_2026-05-16`), each with their own copies of the same files.

**Fixing this one issue eliminates the majority of the 1,207 duplicate groups.**

## Stale `docs/` Folder (331 files)

| Field | Value |
|-------|-------|
| Folder ID | `1VGZYWRIcw6iLomXOnv3S7hkHT3Xbg-uK` |
| Files | 331 |
| Subfolders | 57 |
| All 7 subfolders overlap with canonical | Yes |
| Recommendation | Move all contents to `40_ARCHIVE/duplicate_docs_folder/` |
| Risk | LOW — all content exists in canonical docs folder |

## Same-Parent Duplicates (574 groups)

These are files with the same name in the same folder — true duplicates:

### `00_README.md`
- ID: `17YimGbpuJS-4f9Q59ff9mmSIvDRySDwkhwmuo8_cBl4` | Modified: 2026-05-23T01:25:54.585Z | Size: 2219
- ID: `1GXzGzWTjrc2-GrkzveClBMAJhKMiOneF8UyEbTxNXck` | Modified: 2026-05-23T01:19:16.989Z | Size: 2238
- ID: `14zA5h6z6DelyhBuDDBGeQLKI3nbXrPy7bJg0dGJXx4A` | Modified: 2026-05-22T23:32:32.433Z | Size: 2461
- ID: `1Qy49kKiYqkVRzr0_-nF6cy8JwFwLcLAgpFO7n9EAILs` | Modified: 2026-05-22T23:27:08.728Z | Size: 2461
- ID: `1lWgxC5qw9hfhDrY1jTCMi8TYCUBtxV_zLtLlBelvBhI` | Modified: 2026-05-22T23:09:13.364Z | Size: 2460
- ID: `15sRU5_tl2nJfRvoTaCFCNBsfwjWMyJs9Gl7e8MyAIC8` | Modified: 2026-05-22T22:59:50.060Z | Size: 2480
- ID: `1vTHSAcRU1VHheHOa4u3RoKUSbBEhH8-6Dnu0zbdckUA` | Modified: 2026-05-22T22:51:54.752Z | Size: 2459
- ID: `1eE3SOTOCgwfeXAOsdMl-iLNz4jcbSv74bxQ7gQQm5I0` | Modified: 2026-05-22T21:25:37.397Z | Size: 2650
- ID: `1eNhEviyaXKFGLZ9mfhS5zXOjW5uhasFlfy9hCANjgi8` | Modified: 2026-05-22T21:21:18.041Z | Size: 2648
- ID: `1Fc5T5gEgp9ZpSr0R-8sVJW9NJEQhlMkKoo_FYbs01Dk` | Modified: 2026-05-21T03:09:41.974Z | Size: 2449
- ID: `1Hl51ryGKyUpnqh_Ie0T7YsLHMKe2U25e` | Modified: 2026-05-18T17:26:29.156Z | Size: 1253
- ID: `1PlgdBeKQsdF0vITA8FNQskH9IwNqGBBgzhLMr7CQfKA` | Modified: 2026-05-21T02:42:09.163Z | Size: 2579
- ID: `1tSTyl7oU50A9F-1-XUDOwZW2JQ687wa3` | Modified: 2026-05-18T02:47:59.495Z | Size: 884
- ID: `1CbJgnYsQk3eoidIr1w6Y_CDJl-mO7ULLhpcOCABA734` | Modified: 2026-05-21T02:42:02.391Z | Size: 2786
- ID: `19CxfCxfH9nhunWrHXcvuFmRxQJDisQhm` | Modified: 2026-05-18T02:47:53.095Z | Size: 1160
- ID: `1-i6DnvlOd6EnHH9vaX6pDxZPB_YAJvQp` | Modified: 2026-05-18T01:06:01.699Z | Size: 889
- ID: `1L_OiSTTEcmqoBZEO5OECMWaHJ4OXYB9m` | Modified: 2026-05-17T23:59:17.800Z | Size: 889
- ID: `1UjUj6DurBTjm_A51Tf3gAnOtvQ9ODUDIb-bWVu63bqU` | Modified: 2026-05-21T02:29:31.960Z | Size: 7088
- ID: `1rVZx7VrQbpy6ErBAD-PMStQXzeDyAvHi` | Modified: 2026-05-17T23:12:04.198Z | Size: 7149
- ID: `1klfbkY4Znh8xINZblsM5aosexdM3Dsz-zgeJgsOEkJc` | Modified: 2026-05-22T21:42:28.418Z | Size: 1045
- ID: `1Dj8RkZ0SyWIAHFzMoj1H6lySJ6-Z5561FBmG4f42fOY` | Modified: 2026-05-22T21:31:42.163Z | Size: 1044
- ID: `1W_FmIRIW5BjJwCeHCM-fxJ12or3HR1q_` | Modified: 2026-05-17T23:13:47.071Z | Size: 1354
- ID: `1oXSjwPL0Pe-8LuMK487kRWX6HIhEmDIQ` | Modified: 2026-05-17T22:54:59.454Z | Size: 1354
- ID: `1ypuGMyMbTg0pBn0_BCDFXhkGgm-rqXuC` | Modified: 2026-05-17T22:41:23.943Z | Size: 1339
- ID: `1eQaI9wqxK-9YFvFbsUlYF-LDhMwyVpx7` | Modified: 2026-05-17T22:36:58.020Z | Size: 1339
- **Recommendation**: Keep newest, archive older

### `A1A.md`
- ID: `1xS8P9NFFDhPQmSP_SwFePtGdH6a1Ek4-JNaxpOG_lW8` | Modified: 2026-05-21T02:41:56.905Z | Size: 5066
- ID: `1DaZhDn0p2hsmp_eUI6ld82YrP9we520h` | Modified: 2026-05-17T23:16:56.831Z | Size: 4105
- **Recommendation**: Keep newest, archive older

### `AGENT_COLLABORATION_DESIGN_NOTES.md`
- ID: `1K12opiM1ZpFvPhJ2pPK6v1Y89xJRN0nE` | Modified: 2026-05-25T22:50:25.062Z | Size: 6315
- ID: `1VMkVq78Oko924XnTSuraGD81SnHgWPeb` | Modified: 2026-05-25T22:33:03.775Z | Size: 5031
- **Recommendation**: Keep newest, archive older

### `AGENT_INTELLIGENCE_PIPELINES.md`
- ID: `10g2MUccMpR8kfDzda4iuILdiDh2XSnhWCUwcftK2SDQ` | Modified: 2026-05-21T02:47:43.093Z | Size: 4243
- ID: `12V5YjVROuQ4SQt23MuFNrw4Cp6yKl4ff` | Modified: 2026-05-18T00:01:09.373Z | Size: 2779
- **Recommendation**: Keep newest, archive older

### `AGENT_MONITORING_AUDIT.md`
- ID: `19tjQO-YtpZTN-G2ft-Xx7gqe_HBYu22W` | Modified: 2026-05-26T15:26:51.009Z | Size: 19850
- ID: `1gOSmKIrXcIsui1Pt-BYhkT2DGVetFh1J` | Modified: 2026-05-26T15:23:05.473Z | Size: 19850
- **Recommendation**: Keep newest, archive older

### `AGENT_NEXT_STEPS_RUNBOOK.md`
- ID: `1vT61l8OTrWKneBItct52bf9RCwqqP0n9KSw160YUEdU` | Modified: 2026-05-21T02:49:04.965Z | Size: 2752
- ID: `1QGWpo_-2bVZmzWJNUthzGj1vxHSiXJgX` | Modified: 2026-05-18T00:02:53.298Z | Size: 1195
- **Recommendation**: Keep newest, archive older

### `AGENT_ROUTER_IMPLEMENTATION.md`
- ID: `1C1cMKNrzrzC6jx-KapxEWsUg-I-e9PqIr2heEwhzm6w` | Modified: 2026-05-21T03:01:49.985Z | Size: 8539
- ID: `1LCS-YI84TD4OQyXG--7ksHQSZ5Ub2hgb` | Modified: 2026-05-18T00:09:24.171Z | Size: 6335
- **Recommendation**: Keep newest, archive older

### `ALERT_INTELLIGENCE_PIPELINE.md`
- ID: `1OGCjQPQS4JVc-AQbLC62chN7iUIoLUe1JJ6pZZgNMaQ` | Modified: 2026-05-21T02:49:08.626Z | Size: 7280
- ID: `1qRiZfmIpqcvNDxTG3uK4Kx6J5pyASXq7` | Modified: 2026-05-18T00:02:54.876Z | Size: 5612
- **Recommendation**: Keep newest, archive older

### `APPENDIX_E_SCRIPT_ROUTING_MATRIX.md`
- ID: `1h-HPNtunESEqRirZg71EBLgR9_uq1U2leIq3MeR4_IU` | Modified: 2026-05-21T02:32:22.885Z | Size: 5051
- ID: `1bsOyQxfNDBQzFJiDna6e4JhwOpTCO1bU` | Modified: 2026-05-17T23:13:56.431Z | Size: 5015
- **Recommendation**: Keep newest, archive older

### `ARCHITECTURE_INFOGRAM.md`
- ID: `1NxZBSO1KXkp-YaZPhGUi1Km3O8_Cig3HAnCpnIO2Q3I` | Modified: 2026-05-21T03:04:10.214Z | Size: 19605
- ID: `14-AkY3tzLMVn2Dp6GWWiYMKSqx6AqIiK` | Modified: 2026-05-17T23:19:34.486Z | Size: 14955
- **Recommendation**: Keep newest, archive older

### `ARCHITECTURE_OVERVIEW.md`
- ID: `1SrfL5cmkK4OAv1A6ml9KkDcbCkbjYJiBUDEdz9HWy7Y` | Modified: 2026-05-28T17:19:21.408Z | Size: 18089
- ID: `1wsawP-v3PMZE5T4RYvW8M8vFT5ozT9e8C1u9VLZNyRg` | Modified: 2026-05-21T15:18:37.272Z | Size: 17167
- ID: `1i55SODjOoGZ4zcuLWzPQaZlZU6NSHQla5-msrS4CzUM` | Modified: 2026-05-21T02:39:08.387Z | Size: 15408
- ID: `1DDz0z83NBylRmktThZEhY4laFxtTB2Zb` | Modified: 2026-05-18T12:54:29.186Z | Size: 13067
- ID: `1_aHOXdXx1SyfaRiMHBbaVK8ebMLOvAXH` | Modified: 2026-05-17T23:16:53.166Z | Size: 10813
- **Recommendation**: Keep newest, archive older

### `ARCHIVE_MANIFEST.md`
- ID: `1zlQsKGgvPbhOF-ubSPzYZYOR1hdA-EotWz2IBsJjtFU` | Modified: 2026-05-21T03:03:34.535Z | Size: 1778
- ID: `1zdPottwLz2oiyRN6fQEi2kp7pVvKS36y` | Modified: 2026-05-17T23:18:13.944Z | Size: 1061
- **Recommendation**: Keep newest, archive older

### `ATM_APPROVE_FAILED_2026-05-22.md`
- ID: `1GVhBk0MRKP_kXcI0kkVLwzWDZr1WWpPL413I2irWXxE` | Modified: 2026-05-22T17:12:49.175Z | Size: 9323
- ID: `1m8MwvOiOU3xIDnekE6iw2pea7hrWjpng2-w5w53CS1s` | Modified: 2026-05-22T17:00:01.515Z | Size: 8814
- ID: `1w0i20jUvKWcDrMSvpIkWQrP4r8QPA1Th5vwZEhMk9ts` | Modified: 2026-05-22T16:50:11.879Z | Size: 8764
- **Recommendation**: Keep newest, archive older

### `ATM_SYSTEM_AUDIT.md`
- ID: `1GRA3xlL7dw8531hJYoKqQ17FyaEb2WtJ` | Modified: 2026-05-26T15:26:52.462Z | Size: 19414
- ID: `1A8jYjR357fBmI3eUyT-9M6O5ijt80LKl` | Modified: 2026-05-26T15:22:11.952Z | Size: 19414
- **Recommendation**: Keep newest, archive older

### `ATM_V1_DAY1_DASHBOARD_2026-05-22.md`
- ID: `1bBOEXmW9XBxm92RdP3i1W0vFuQrCSMO69qz7X24GNlU` | Modified: 2026-05-22T14:19:06.279Z | Size: 6262
- ID: `1w0___R5n5OhFFyG4SZh3o1qEmfwIrQixSbZr5J2vk38` | Modified: 2026-05-22T14:08:12.192Z | Size: 6007
- **Recommendation**: Keep newest, archive older

### `AUDIT_FINDINGS.md`
- ID: `13iU_GfjETdnVvevyrVNz78zOStbER3XI1GwUgwwEp2Q` | Modified: 2026-05-21T02:27:30.092Z | Size: 6942
- ID: `1axeE3HFrcQHrL46sowht_YaHEtdUguk1` | Modified: 2026-05-17T23:10:21.915Z | Size: 6220
- **Recommendation**: Keep newest, archive older

### `AUDIT_REPORT.md`
- ID: `1jeJ2CqbFAd8_O__jPUG4pLprPsNk_poP_xhxdCyNUf0` | Modified: 2026-05-21T03:05:36.914Z | Size: 4031
- ID: `1hUgHOGC3d7VvaPQkRhJhPOiJF1-qD2mY` | Modified: 2026-05-17T23:20:23.684Z | Size: 3099
- **Recommendation**: Keep newest, archive older

### `AUDIT_RESULT.md`
- ID: `1U2GA5zwLoHB_o-eF0pNBpN0O1prmrFUnT5KZgUzDQfw` | Modified: 2026-05-21T03:05:40.274Z | Size: 2939
- ID: `1BUScr3NYatULwICHV89AFd9k67W-_6_g` | Modified: 2026-05-17T23:20:30.271Z | Size: 1657
- **Recommendation**: Keep newest, archive older

### `AgentCollaboration.tsx.REPLACEMENT.md`
- ID: `1uIMdwZyp_pUQqEQsg6hWboqQ4OEm2k1R` | Modified: 2026-05-25T22:50:20.301Z | Size: 56501
- ID: `1kGqVThQPjbbnNKcJueQnt6VHPVGVTiBm` | Modified: 2026-05-25T22:33:02.453Z | Size: 33564
- ID: `1j8nrVTXiUwLAXKODYIsGceqVlDXCwnqv` | Modified: 2026-05-25T16:49:16.988Z | Size: 17544
- ID: `1jo2YChk7QkNnDlj-eeLDrGlc90qNeumE` | Modified: 2026-05-25T15:44:40.494Z | Size: 429
- **Recommendation**: Keep newest, archive older

### `BOT_MATURITY_ROADMAP_v1.md`
- ID: `1WiWzY0wXVdowJDIib2V_iJej6yoY9XjumNfYoo1TELI` | Modified: 2026-05-21T03:17:55.017Z | Size: 14218
- ID: `1qiUnoKuy2hHdHjJVwA0tOKXO9SpHcOR6` | Modified: 2026-05-17T23:22:41.133Z | Size: 19741
- **Recommendation**: Keep newest, archive older


... +554 more groups (see `duplicate_candidates.csv`)

## Duplicate TGZ Archives

| File | Copies | Recommendation |
|------|--------|----------------|
| `playwright_journal_backtest_20260529_1506.tgz` | 2 | Keep the one linked in docs (ID: `1DY_kup-0QgZyHSfE74ibvLhrJCLYkLqa`), archive other |
| `playwright_journal_backtest_20260529_1421.tgz` | 1 | Archive — superseded by 1506 |
| `ui_redesign_trade_ai_command_center_full_20260525.tgz` | 3 (root + 2 nested) | Keep 1, archive 2 |
| `atm_audit_2026_05_26_FULL_HANDOFF_20260526_1135.tgz` | 2 | Keep 1, archive 1 |
| `audit_7777_20260524_1923.tgz` | 2 | Keep nested, archive root |
| `audit_7776_20260524_1225.tgz` | 2 | Keep nested, archive root |

## Full Data

- `logs/drive_cleanup_2026_05_30/duplicate_candidates.csv`

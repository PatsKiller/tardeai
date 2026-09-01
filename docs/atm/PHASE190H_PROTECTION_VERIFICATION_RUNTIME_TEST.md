# PHASE 190H — Protection Verification Runtime Test

Status:      HISTORICAL
as_of:       2026-06-02T10:33:34-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~10:20 ET · Alpaca **paper** only · Live endpoint blocked

---

## Verification results

| Check | Result |
|---|---|
| ANY broker stop still exists | ✅ YES (@3.07, id 8bfdde82, status=new) |
| ANY stop_order_id persisted in DB | ✅ YES (PROTECTED_TRACKED, src=alpaca_paper_order_book) |
| SNOW broker stop still exists | ✅ YES (@254.38, id 8737e56d) |
| SNOW stop_order_id persisted in DB | ✅ YES |
| TMHC broker stop still exists | ✅ YES (@68.02, id f7347a29) |
| TMHC stop_order_id persisted in DB | ✅ YES |
| **Untracked broker stops 3 → 0** | ✅ **0 remaining** |
| New stop orders placed | ✅ NONE (book = 6 stops, all original ids, status=new) |
| Stops modified/cancelled | ✅ NONE (no non-stop orders present) |
| Live endpoint touched | ✅ NO (paper-api only; hard guard in verifier) |
| SIEM event for the defect | ✅ event id 162 (`data_integrity`/`LARGE_GAIN_NO_TAKE_PROFIT`/ANY/urgent) |
| Telegram digest send logged | ✅ YES — message_id 11226 (chat 6993102664), 11227 (chat 8797974247), HTTP 200 |
| Hermes protection findings | 0 (correct — all tracked; gains below $250 TP threshold at check time) |

## Before / after
| Metric | Before (Phase 189) | After (Phase 190) |
|---|---|---|
| Untracked broker stops | 3 (ANY, SNOW, TMHC) | **0** |
| Positions with `protection_status` | 0 | 6 |
| SIEM protection events | 0 (log-swallowed) | emitted + deduped |
| Hermes protection visibility | none | safe view + 6 rules |
| Dashboard protection panel | none | endpoint live (UI next deploy) |

## Notes
- Live P&L fluctuated during the test window (ANY +$535 → +$231; SNOW +$251 → +$181) as syncs
  refreshed marks — the `LARGE_GAIN_NO_TAKE_PROFIT` rule (≥ $250) fires/clears accordingly, which
  is correct, threshold-driven behavior.
- The persisted `stop_order_id` values **survived a 10:00 ET position sync** — durability confirmed.
- **No new stops placed, none modified, no live endpoint touched** — fully within phase guardrails.

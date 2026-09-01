# PHASE 191A — Protection UI Visibility Verification

Status:      HISTORICAL
as_of:       2026-06-02T11:12:46-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~11:00 ET · Alpaca **paper** only · Live endpoint blocked

---

## Server
- Service: `tradeai-portfolio-server.service` (system systemd, enabled). **Auto-restarted
  2026-06-02 10:15:47 ET** — which loaded the Phase 190 endpoint.
- A manual restart requires `sudo` (password) — not available non-interactively. The Phase 190
  endpoint is **already live** from the 10:15 restart, so no forced restart was needed.

## Verification
| Check | Result |
|---|---|
| ATM protection endpoint live | ✅ `GET /api/v2/atm/protection-coverage` returns `{ok:true,...}` (6 positions, 0 untracked) |
| Hermes protection view accessible | ✅ `hermes_v_open_position_protection_context` queries cleanly (6 rows) |
| `protection_status` visible for all open positions | ✅ all 6 = PROTECTED_TRACKED |
| `stop_order_id` visible for ANY/SNOW/TMHC | ✅ persisted (8bfdde82 / 8737e56d / f7347a29) |
| Live endpoint touched | ✅ NO — paper endpoint only |

## New in Phase 191 (live on next restart)
- `GET /api/v2/atm/profit-protection-advisory` — added to `ROUTES`; serves the inline advisory
  panel. It is **live on the next `tradeai-portfolio-server` restart** (the running process predates
  this edit). To activate immediately, operator may run:
  `! sudo systemctl restart tradeai-portfolio-server.service`

No live trading, no order mutation, Level 7 prohibited.

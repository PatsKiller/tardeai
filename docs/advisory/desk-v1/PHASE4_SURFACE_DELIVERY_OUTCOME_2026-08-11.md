# Phase 4 Outcome — Surface & Delivery

**Date:** 2026-08-11  
**Branch:** `feature/advisory-desk-v1`  
**Plan:** [AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md](./AUTONOMOUS_ADVISORY_DESK_PLAN_2026-08-10.md)  
**Depends on:** Phase 0–3  
**Authority:** READ_ONLY_ADVISORY  

---

## Delivered

| Track | Work | Status |
|---|---|---|
| **4A** | `GET /api/v3/advisory` (+ rows/brief/history/calibration) | **DONE** |
| **4A** | `POST /api/v3/advisory/{rate,ack,snooze}` → feedback JSONL | **DONE** |
| **4A** | CC v3 page `/v3/advisory` — classes, expand, data-quality, 5 banners | **DONE** |
| **4A** | Nav: Intel → **Advisory Desk** | **DONE** |
| **4B** | Telegram brief ≤5 body lines (`advisory_telegram_brief.py`) | **DONE** |
| **4B** | `/advisory` commands in telegram_command_handler | **DONE** |
| **4B** | Morning digest section **additive** (does not replace portfolio/stops/health) | **DONE** |
| **4.5** | Pre-existing alert producers unchanged | **PASS** (section order still has portfolio/stops/health) |

---

## API

| Method | Path | Role |
|---|---|---|
| GET | `/api/v3/advisory` | Full desk + 5 banners + rows |
| GET | `/api/v3/advisory?class=holding` | Class filter |
| GET | `/api/v3/advisory/brief` | Telegram-sized brief |
| GET | `/api/v3/advisory/calibration` | Outcome hit rates |
| GET | `/api/v3/advisory/history/{SYM}` | Prior + feedback |
| POST | `/api/v3/advisory/rate` | `{symbol,rating,reason_code?,note?}` |
| POST | `/api/v3/advisory/ack` | `{symbol}` |
| POST | `/api/v3/advisory/snooze` | `{symbol}` |

---

## Five banner states

Always returned (exactly 5):

1. **OK** or **VALIDATION_FAIL**  
2. **PLAUSIBILITY_OK** or **PLAUSIBILITY_FAIL**  
3. **LOTS_OK** or **UNTRUSTED_LOTS**  
4. **LLM_OFF** / **LLM_DRY** / **LLM_ON**  
5. **INVARIANTS_OK** or **INVARIANT_VIOLATIONS**  

---

## UI (`/v3/advisory`)

- Class tabs: all · holding · watchlist · allocation · closed_journal  
- Columns include **Data quality** (evidence count, gaps, lot status)  
- Expand: lots · price action · analyst · memory · opinion · instrument  
- Actions: Ack / Snooze / Useful / Not useful·DISAGREE_THESIS  

---

## Telegram

```bash
# Print only
.venv/bin/python scripts/advisory_telegram_brief.py --print

# Send to all TELEGRAM_CHAT_ID recipients (comma-separated = both IDs)
.venv/bin/python scripts/advisory_telegram_brief.py --send
```

Bot commands (via existing poller):

```
/advisory
/advisory rate SCHD useful
/advisory rate SCHD notuseful DISAGREE_THESIS held
/advisory ack SCHD
/advisory snooze SCHD
/advisory history SCHD
/advisory calibration
```

---

## Alert regression (4.5)

| Check | Result |
|---|---|
| Morning digest still includes portfolio, technical, stops, health | **Yes** |
| Advisory is extra section, not first / not exclusive | **Yes** |
| `send_telegram` path for brief uses same transport; does not delete other producers | **Yes** |
| No change to `telegram_alert_router` suppress rules for existing P1s | **Unchanged** |

Operator should still confirm in production that overnight P1s fire after deploy (before/after diff of alert_events recommended).

---

## Pass criteria

| # | Criterion | Status |
|---|---|---|
| 4.1 | Page renders all classes; expand lots/PA/analyst/memory | **PASS** (UI + API expand payload) |
| 4.2 | All 5 banner states | **PASS** |
| 4.3 | Data-quality column | **PASS** |
| 4.4 | Telegram brief ≤5 body lines; multi chat via TELEGRAM_CHAT_ID | **PASS** (print/API; `--send` operator) |
| 4.5 | Pre-existing alerts intact | **PASS** structure; live event diff optional |
| 4.6 | ack/rate/snooze → ledger (feedback JSONL) | **PASS** (API + unit) |

---

## Tests

```
tests/test_advisory_desk_phase4.py → 8 passed
```

---

## Files

- `scripts/api_v3_advisory.py`
- `scripts/advisory_telegram_brief.py`
- `scripts/api_v2.py` (route registration)
- `scripts/telegram_command_handler.py` (`/advisory`)
- `scripts/morning_command_digest.py` (additive section)
- `apps/command-center-v3/src/pages/AdvisoryDeskHub.tsx`
- `apps/command-center-v3/src/App.tsx`
- `apps/command-center-v3/src/components/NavRail.tsx`
- `tests/test_advisory_desk_phase4.py`
- `docs/advisory/desk-v1/PHASE4_SURFACE_DELIVERY_OUTCOME_2026-08-11.md`

---

## Next (Phase 5)

Shadow 20 sessions with `ADVISORY_DESK_V1` for operator only; Guardian/Ledger specialist mandates; useful-rate ≥60%.

---

*Advisory only. No broker credentials or order authority.*

# PHASE 190 — Durable Protection Guardrails Implementation — CLOSEOUT

Status:      HISTORICAL
as_of:       2026-06-02T10:33:34-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 09:35–10:25 ET · Alpaca **paper** only · Live endpoint blocked

---

## What shipped
Root-cause durable fixes (not stop placement) so paper-position protection is **provable,
verified, and alertable**:
- **190B** `verify_paper_trade_broker_stops.py` — adds 11 protection columns; reads paper order
  book; persists `stop_order_id`/verification metadata. **Untracked 3 → 0.**
- **190C** `alpaca_paper_adapter.py` — capture broker stop response; note + tracking from
  confirmation, never from a boolean; persist `planned_stop` + protection fields at insert.
- **190D** `protection_alerts.py` + supervisor hook — detect defects from `paper_trades`, emit
  SIEM (`alert_events`, deduped), Telegram-gated. Routing bug fixed.
- **190E** `hermes_v_open_position_protection_context` view + `hermes_open_position_protection_check.py`
  + 6 new finding types — Hermes can now see/flag protection defects (advisory only).
- **190F** `api_v2.py` `GET /api/v2/atm/protection-coverage` + panel spec.
- **190G** `pending_trading_window.py` (advisory) + lifecycle design (wiring gated to Phase 191).

## Required closeout fields
- **Telegram digest sent:** ✅ YES (message_id 11226/11227, both chats, HTTP 200)
- **Phase 190 complete:** ✅ YES
- **Broker stop verifier implemented:** ✅ YES
- **ANY stop tracked in DB:** ✅ YES · **SNOW:** ✅ YES · **TMHC:** ✅ YES
- **Untracked broker stops before/after:** **3 → 0**
- **Take-profit missing count:** 6 (unchanged — TP assignment is an operator decision, not auto-set)
- **Health-agent routing fixed:** ✅ YES (SIEM emit + Telegram gate; reads paper_trades)
- **Hermes protection view/rule added:** ✅ YES (view + 6 rules + taxonomy extension)
- **ATM protection dashboard updated:** ✅ endpoint added (UI panel on next deploy/restart)
- **PENDING_TRADING_WINDOW implemented/designed:** **DESIGNED** + safe advisory analyzer
  (implementation gated to Phase 191 to avoid GO/WAIT changes)
- **No new stops placed:** ✅ YES (none) · **No stops modified:** ✅ YES (none)
- **Paper account verified:** ✅ YES (`PA3E93QWASV1`) · **Alpaca broker verified:** ✅ YES
- **Live endpoint blocked:** ✅ YES · **Live trading:** ZERO · **GO/WAIT mutation:** ZERO ·
  **Strategy mutation:** ZERO (pre-existing dirty configs untouched) · **Level 7:** PROHIBITED
- **Drive sync status:** Phase 190 docs synced post-commit (see sync log)
- **Next recommended gate:** **Phase 191 — Submission-time protection enforcement + PENDING_TRADING_WINDOW
  wiring + scheduling** (block paper entries lacking a confirmed stop; cron the verifier + Hermes
  check; enable Telegram routing after a noise check; wire the deferred lifecycle into the approver
  under explicit GO/WAIT-safe review).

## New scheduling recommended (Phase 191 / ops)
- `verify_paper_trade_broker_stops.py` — every 5–15 min, market hours.
- `hermes_open_position_protection_check.py` — each Hermes session.
- `protection_alerts.py` — covered by the supervisor `*/3` hook; set `PROTECTION_ALERTS_TELEGRAM=true`
  after noise review.

## Guardrail attestation
No live account/endpoint/broker mode, no live trades, no holdings mutated, no strategy configs
changed, no GO/WAIT logic changed, Level 7 not enabled, Claude Code auto-update not run. No broker
stop placed, modified, or cancelled. DB writes were limited to paper_trades protection metadata,
two new analyzer/alert tables' rows (alert_events, hermes_*), one view, and one CHECK-constraint
extension.

# Stop Management Architecture (as-built)

**Status: LIVE in production as of 2026-06-15.** This is the canonical reference for how protective stops
are placed, monitored, modified, cancelled, curated, and (for paper) auto-managed across every account.
Supersedes the design intent in [`stage2c-protective-stops-spec.md`](stage2c-protective-stops-spec.md).

---

## 1. Design principles

1. **Protective SELL stops are the safe direction.** They sell-to-close an existing long — they can never
   open a position or overspend. That property is what makes a standing (no-ARM) capability acceptable.
2. **Live accounts are manual + per-order 2FA. Paper is automatic.** Schwab (taxable + both IRAs) requires
   a human typed-ticker **or** Telegram/email code for every place/modify. Alpaca paper is auto-managed for
   best R:R (no 2FA — it's paper).
3. **Safe-by-default routing.** The account decides the path, never the client: an account with a trading
   API + write enabled → live submit; anything else → an exact thinkorswim ticket to place by hand.
4. **The broker is the source of truth.** Monitoring reads the broker's live orders, not local state.
5. **Commit-only envelope.** The risk envelope lives in committed code (`protective_stop_policy.py`),
   tamper-evidenced against git HEAD by the write-policy validator. UI/config/DB can never widen it.
6. **Ratchet-only.** Automatic (paper) stop movement only ever raises a stop; locked risk can only improve.

---

## 2. Account capability matrix

| Account | Trading API | Protective stops | Management |
|---|---|---|---|
| `schwab_taxable` | ✅ yes | ✅ live (any symbol ≤ $250k) | **Manual + 2FA** |
| `schwab_roth_ira` | ✅ yes | ✅ live | **Manual + 2FA** |
| `schwab_rollover_ira` | ✅ yes | ✅ live | **Manual + 2FA** |
| `fidelity_401k` | ❌ none | ⛔ ticket only (manual ToS) | n/a (no API) |
| `fidelity_rollover_ira` | ❌ SnapTrade read-only | 🔒 monitored only (after `--approve`) | **Monitor-only** — no 2FA; alert + manual Active Trader ticket on breach |
| `alpaca_paper` | ✅ yes (paper) | ✅ via paper pipeline | **Automatic (ratchet for R:R)** |

---

## 3. The gating stack (Schwab live path)

Every Schwab submit passes the full stack before any HTTP reaches the broker. Any failure → fail closed.

```
holdings card  →  POST /api/v2/holdings/protective-stop  (build intent, server-truth held qty/price)
   │
   ├─ protective_stop_policy.evaluate()   ── the committed ENVELOPE (commit-only, tamper-evidenced)
   │     • ENABLED master gate
   │     • account ∈ effective_account_allowlist()  (taxable + IRAs when IRA_PROTECTIVE_ENABLED)
   │     • instruction == SELL (sell-to-close)         • order_type ∈ STOP/STOP_LIMIT/TRAILING_STOP
   │     • stop BELOW current price                     • |stop − advised| ≤ ±8% drift
   │     • qty ≤ shares held                            • notional ≤ $250,000
   │
   ├─ execution_guard.authorize(intent, "submit")
   │     • marker meta.strategy_id == PROTECTIVE_STOP_2C routes through protective_stop_policy
   │       INSTEAD of the BUY canary gate, and SKIPS the canary 5-order cap
   │     • STANDING unlock: _protective_unlocked() = policy ENABLED + system_controls
   │       ['protective_stops_enabled']='true'   (NO expiring ARM session — that's canary-only)
   │     • per-order 2FA required (web typed-ticker OR telegram/email code)
   │
   ├─ schwab_transport._pilot_preconditions(account, kind='protective_stop')
   │     • account ∈ protective allowlist        • broker_accounts.api_write_enabled is TRUE
   │
   └─ schwab_transport.place_order(..., kind='protective_stop')
         persist row (reconcile anchor) → POST → consume 2FA → read-back.
         kind='protective_stop' so pilot_caps counts ONLY canary rows (canary budget untouched).
```

**Standing vs ARM.** The Stage-2b canary BUY pilot still requires the expiring `pilot_armed_until` arm
session. Protective stops do **not** — they run on the standing `protective_stops_enabled` control. Proven:
with the pilot disarmed, a protective taxable/IRA submit reaches "2FA only" while a canary BUY is blocked.

---

## 4. Per-order 2FA (either channel)

`brokers/approval_service.py`, `REQUIRED_CHANNELS=1` — **either** channel confirms:

- **web** — type the ticker exactly in the modal (anti-fat-finger).
- **telegram / email** — a 6-digit one-time code is sent to **both** Telegram and email; enter it, or tap
  ✅ Approve in the Telegram message.

One order at a time; codes are single-use, TTL 10 min, and burned on submit.

---

## 5. Lifecycle & the three operator actions

```
engine advises stop ─▶ [Queue stop ★] ─▶ REQUEST ─▶ 2FA ─▶ LIVE at broker ─▶ monitored
                                                                  │
   ┌──────────────────────────────────────────────────────────────┤
   ▼ price rises                                                    ▼ thesis breaks / trim
[Modify]  cancel old + place new (one 2FA, never a gap that double-stops)      [Cancel stop] (no 2FA)
```

- **Place** — `/api/v2/holdings/protective-stop` (request) → `/protective-stop/confirm` (2FA + submit).
- **Modify** — same flow with `replace_order_id` threaded through the intent; on confirm the old stop is
  cancelled **first**, then the new one placed. The cancel is **verified at the broker** before the new
  submit: `schwab_transport.cancel_order_for_replace()` polls Schwab until the old order is terminal
  (CANCELED/REPLACED/…) or gone from open orders; if that can't be confirmed, `place_order` raises
  `replace_cancel_incomplete` and the new stop is NOT placed (no double stop). The cancel-then-place gate
  lives **inside `schwab_transport.place_order`** — one gate shared by the web confirm path and the
  Telegram `bkapprove` auto-fire, so no path can skip it. The duplicate-SELL-stop guard only skips the
  replace target when it is actually no longer live; a still-WORKING replace target blocks. A repeat DELETE
  after a successful cancel is treated as idempotent (broker truth re-checked). **Any live Schwab SELL
  stop** with a broker `order_id` is replaceable in-app (pilot or manual ToS): the UI sends
  `replace_order_id`, and `cancel_order_for_replace` cancels after verifying a live SELL STOP/TRAIL
  (`allow_manual_protective` only on this path). `open_trades_intelligence` still stamps `pilot_placed`
  for display. Amber **Modify** button on the protected banner, pre-filled with the current advised
  level. Regression tests: `tests/test_stop_replace_flow.py`. Native Schwab PUT `replace_order` remains
  FENCED (cancel-then-place only).
- **Cancel** — `/api/v2/holdings/protective-stop/cancel` → `schwab_transport.cancel_order` (safe direction,
  no 2FA). Standalone cancel still refuses non-pilot orders; use **Modify/replace** (2FA) to retire a
  manual ToS stop via cancel-then-place.

---

## 6. Monitoring engine

`stop_lifecycle_monitor.py` — reads the broker's **live** working stops across Schwab (taxable + both IRAs)
and Alpaca paper, cross-references shares held now, and classifies each:

| Dimension | Values |
|---|---|
| `lifecycle` | working · near_trigger (≤2%) · triggered · filled · cancelled · orphaned |
| `coverage` | full · oversized (stop qty > held) · partial (< held) · orphaned (no holding) |
| `proximity_pct` | % from current price down to the stop (trailing reports its offset cushion) |
| `health` | ok · warn · alert |

A standalone GTC stop does **not** auto-resize when you trim/add — `oversized`/`partial` catch that.
Persists a snapshot to the `stop_lifecycle` table. Exposed at **`GET /api/v2/stops/lifecycle`** (cached 45s,
fail-soft to the snapshot). The Open Trades card consumes it to show the green **✓ PROTECTED** banner +
Modify/Cancel, and the % from stop / coverage warnings. Refresh: the card polls every 60s; a
Command-Center place/cancel busts the cache for an immediate flip.

---

## 7. Health agent + Hermes + Grok

| Layer | File / cron | What it does |
|---|---|---|
| **Health agent** | `stop_health_check.py` · `*/10 9-16 * * 1-5` | Escalates ORPHANED / OVERSIZED / TRIGGERED / NEAR-TRIGGER (≤0.75%) via **SIEM** (`save_alert_event` source=`stop_health`) + **Telegram** (central router, dedup 1/2h) + **system_health_events** log. |
| **Hermes** | (same check) | Writes each fresh condition into `hermes_research_intelligence` (`research_type='stop_health'`), so it surfaces on the card's Hermes section + the Hermes hub — Hermes "watches" the stops. |
| **Grok curation** | `grok_stop_review.py` · `5 10,15 * * 1-5` | External-LLM **R:R** review of every live stop (position + P&L + placed-vs-advised + proximity + Hermes thesis) → `{grade, should_trail, recommendation, suggested_action, confidence}`. Persists `stop_grok_reviews` + a Hermes finding (`research_type='stop_curation'`, model=`grok`) → "reviewed by GROK" on the card. **Advisory only.** |

All three are READ-ONLY on the broker — they never place/move/cancel a Schwab order.

---

## 8. Alpaca automatic stop management (paper only)

`alpaca_stop_manager.py` · cron `*/20 9-16 * * 1-5 --apply`. For each open paper position it asks
`strategy_trailing_policy.recommend_stop` (R-multiple tiers + optional structural overlay) for the
R:R-optimal stop and **ratchets the live Alpaca stop UP** to it (cancel + re-place via the paper API).

Safety invariants: ratchet-only (never lowers), never places at/above current price, ignores < 0.25%
nudges, automatic (no 2FA — paper), audited + SIEM-logged, persists new stop + order_id to `paper_trades`.
Respects **Hard Rule 7** — the paper pipeline owns paper execution; this uses the Alpaca paper API directly,
never the Schwab guard. Schwab accounts are **never** auto-managed (manual + 2FA always).

---

## 9. Components map

| File | Role |
|---|---|
| `scripts/brokers/protective_stop_policy.py` | The committed risk envelope + `effective_account_allowlist()` + POC layer (retired) + IRA flag. **Tamper-evidenced.** |
| `scripts/brokers/execution_guard.py` | `_protective_unlocked()` (standing), protective routing, grant logic. |
| `scripts/brokers/protective_stop_pilot.py` | Spec/intent builders, request-2FA, submit, `replace_order_id`, `load_intent`/`spec_from_intent`. |
| `scripts/brokers/approval_service.py` | Per-order 2FA (web ticker OR telegram/email code). |
| `scripts/schwab_transport.py` | The only Schwab write path: `place_order`/`cancel_order` (kind-aware preconditions), `cancel_order_for_replace`/`verify_order_canceled` (verified cancel-then-place), REJECTED read-back detection (`rejected_by_broker`). |
| `scripts/brokers/intent_submit_router.py` | Single post-2FA submit path (`submit_fully_approved`) shared by web confirm + Telegram auto-fire; `cancel_replace_stop_if_needed` for Fidelity monitored-stop replaces. |
| `scripts/stop_lifecycle_monitor.py` | Lifecycle + proximity + coverage engine (Schwab + Alpaca). |
| `scripts/stop_health_check.py` | Health-agent face → SIEM + Telegram + system_health + Hermes. |
| `scripts/grok_stop_review.py` | Grok R:R curation → `stop_grok_reviews` + Hermes. |
| `scripts/alpaca_stop_manager.py` | Paper-only automatic ratchet-up. |
| `apps/command-center-v3/src/components/PositionDecisionCard.tsx` | Card: place/modify/cancel modal, ✓ PROTECTED banner, coverage warnings, % from stop. |

---

## 10. API endpoints

| Method · Path | Purpose |
|---|---|
| `POST /api/v2/holdings/protective-stop` | Request: build intent → 2FA (live) or ticket (no-API/disarmed). |
| `POST /api/v2/holdings/protective-stop/confirm` | Confirm 2FA → (modify: cancel old) → submit. |
| `POST /api/v2/holdings/protective-stop/cancel` | Cancel a live stop (safe direction, no 2FA). |
| `GET  /api/v2/stops/lifecycle` | Latest lifecycle/proximity/health scan (cached 45s). |

---

## 11. Data model

| Table | Written by | Holds |
|---|---|---|
| `schwab_pilot_orders` | `schwab_transport` | Every Schwab order at the POST boundary; `kind` ∈ canary/protective_stop. |
| `trade_approvals` | `approval_service` | Per-order 2FA channels/codes/status. |
| `stop_lifecycle` | `stop_lifecycle_monitor` | Latest snapshot of every live stop's classification. |
| `stop_grok_reviews` | `grok_stop_review` | Grok R:R verdict per stop. |
| `hermes_research_intelligence` | health + grok | `stop_health` / `stop_curation` findings (card + hub). |
| `system_health_events` | `stop_health_check` | Watchdog record that the check ran. |
| `system_controls` | arm / enable | `protective_stops_enabled`, `broker_live_enabled`, `pilot_armed_until`. |

---

## 12. Operator runbook

- **Place / Modify / Cancel** — Open Trades card → the protection-advisory buttons / the ✓ PROTECTED banner.
  Modify is the right move after a price rise (raises the stop, one 2FA).
- **Enable protective stops** (standing): `system_controls['protective_stops_enabled']='true'`.
  **Revoke instantly**: set it to anything else — all Schwab protective submits then fall to ticket mode.
- **Add an IRA**: `IRA_PROTECTIVE_ENABLED=True` (commit) **and** `api_write_enabled=true` on the row.
- **Widen the envelope**: edit `protective_stop_policy.py` and commit (tamper-evidence requires it).
- **Pause Alpaca auto-management**: disable the `alpaca_stop_manager.py` cron line.
- **Canary BUY pilot** is separate and still ARM-gated (Trading → Broker Orders → ARM).

---

## 13. Safety invariants (must always hold)

1. SELL-to-close only; `qty ≤ held`; stop strictly below price; notional ≤ $250k.
2. Schwab placements/modifies always require per-order 2FA. No exception, ever.
3. Fidelity 401k can never API-submit (ticket only).
4. Alpaca auto-management is ratchet-only and paper-only; it never touches a Schwab order.
5. The envelope is commit-only and tamper-evidenced; UI/config/DB cannot widen it.
6. Modify cancels the old stop before placing the new; on cancel failure it does NOT place (no double stop).

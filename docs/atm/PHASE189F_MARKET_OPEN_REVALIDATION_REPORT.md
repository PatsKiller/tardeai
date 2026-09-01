# PHASE 189F — Market-Open Revalidation Report (post-open, authoritative)

Status:      HISTORICAL
as_of:       2026-06-02T09:35:38-04:00
Measured at: efcc51365 / not measured

**Watch fired:** ✅ YES — cron `atm-market-open-watch-0930` ran **2026-06-02 09:30:02 ET**
(`logs/atm_market_open_watch.log`). **Revised with fresh live re-quotes pulled 09:32 ET.**
Alpaca **paper** only · Live endpoint blocked · READ-ONLY (no orders/stops/mutations).

> The 09:30 auto-run reported position P&L from the DB `current_price` (yesterday's close). This
> revision overlays **fresh live quotes** so SNOW/ANY marks are real, not stale.

---

## ELMT — DID NOT CLEAR (REJECTED, aged out premarket)

| Field | Value |
|---|---|
| Proposal id | #161 |
| Current status | **REJECTED** / action_state BLOCKED |
| Rejected at | 2026-06-02 **09:00:02 ET** (premarket, before the open) |
| Rejection reason | `auto_blocked_230min` (proposal aged past 230 min) |
| action_label | "Cannot approve: quote for ELMT is 1020.0min old. Need fresh market data." |
| Fresh quote now | YES (age 0.3 min) |
| Quote timestamp | 2026-06-02 ~09:32 ET |
| Last price | 19.21 |
| Bid / Ask / Spread | 16.47 / 22.52 / **6.05 (~31% — untradeable)** |
| Signal still valid | N/A — proposal already REJECTED/dead |
| Stop/target valid | N/A |
| R:R valid | N/A |
| Stage 1 caps pass | YES (6 open, 0 new) but moot |
| Auto-approver eligible | **NO** |
| Submitted/held/rejected | **REJECTED** (not submitted) |
| New ELMT proposal post-open? | **NO** — 0 proposals created/updated after 09:30 |

**Read:** ELMT aged out and was auto-rejected premarket; no live ELMT proposal exists now. Even if
regenerated, the ~31% opening spread would fail any liquidity gate. The stale-quote/age gate
behaved correctly. (Gap remains: no `PENDING_TRADING_WINDOW` state — see 189B.)

---

## Open positions — fresh live re-quote (09:32 ET)

| Sym | Live last | DB mark | Live uPnL | Broker stop | DB stop_order_id | planned_stop | take-profit | Protection | Defect severity |
|---|---|---|---|---|---|---|---|---|---|
| ANY | 4.15 | 4.05 | **+$569.48** (+5.75R vs stop) | 3.07 ✅ | **NULL** | NULL | NULL | PROTECTED_UNRECORDED | **P1** (big gain, untracked, no TP) |
| SNOW | **267.94** | 280.10 | **+$251.50** (~+13.3%) | 254.38 ✅ (locks gain) | **NULL** | NULL | NULL | PROTECTED_UNRECORDED | **P1** (untracked, no TP) |
| TMHC | 71.60* | 71.55 | ≈ −$0.27 | 68.02 ✅ | **NULL** | NULL | NULL | PROTECTED_UNRECORDED | P2 (untracked) |
| NWG | 15.95 | 15.95 | +$26.46 | 15.05 ✅ | ✅ tracked | 15.05 | NULL | PROTECTED_TRACKED | none |
| AGNC | 10.24 | 10.24 | +$5.86 | 9.71 ✅ | ✅ tracked | 9.71 | NULL | PROTECTED_TRACKED | none |
| CMCSA | 25.05 | 25.05 | +$9.60 | 23.61 ✅ | ✅ tracked | 23.61 | NULL | PROTECTED_TRACKED | none |

\* TMHC live bid/ask 61.56/81.67 — no real two-sided market at the open; treat last as noisy.

### Per-symbol detail (as required)

**ANY (48):** fresh quote YES (age 0.0). price 4.15. uPnL **+$569.48**. R vs broker stop **+5.75R**
(risk/sh 0.16). Broker stop exists **YES** (@3.07). DB stop_order_id **NO**. planned_stop **NO**.
take-profit **NO**. Severity **P1**. Operator action required: **YES — profit-protection review**
(largest unrealized gain; stop only near breakeven; no TP/trailing). *Stops exist — not urgent-naked.*

**SNOW (43):** fresh quote YES (age 0.0). price **267.94**. **Prior +18% mark was STALE/inflated —
real live ≈ +13.3%.** uPnL **+$251.50** (was +$348.78 on the stale 280.10 mark). R: stop @254.38
is **above** entry (236.50), so downside R vs entry is N/A — the stop already locks a gain. Broker
stop exists **YES**. DB stop_order_id **NO**. planned_stop **NO**. take-profit **NO**. Severity
**P1**. Operator action required: **YES — record/verify stop + consider trailing/TP.** *Protected.*

**TMHC (47):** fresh quote YES but spread garbage (61.56/81.67). Broker stop exists **YES** (@68.02).
DB stop_order_id **NO**. Stop note broker-confirmed **NO** (note written from `use_market` boolean).
Severity **P2**. Operator action required: **YES — record/verify stop** (low urgency; trade ~flat).

---

## Counts (post-open)
- Open positions reviewed: **6**
- Naked broker stops (no broker stop): **0**
- Untracked broker stops (stop exists, DB `stop_order_id` missing): **3** (ANY, SNOW, TMHC)
- Take-profit missing: **6**
- New trades premarket/at-open: **0**

## SIEM / Telegram
- Watch generated no SIEM/Telegram (read-only by design). A corrected actionable digest is
  prepared in 189E — **not auto-sent** (awaiting operator OK).

_Guardrails: paper-only, live endpoint blocked, Level 7 prohibited, zero mutations. No stop was
placed, modified, or cancelled. Broker stops re-verified live: all 6 present, status=new._

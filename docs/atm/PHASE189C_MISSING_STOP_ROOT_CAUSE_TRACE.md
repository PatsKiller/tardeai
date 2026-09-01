# PHASE 189C — Missing-Stop Root-Cause Trace

Status:      HISTORICAL
as_of:       2026-06-02T09:13:00-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~09:08 ET · Alpaca **paper** only · Evidence-backed (file:line)

---

## ⚠️ Material correction to Phase 188

Phase 188 concluded ANY and SNOW were **"naked — no stop."** **That was wrong.** Direct
read-only query of the Alpaca **paper** order book confirms **all six open positions currently
hold a live broker stop order:**

| Sym | Broker stop | Qty | Broker order id | DB `stop_order_id` | DB `stop_loss` | Protection |
|---|---|---|---|---|---|---|
| ANY | 3.07 | 619 | `8bfdde82` | **NULL** | **NULL** | PROTECTED_UNRECORDED |
| SNOW | 254.38 | 8 | `8737e56d` | **NULL** | **NULL** | PROTECTED_UNRECORDED |
| TMHC | 68.02 | 27 | `f7347a29` | **NULL** | 68.02 | PROTECTED_UNRECORDED |
| NWG | 15.05 | 189 | `45b57b20` | `45b57b20` ✅ | 15.05 | PROTECTED_TRACKED |
| CMCSA | 23.61 | 120 | `e29b2971` | `e29b2971` ✅ | 23.61 | PROTECTED_TRACKED |
| AGNC | 9.71 | 293 | `f171e7ec` | `f171e7ec` ✅ | 9.71 | PROTECTED_TRACKED |

**The book is hedged.** The defect is a RECORD / VERIFY / TRACKING gap, not an unhedged-position
emergency. Note the split: the three **proposal-originated income trades carry a recorded
`stop_order_id` and are fully tracked**; the two **`alpaca_sync` positions (ANY, SNOW)** and the
**market-order proposal trade (TMHC)** have a live broker stop that the DB never recorded. For
those three the system cannot *prove* protection from its own DB, cannot self-heal if a broker
stop vanishes, and emits no alert — because the post-fill / sync paths in
`alpaca_paper_adapter.py` never persist the returned `stop_order_id` (the string does not appear
in that file at all). The bracket/proposal path that *does* record it is why the income trades
are clean.

> Severity reframed: from "P0 naked book" → "P1 observability/verification defect with latent P0
> exposure if a broker stop is cancelled/filled and nothing notices."

---

## Per-position trace

### ANY (id 48) — `alpaca_sync`
| Field | Value |
|---|---|
| Source | Alpaca sync onboarding — `alpaca_paper_adapter.py:155-166` |
| Proposal id | NULL (sync path never sets it) |
| Broker stop | **EXISTS** @ 3.07 (`8bfdde82`) — but unrecorded |
| planned_stop expected | NO — INSERT hardcodes `'unknown_sync'`, omits stop/target/proposal |
| stop_order_id in DB | **NO** |
| Verification job | none persists it (see below) |
| Failure logged/alerted | **NO** |
| **Root cause** | `ALPACA_SYNC_ONBOARDED_WITHOUT_METADATA` + `IMPORTED_POSITION_WITHOUT_PROTECTION` (metadata sense) + `STOP_PLACED_BUT_NOT_RECORDED` + `HEALTH_AGENT_COVERAGE_GAP` |

Evidence — the onboarding INSERT (`alpaca_paper_adapter.py:157-166`) writes
`strategy_id='unknown_sync'`, `opened_via='alpaca_sync'` and **no** stop/target/planned_stop/
proposal_id. Self-heal in `paper_trade_monitor.py:373` is gated `if ... stop > 0` — with
`stop_loss` NULL the branch never runs.

### SNOW (id 43) — `alpaca_sync`
Identical path/defects to ANY. Broker stop **EXISTS** @ 254.38 (`8737e56d`). Note the stop sits
**above** entry (236.50) — it is effectively locking a gain — but its provenance is untracked and
the DB shows no stop at all. **Root cause: same four labels as ANY.**

### TMHC (id 47) — `alpaca_adapter`, proposal 159
| Field | Value |
|---|---|
| Source | `submit_entry` proposal path — `alpaca_paper_adapter.py:272`, INSERT `:596-627` |
| Proposal id | 159 (`proposed_stop=68.02, final_stop=68.02, APPROVED_FOR_PAPER_TEST`) → **proposal carried a valid stop** |
| Broker stop | **EXISTS** @ 68.02 (`f7347a29`) |
| stop placement attempted | **YES** — `alpaca_paper_adapter.py:526-534` posts a separate stop order |
| stop_order_id in DB | **NO** — the `_api_post` return (which contains the id) is discarded (`:534`) |
| planned_stop in DB | **NO** — INSERT sets `stop_loss/target_1` but never `planned_stop` (`:596-606`) |
| "placed after fill" note | written **unconditionally** from `not use_market` (`:626-627`), not from broker confirmation |
| **Root cause** | `STOP_PLACED_BUT_NOT_RECORDED` + `JOURNAL_METADATA_GAP` + `HEALTH_AGENT_COVERAGE_GAP` (explicitly **NOT** `PROPOSAL_MISSING_STOP`, **NOT** `SUBMITTER_DID_NOT_PLACE_STOP`, **NOT** `BROKER_STOP_REJECTED`) |

Evidence — `alpaca_paper_adapter.py:530-536` posts the stop then logs success and sets
`stop_placed=True` **without capturing** the returned order id; `_api_post` does return the JSON
(`:73-77`). The note string at `:626-627` is a pure function of the `use_market` boolean — it
would read "placed after fill" even if the stop had been silently rejected with HTTP 200.

---

## Verification & alerting coverage (all three)

- **Only broker-stop verifier:** `reconcile_stop_v21_broker_stops.py` — **report-only**
  (`:4-5`), correctly covers synced/NULL-strategy rows (`:89-92`, no exclusionary filter),
  classifies these as `MISSING_BROKER_STOP`/`MISSING_DB_STOP` (`:16-29`), finds the broker stop
  via single-symbol fallback (`:167-182`) **but does not persist the id**. It is **NOT in
  crontab** — only runs embedded in `unified_stop_supervisor.py:55-56`.
- `unified_stop_supervisor.py` on critical findings only `log.warning`s (`:126-128`), hardcodes
  `stops_created:False` (`:199`), and **has no Telegram/SIEM call** — findings are buried in a
  log.
- `backfill_stop_v20_tracking.py` *can* persist `stop_order_id` (`:116-133`) and backfill
  `planned_stop` from `stop_loss` (`:99-111`) — but it is a **manual one-shot, NOT in crontab**.
- **No SIEM/Telegram alert exists** for a missing/unverified broker stop (searched the
  reconciler, supervisor, `paper_trade_monitor.py:372-377`, `portfolio_stops.py:258-284`,
  `alpaca_paper_reconciler.py` — the last never queries stops at all).

## Root-cause categories (summary)
- **ANY (48):** ALPACA_SYNC_ONBOARDED_WITHOUT_METADATA, IMPORTED_POSITION_WITHOUT_PROTECTION, STOP_PLACED_BUT_NOT_RECORDED, HEALTH_AGENT_COVERAGE_GAP
- **SNOW (43):** same four
- **TMHC (47):** STOP_PLACED_BUT_NOT_RECORDED, JOURNAL_METADATA_GAP, HEALTH_AGENT_COVERAGE_GAP

No fix applied here (root-cause phase). Remediation in 189G; implementation deferred to Phase 190.

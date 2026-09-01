# PHASE 189B — Extended-Hours Capability & Blockage Root Cause

Status:      HISTORICAL
as_of:       2026-06-02T09:13:00-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~09:08 ET · Alpaca **paper** only · Evidence-backed (file:line)

---

## TL;DR
The Alpaca paper adapter **is** extended-hours capable and builds a *correct* extended-hours
order (limit + TIF=day + `extended_hours:True`). It is never reached in the auto path because a
**market-session code gate short-circuits execution before the adapter runs** — not because of
cron, order type, or a missing parameter. A second, independent contributor is the **default IEX
data feed**, which returns little/no premarket data for low-float names.

---

## Capability checklist

| Question | Answer | Evidence |
|---|---|---|
| Adapter supports `extended_hours` flag? | **YES, set True** | `alpaca_paper_adapter.py:437-444` builds `{type:'limit', time_in_force:'day', extended_hours:True}` |
| Order type / TIF valid for ext-hours? | **YES** (limit+day) | `:441-443`; market→limit forced at `:429-431` |
| Limit orders used where required? | **YES** | brackets omitted in ext-hours (`:438`); limit forced |
| Entries allowed in ext-hours (config)? | YES at adapter; gated upstream | adapter `:418-422` only blocks 20:00–04:00 |
| Exits allowed in ext-hours? | Strategy-dependent | `market_session.py:138-141` exempts swing/income/position/dividend only |
| Auto-approver runs in ext-hours? | **YES** | cron `*/15 4-19 * * 1-5`; `_in_operating_hours` starts 04:00 (`atm_auto_approver.py:133-151`) |
| Stale-quote gate blocks before live data? | YES (secondary) | `paper_execution_revalidator.py:242-245` `no_quote_data` → blocked_safety |
| Data feed provides premarket quotes? | **Largely NO (IEX default)** | `market_quote_provider.py:85-87,156-158` — no `feed=` param → IEX |
| Feed delayed / regular-hours / unauth? | IEX free feed, thin premarket | no `feed=sip` anywhere in `scripts/*.py` |

## Why premarket action does not happen — ranked

1. **Market-session gate (dominant, fires first).** `paper_execution_revalidator.py:214` calls
   `market_session.should_delay_execution(strategy)`. For `premarket` it returns
   `(True, "premarket_wait_for_open")` (`market_session.py:135-137`) → `status="delayed"`,
   `score -= 50` → `submit_paper` returns `{"status":"delayed"}` (`proposal_paper_submitter.py:558-565`).
   **No order is ever sent.** This ignores the adapter's extended-hours capability entirely.
2. **Data feed not live in premarket (IEX default).** Even if (1) were lifted, IEX premarket
   quotes for low-float names are frequently empty → `no_quote_data` critical block
   (`paper_execution_revalidator.py:242-245`).
3. **30-min stale-recommendation threshold for momentum_scalp.** `market_session.py:34`
   (`momentum_scalp: 30`), penalized at `paper_execution_revalidator.py:226-231`.
4. **Unreachable extended-hours adapter path.** The correct code at
   `alpaca_paper_adapter.py:437-444` never executes because revalidation returns `delayed`
   before `submit_entry` is called.

**NOT the cause:** cron schedule (covers 04:00–19:59), order-type/TIF (correct), missing
`extended_hours` param (present), `_in_operating_hours` (passes at 04:00), paper adapter
limitation (adapter is capable).

> Design read: the system is *intentionally* configured to wait for the 09:30 open for scalps
> (`should_delay_execution`), which is defensible. The defect is that this is implemented as a
> transient per-cycle "delayed" verdict rather than an explicit deferred lifecycle state — see
> the ELMT section.

## ELMT specifically

- **Blocked correctly?** Yes in outcome, but the *primary* reason is the **premarket session
  gate**, not the stale-quote gate (the stale-quote gate is secondary). Correct to not submit a
  momentum scalp premarket.
- **Eligible if quote were fresh?** Not premarket — `should_delay_execution` still returns
  delayed. In a regular session with a fresh quote it would then face the R:R gate
  (`approval_revalidator.py:211-221`: R:R ≥ 1.5 block / ≥ 2.0 preferred), drift < 10%, and
  `score ≥ 70`. Freshness alone is **insufficient**.
- **Dedup working?** **YES.** `auto_proposal_generator.py:268-281` and
  `incubator_proposal_promoter.py:410-416` skip when a PENDING/APPROVED row already exists. The
  "keeps re-proposing" appearance is the **same row (id 161)** re-touched each cycle, not new
  rows. (At 09:08 ET id 161 has since moved to REJECTED.)
- **Should there be a `PENDING_TRADING_WINDOW` / deferred state?** **YES — and it does not exist
  (NOT FOUND).** No `PENDING_TRADING_WINDOW`/`WAIT_FOR_OPEN`/`DEFERRED` state in
  `proposal_lifecycle.py`. A premarket scalp loops through delayed-revalidation every 15 min
  instead of being parked until the open. **Recommended fix (Phase 190):** add an explicit
  deferred-to-open lifecycle state; park premarket scalps there; stop re-revalidating until the
  session opens. Repeated stale proposals should be deduped into that single parked row.

## Recommended (do NOT implement here — root-cause phase only)
- Add `PENDING_TRADING_WINDOW` lifecycle state + park-until-open.
- Add `feed=sip` (if entitled) or explicitly accept IEX-premarket-empty and treat as "wait."
- If genuine premarket/extended-hours *entries* are ever desired, wire `submit_entry`'s
  extended-hours path to be reachable (it currently is dead code in the auto flow).

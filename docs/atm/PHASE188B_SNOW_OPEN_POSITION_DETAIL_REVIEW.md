# PHASE 188B — SNOW Open Position Detail Review

Status:      HISTORICAL
as_of:       2026-06-02T08:17:52-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~08:25 ET (premarket) · Alpaca **paper** only · Live endpoint blocked
**Headline:** SNOW shows a large **stale** unrealized gain and carries **no stop and no take-profit**.

---

## Full position detail (paper_trades id 43)

| Field | Value |
|---|---|
| Trade id | 43 |
| Proposal id | **None** (not proposal-originated) |
| Strategy | **`unknown_sync`** |
| Setup type | None |
| Entry price | 236.5025 |
| Current / last price | 280.10 (DB) / 280.03 (feed) |
| Quote timestamp | 2026-06-01 16:00 ET |
| Quote freshness | **STALE — age ≈ 974 min (~16 h)** |
| Share count | 8 |
| Notional (entry) | 1,892.02 |
| Notional (mark) | ≈ 2,240 |
| Unrealized P&L | +$348.78 (≈ **+18.4%**, on stale mark) |
| Unrealized R | stored 3.88 — **see caveat below** |
| Original stop | **None** |
| Current stop | **None** |
| Broker stop order id | **None** |
| Target / take-profit | **None** |
| Trailing active | **No** |
| Stop update history | None (never set) |
| Opened via | `alpaca_sync` (synced from broker, not proposal pipeline) |
| Entry time | 2026-06-01 10:57 ET |
| Catalyst / context | None recorded |
| Journal fields | None |
| Backtest comparison | Not available (no strategy/plan linkage) |
| Hermes opinion | None linked (`hermes_v_trade_reflection_context` has no row for id 43) |

## Caveat on "+18% / 3.88R"

- The **+18% is a stale mark** — it equals yesterday's 16:00 ET close (280.03), not a live
  premarket print. The feed has no fresh data for SNOW this session. **Treat the gain as
  unconfirmed until the open.**
- The stored `r_multiple = 3.88` is **not** produced by the trailing policy. The position has
  `planned_stop = None`, so STOP-V2.3's `recommend_stop()` cannot compute R at all (it returns
  `invalid entry/stop data`). The 3.88 was written by a separate calc using an assumed risk
  basis and should not be trusted for stop decisions.

## Root-cause summary (why SNOW has no protection)

1. **Origin:** SNOW entered via `alpaca_sync`, which mirrors a broker position into the DB but
   does **not** attach a trade plan, stop, target, or strategy classification.
2. **Strategy = `unknown_sync`:** STOP-V2.3 maps this to the `unknown` family → `DEFAULT_POLICY`
   with **empty tiers** → auto-trailing is structurally impossible for it.
3. **No `planned_stop`:** even if the family had tiers, R is uncomputable, so no tier can fire.

This is a **metadata/onboarding gap for synced positions**, not a +1R-detection bug.

## Cross-reference

The same defect applies to **ANY (id 48)** — also `unknown_sync`, also no stop, +$507.58 on a
619-share position. ANY is arguably the higher naked-risk exposure. See PHASE188C / 188D.

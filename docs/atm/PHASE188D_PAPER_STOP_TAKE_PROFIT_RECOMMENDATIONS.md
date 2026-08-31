# PHASE 188D — Paper-Only Stop / Take-Profit Recommendations

Status:      HISTORICAL
as_of:       2026-06-02T08:17:52-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~08:25 ET (premarket) · Alpaca **paper** only · Live endpoint blocked
**Nature:** Recommendations only. **No stop was modified, no order was placed.** Existing ATM
policy does not authorize automatic action on `unknown` family or on stale premarket quotes.

---

## Recommendation per position

| id | Sym | Recommendation | Rationale |
|---|---|---|---|
| 28 | NWG | **HOLD_NO_ACTION** | Income, R 0.13, stop+target live. Below 1.5R trailing tier. |
| 31 | AGNC | **HOLD_NO_ACTION** | Income, R 0.03, stop+target live. |
| 33 | CMCSA | **HOLD_NO_ACTION** | Income, R 0.07, stop+target live. |
| 43 | **SNOW** | **NEEDS_OPERATOR_REVIEW** → then `SET_TAKE_PROFIT` + assign stop at open | Naked, unknown_sync, large stale gain. Cannot auto-act. |
| 47 | TMHC | **NEEDS_OPERATOR_REVIEW** (verify/place broker stop $68.02) | Stop value exists but no broker stop order id. |
| 48 | **ANY** | **NEEDS_OPERATOR_REVIEW** → assign protective stop at open | Naked, unknown_sync, +$507 with no stop. Highest naked risk. |

> No `CONVERT_TO_TRAILING_STOP` or `MOVE_STOP_TO_BREAKEVEN` is recommended right now: the only
> positions deep enough to qualify (SNOW, ANY) have **no risk basis** for the engine to trail
> from, and all marks are stale. Re-evaluate at the open once R is computable on live data.

---

## SNOW — specific answers required by Phase 188

1. **Is the +18% mark real/current or stale?**
   **STALE.** The 280.03 mark is yesterday's 16:00 ET close (quote age ≈ 974 min). No fresh
   premarket print exists. The gain is **unconfirmed** until the 09:30 ET open.

2. **If real, why has no take-profit or trailing stop triggered?**
   Two stacked reasons:
   - **Strategy = `unknown_sync` → `unknown` family → DEFAULT_POLICY has empty tiers.** Auto-
     trailing is structurally impossible for this position.
   - **`planned_stop = None`** → STOP-V2.3 `recommend_stop()` returns `invalid entry/stop data`
     and cannot compute R, so no tier could fire even if tiers existed.

3. **Did the strategy policy fail to detect +1R?**
   **No.** The policy never received a valid risk basis. It did not "miss" +1R — it correctly
   refused to act on a position with no stop and an unknown strategy. This is a **data/onboarding
   gap for `alpaca_sync` positions**, not a detection bug.

4. **Is the trade missing risk/target metadata?**
   **Yes — entirely.** No stop, no target, no dollar_risk, no proposal/plan linkage, no strategy
   classification. Same for ANY (id 48).

5. **Should ATM protect paper profit under existing policy?**
   **Not automatically — existing policy explicitly withholds auto-action on `unknown` family and
   on stale quotes.** The correct move under current rules is **operator-reviewed** protection at
   the open: (a) classify the position to a real strategy family, (b) assign a protective stop
   (e.g. recent swing low / ATR-based), (c) set a take-profit or convert to trailing once R is
   computable on a live quote. This should NOT be forced premarket on stale data.

---

## Recommended operator actions at the open (paper-only)
1. **ANY (48)** — assign protective stop first (largest naked gain, no stop). Priority 1.
2. **SNOW (43)** — confirm live price, then set take-profit / trailing + protective stop.
3. **TMHC (47)** — verify the $68.02 broker stop order actually exists; place if missing.
4. Backlog: fix the `alpaca_sync` onboarding so synced positions get strategy + stop metadata
   (this is the proposed follow-up phase: *make profit protection automatic in paper mode*).

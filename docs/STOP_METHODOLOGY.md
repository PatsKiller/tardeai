# Stop & Trailing-Stop Methodology (canonical)

**Status:** Active · **Updated:** 2026-06-29 · **Scope:** protective stop / trailing-stop advisories for **real-account holdings** (Schwab + Fidelity). Paper/Alpaca execution is covered separately by [`OCO_ATM_UNIFICATION_DESIGN.md`](design/OCO_ATM_UNIFICATION_DESIGN.md) and `alpaca_stop_manager.py`.

> **Advisory only.** Nothing here places, modifies, or cancels a broker order. Real-account stops are operator-placed (Fidelity manual / Schwab per-order 2FA). The engine recommends; the operator executes.

---

## 1. Engine
`scripts/holding_protection_advisor.py` produces one stop/trailing recommendation per holding. For each position it gathers **read-only** technicals (RSI14, ATR14, 20-day swing low, 50-day SMA) + the Yahoo analyst layer, then asks a free-lane LLM for a strict-JSON recommendation, validates it, and stores it to `hermes_research_intelligence` (`research_type='protection_advisory'`). Surfaced on the Portfolio cards via `/api/v2/portfolio/llm-coverage`.

## 2. How a stop is sized (the rules, in order)
1. **Family classification** (`holding_family.classify_family`) → a per-family **% band**. The band is the hard envelope; the swing-low anchor places the stop *within* it.

   | Family | Floor (min %) | Cap (max %) | Hold style |
   |---|---|---|---|
   | **income** (dividend/income ETFs: SCHD, DIVI, JEPI, BND…) | **4%** | 10% | held through noise |
   | **position / core / growth** | **5%** | 12% | core compounding |
   *(values from `holding_family.protection_bounds`; ATR-aware classification)*

2. **Anchor to structure** — the stop sits at/just below the **20-day swing low**, between `swing_low − 1×ATR` and `swing_low` (anchored to real support, not arbitrary geometry).

3. **Clamp to the family band (both sides):**
   - **Too wide** (swing low further than the cap): cap the stop at `stop_max_pct` below price (position is extended).
   - **Too tight** (swing low closer than the floor — common for low-volatility income ETFs near their range): **widen the stop to `stop_min_pct` below price.** Added 2026-06-29 after SCHD/DIVI were found with ~2–3% stops that would whipsaw a core hold. The widening is recorded in the rationale and flagged `floored` in `evidence_json`.

   > A core income position must keep ≥ its family floor or it gets stopped out on ordinary noise — the opposite of "held through noise." 2026-06-29 sweep found **9 holdings** below floor (SCHD/BND/JEPI → 4%; DIVI/SCHG/ARKX/CSWC/HPE/XLB → 5%), all widened.

4. **`stop_pct_below`** = `round((price − stop_price)/price × 100, 1)` — always recomputed against the **live** price (the Portfolio card renders this live value, not the stale generation-time string).

## 3. Fixed vs trailing (rule, not preference)
- **Income / core:** FIXED stop. Trailing only when **unrealized ≥ +20% AND price > 50-day SMA** (a real runner) — then a PERCENT trail matching the fixed-stop width.
- **Normal families:** FIXED, with a PERCENT trail when **unrealized ≥ +10% AND price > 50-day SMA**.
- Trail offset is **PERCENT only** (no $ offsets, no ATR-multiples), bounded by the family `trail_min/max_pct`. A trailing stop ratchets up and never down.

## 4. LLM lanes (free only — no paid fallback)
- **Default:** free **Grok** OAuth lane (`:8645`). 
- **Resilience (2026-06-29):** on a Grok/ChatGPT OAuth failure (e.g. a 403 token-rotation blip) the advisor **falls back to the local gemma lane** (free) — it **never** falls back to a paid key (honours the no-paid-fallback policy; see [`diligence/current/LOCAL_LLM_RUNTIME_POLICY.md`](diligence/current/LOCAL_LLM_RUNTIME_POLICY.md)). The stored `lane`/`model_used` reflect the lane that actually produced the recommendation.

## 5. Validation (`_sanity_check`)
Every recommendation is checked against the real technicals + family bounds; verdict `ok | warn | fail`:
- `fail` — stop at/above price (would trigger immediately).
- `warn` — below the family floor (too tight / whipsaw), beyond the cap (too weak), tighter than the reachable 20-day swing low, or an out-of-band trail.

## 6. Display (Portfolio v3 card)
- Live **stop distance %** (recomputed against the live price), not the generation-time string.
- **Status is explicit:** `● STOP LIVE` (resting broker order) · `◉ MONITORED` (software-watched, not a broker order) · `○ ADVISORY … not placed` (recommendation only).
- **Lock-in-profits advisory (2026-06-30):** when a position holds a **live FIXED stop** and a trailing stop at the advised width would currently sit **above** that frozen trigger, the card surfaces a `📈 Lock in profits — switch to N% trailing` banner (trailing floor vs fixed stop + the gap). One-click switch routes per broker — **Schwab via API (per-order 2FA)**, **Fidelity as a manual Active Trader ticket**. Advisory only; it never moves an order itself. It fires only once price has risen enough that trailing locks a genuinely higher floor than the *placed* fixed stop (a fresh advisory at the current price has the same width as a fixed stop, so there is nothing to lock until price moves up).
- **Daily alert:** `scripts/stop_drift_alert.py --send` (cron `35 17 * * 1-5`) emits both the **ratchet-up** ("raise your stop") and the **lock-in** ("switch fixed→trailing") nudges to SIEM + Telegram, deduped per symbol per 12h by `kind`.

## 7. Governance — monthly Claude meta-review
`scripts/monthly_protection_meta_review.py` (1st of month, cost-gated Claude oversight) reviews **all** of the month's protection advisories per symbol — gemma + grok recs together — and judges soundness. Floor-widened recs carry an explicit **`floored`** flag so the widenings are sanity-checked specifically. This is the only paid lane in the stop path, and it is a deliberate, monthly, cost-gated review — never a per-call fallback.

## 8. Cross-references
`holding_protection_advisor.py`, `holding_family.py`, `monthly_protection_meta_review.py`, `HoldingProtectionActions.tsx`, `PortfolioHub.tsx`; paper side: `alpaca_stop_manager.py` + `design/OCO_ATM_UNIFICATION_DESIGN.md`; runtime/lane policy: `diligence/current/LOCAL_LLM_RUNTIME_POLICY.md`.

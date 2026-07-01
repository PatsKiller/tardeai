# Stop & Trailing-Stop Methodology (canonical)

**Status:** Active · **Updated:** 2026-06-30 · **Scope:** protective stop / trailing-stop advisories for **real-account holdings** (Schwab + Fidelity). Paper/Alpaca execution is covered separately by [`OCO_ATM_UNIFICATION_DESIGN.md`](design/OCO_ATM_UNIFICATION_DESIGN.md) and `alpaca_stop_manager.py`. **Momentum scalp paper trades** use a distinct layered policy: [`MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md`](MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md). **Click-time preflight UX** (operator choices 1A–5A): see §9 and [`runbooks/protective-stop-integration-2026-06-30.md`](runbooks/protective-stop-integration-2026-06-30.md#click-time-preflight-portfolio-ux-1a5a).

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

## 8. Quote freshness (session-aware gate)

The Portfolio stop panel blocks live-stop requests when the quote is outside a session-aware window (matches `scripts/brokers/quote_time.py`):

| Session | Max age |
|---------|---------|
| Regular | **15 min** |
| Pre-market / after-hours | **60 min** |

Naive `YYYY-MM-DD HH:MM:SS` timestamps from Finviz after-hours are parsed as **America/New_York**, not browser-local or UTC. The UI prefers `source_timestamp` (quote fetch time) over `price_as_of` for the freshness gate.

## 9. Click-time preflight (Portfolio UX — operator choices 1A–5A)

Before any Schwab 2FA submit or Fidelity manual ticket, `HoldingProtectionActions` runs a **read-only** click-time preflight (~1–3s). Nothing is submitted until validation completes.

**Sequence (always full — 4A):**

1. Pause — button shows `Validating…`
2. `POST /api/v2/holdings/protective-stop/refresh-quote` (Schwab → market provider → DB → Finviz; freshest wins)
3. `GET /api/v2/portfolio/llm-coverage` — refresh protection advisory for the symbol (**3A**)
4. `GET /api/v2/holdings/live-stops` — re-read broker protective stop (60s cache)
5. `GET /api/v2/holdings/stop-readiness` — Schwab canary gates (read-only)
6. Recalc `buildStopLogic` with fresh quote + advisory + live stop

**Outcomes:**

- **Unchanged + valid (1A):** auto-continues to 2FA intent / Fidelity manual ticket.
- **Changed (2A):** amber `preflight-changed` panel with structured before→after diff (price, decision, status, advisor stop, broker stop, recommendation, blockers ±) + **Proceed anyway** / **Cancel**.
- **2FA approve:** same preflight runs again before broker submit.

**Holding card sync (5A):** `PortfolioHub` merges preflight quote into the holding row (`current_price`, `market_value`, timestamps) and protection chip without a full holdings refetch.

Build marker: `cc-v3 stop-audit-sync 2026-07-01`.

## 9b. Data-integrity guards (2026-07-01)

- **No phantom stops.** The Stop Management aggregation used to resurrect a stale `stop_confirmations`
  record or `stop_lifecycle` snapshot as a live "active stop" even when the live Schwab order read
  succeeded. A healthy broker read is now **authoritative** — a confirmed/snapshot stop it does not show
  is skipped as stale, so an unprotected position never reads as protected. (JEPI showed a $55 stop from a
  2026-04-22 confirmation with zero live orders; NOC showed a stale snapshot. Both corrected; the JEPI
  record was set `unconfirmed`.) Fidelity (no broker API) confirmations still stand.

- **Family-floor drift reconciliation.** A FIXED advised stop is frozen at advisory time; if price drifts
  DOWN, a once-in-band income/position stop can fall INSIDE the family floor (e.g. JEPI $54.22 was 4% below
  the advisory-day price, 3.6% below current). `buildStopLogic` now **widens the effective advised stop to
  the family floor against the CURRENT price** (never tightens) instead of hard-blocking on `floor_mismatch`
  — mirroring `holding_protection_advisor.py`'s run-time floor enforcement, applied live so intraday drift
  doesn't dead-end placement. The daily advisor re-run re-floors the stored value.

## 10. Cross-references
`holding_protection_advisor.py`, `holding_family.py`, `monthly_protection_meta_review.py`, `HoldingProtectionActions.tsx`, `PortfolioHub.tsx`, `stopManagement.ts`, `brokers/quote_time.py`; paper side: `alpaca_stop_manager.py` + `design/OCO_ATM_UNIFICATION_DESIGN.md`; runtime/lane policy: `diligence/current/LOCAL_LLM_RUNTIME_POLICY.md`; integration runbook: `runbooks/protective-stop-integration-2026-06-30.md`.

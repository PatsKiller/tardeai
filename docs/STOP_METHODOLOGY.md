# Stop & Trailing-Stop Methodology (canonical)

**Status:** Active · **Updated:** 2026-07-14 v3 (dynamic tiers + operator surfaces) · **Scope:** protective stop / trailing-stop advisories for **real-account holdings** (Schwab + Fidelity). Paper/Alpaca execution is covered separately by [`OCO_ATM_UNIFICATION_DESIGN.md`](design/OCO_ATM_UNIFICATION_DESIGN.md) and `alpaca_stop_manager.py`. **Momentum scalp paper trades** use a distinct layered policy: [`MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md`](MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md). **Click-time preflight UX** (operator choices 1A–5A): see §9 and [`runbooks/protective-stop-integration-2026-06-30.md`](runbooks/protective-stop-integration-2026-06-30.md#click-time-preflight-portfolio-ux-1a5a).

> **Advisory only.** Nothing here places, modifies, or cancels a broker order. Real-account stops are operator-placed (Fidelity manual / Schwab per-order 2FA). The engine recommends; the operator executes.

---

## 1. Engine
`scripts/holding_protection_advisor.py` produces one stop/trailing recommendation per holding. For each position it gathers **read-only** technicals (RSI14, ATR14, 20-day swing low, 50-day SMA) + the Yahoo analyst layer, then asks a free-lane LLM for a strict-JSON recommendation, validates it, and stores it to `hermes_research_intelligence` (`research_type='protection_advisory'`). Surfaced on the Portfolio cards via `/api/v2/portfolio/llm-coverage`.

## 2. How a stop is sized (the rules, in order)
1. **Tier classification** (`holding_family.classify_family`) → a per-tier **% band**. The band is the hard envelope; the swing-low anchor places the stop *within* it. Since 2026-07-14 the tiers are **config-driven** from [`config/stop_policy.yaml`](../config/stop_policy.yaml) (operator-editable, mtime hot-reload, fail-soft to the legacy built-in bands if the file is missing/invalid).

   | Tier | Stop band | Trail band | Hold style | Examples |
   |---|---|---|---|---|
   | **income_defensive** | **5–8%** | 6–8% | held through noise | SCHD, JEPI, BND, DIV, DIVI, PFLT, CSWC |
   | **growth_tech** | **8–12%** | 10–12% | growth compounder | SCHG, JEPQ, QQQ |
   | **sector_tactical** | **6–10%** | 7–10% | thesis-bound (wks–mos) | XLI, XLB (sector ETFs) |
   | **stock_core** | **7–10%** | 8–10% | high-conviction stock | V, LMT, RTX, NOC |
   | **stock_tactical** | **4–7%** | 5–7% | small/tactical (days–wks) | AVAV, KTOS, RKLB, LDOS |
   | *legacy:* momentum / swing / income / position | 2–6 / 3–8 / 4–10 / 5–12% | — | unchanged (scalp lanes + fallback) | |

   **Dynamic volatility tiers (2026-07-14.2)** — classification is data-driven, NO hardcoded symbols. `classify_volatility_tier(beta, atr_pct, div_yield_pct, sector)` (rules in `volatility_classification`):

   | Vol tier | Rule (config-driven) | Stop band | Trail band |
   |---|---|---|---|
   | **vol_low** | β ≤ 0.6, or β ≤ 0.85 with income yield ≥ 3% or ATR ≤ 1.5% | 5–8% | 6–8% (trail only ≥ +20% gain) |
   | **vol_medium** | everything else with data | 8–11% | 9–11% |
   | **vol_high** | β ≥ 1.0, ATR ≥ 3.5%, or high-vol sector with β ≥ 0.9 | 9–13% | 10–13% |

   Inputs: `ticker_enrichment_cache.json` (finviz beta/ATR$/yield/sector) + live prices. `volatility_tier_refresh.py` (cron 06:45 weekdays) writes `data/state/volatility_tiers_latest.json` + `symbol_volatility_tiers` DB table; `holding_family.volatility_tier()` prefers the state file and falls back to live cache classification. (The cache's `volatility_w_pct` column is misparsed and deliberately unused.)

   **Resolution order** (first match wins): `symbol_tier_overrides` (operator pins — EMPTY by design; mechanism kept for genuine overrides) → `bucket_map` (asset_classification_rules bucket tags; income/covered-call semantics beat raw beta) → **dynamic volatility tier** → `asset_class_map` (etf_classification_overrides) → type-aware volatility fallback (a low-ATR individual stock with no data lands in stock_core) → `default_tier` (position). Every advisory records `family`, `family_source` (e.g. `vol_tier:high β1.60`), `volatility_tier`, `regime` and the resolved `family_bounds` in `evidence_json`.

   **Regime adjustment** (`regime_adjustments`, source `market_regime_snapshots` — same as `/api/v2/risk-regime/status`): posture mapping is label-driven (`risk_on_trend`/`broad_momentum`/`low_volatility_grind` → risk-on; `risk_off`/`high_volatility` → risk-off; anything else, a stale snapshot, or a DB error → neutral, fail-soft). Risk-on widens the **vol_high trail cap only** (+1 pct-pt: room to run); risk-off tightens every stop/trail cap by 1 pct-pt. Adjustments move the cap end only, clamp at `stop_min + 0.5`, and are recorded as `regime` / `regime_adjustment_pct` in bounds provenance.

   **Conviction modifier** (`conviction_modifiers`): an individual **stock** position under $10K gets its cap tightened 1 pct-pt (small tactical ≠ conviction hold); ETFs/funds are unaffected. Recorded as `conviction_tightened_pct`.

   **Lifecycle modifier** (hermes_holdings_lifecycle): a `watch` stage shrinks the stop cap by 1 pct-pt, `trim_candidate` by 2 — biasing toward the tight end of the band. It never widens, never drops below `stop_min + 0.5`, and the applied shrink is recorded as `lifecycle_tightened_pct` in the bounds.

   **Portfolio drawdown guard** (`stop_health_check._portfolio_drawdown_guard`): portfolio value ≥10% below its 90-day peak (from `daily_system_metrics`) → warning alert; ≥12% → critical (Telegram + SIEM + Hermes, deduped 6h, symbol `PORTFOLIO`). Advisory only — it never places or modifies an order.

   > **L3 hybrid trailing stays OFF** (triple-confirmed backtest verdict) — `stop_policy.yaml` cannot re-enable it, and `tests/test_stop_policy.py` gates this.

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

Build marker: `cc-v3 stop-lifecycle-close 2026-07-01`.

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
### Drawdown treatment (2026-07-14)
Three distinct drawdown concepts, each handled explicitly:
1. **Portfolio drawdown** — `stop_health_check._portfolio_drawdown_guard()`: portfolio value vs its
   90-day peak (`daily_system_metrics`); warning ≥10%, critical ≥12% (Telegram + SIEM + Hermes,
   symbol `PORTFOLIO`, dedup 6h). Advisory alert only — it never moves a stop.
2. **P/L locked at the stop (per position)** — the drawer's comparison panel shows
   `If the current|advisory stop fills: P/L locked ±X% (now ±Y% · gives back Z% from current)`
   computed from cost basis, live price and the effective stop. This is the number that tells you
   what a refreshed stop actually protects.
3. **Drawdown-from-peak as a SIZING input — deliberately NOT used.** Give-back bounding is what
   trailing stops do; sizing stops off recent peaks is the L3 hybrid-trailing model, and it
   **failed the backtest three times** (net-negative on swing/momentum). Position P/L enters the
   methodology only through the trail-eligibility thresholds (trail on ≥+9% gains, income ≥+20%).

### Setting a TIGHTER (or any custom) stop — UI and API
**UI:** drawer → Order parameters → type the stop price (or trail %) → Apply … (2FA). Values
tighter than the tier floor show the amber out-of-band warning but are allowed — the band is
advisory; the operator decides.
**API (Schwab, same 2FA flow the UI uses):**
```
# STEP 1 — request (builds intent, runs protective gate, sends the 2FA code; places NOTHING)
curl -X POST :7777/api/v2/holdings/protective-stop -H 'Content-Type: application/json' -d '{
  "symbol":"SCHG","account":"schwab_taxable","qty":100,
  "order_kind":"STOP","stop_price":33.10,          # tighter than advisory — operator choice
  "advised_stop":31.47,"current_price":34.58,
  "quote_at":"<fresh ISO timestamp>","whole_share_confirmed":true}'
# → {mode:"awaiting_approval", intent_id}
# STEP 2 — confirm with EITHER channel (web typed-ticker + emailed 6-digit code, or Telegram)
curl -X POST :7777/api/v2/holdings/protective-stop/confirm -d '{"intent_id":"...","channel":"web",
  "ticker_confirmation":"SCHG","code":"123456"}'
```
`order_kind` also accepts `STOP_LIMIT` (+`limit_price`) and `TRAILING_STOP` (+`trail_pct`).
A stale `quote_at` is rejected (stale-quote gate); Fidelity accounts return a manual ticket
instead of a 2FA request; nothing can be placed without STEP 2.

### Operator surfaces (2026-07-14, commits da36bf72…2f63d77d)
- **VOL badges** — color-coded low/medium/high (green/amber/red) on every Holdings-table row, holdings
  card and drawer, sourced from the advisory `volatility_tier`.
- **Three-line comparison** — badges (tooltip) and the stop drawer (on-screen color-coded panel):
  `Current live stop: $X (Y% below)` / `Advisory: Widen to|Tighten to|Set A–B% trailing (based on
  TIER tier + regime, ±cap)` — verb compares the live stop distance to the advisory trail band,
  "within band" when compliant / `Minimum floor: F% (family/swing-low rule still governs final
  placement)`. One shared helper (`volTierTooltip`) drives every surface.
- **Drawer** — cells labeled **CURRENT LIVE BROKER STOP** vs **ADVISORY RECOMMENDATION** (price + %
  for both); buttons **Apply Fixed Stop (2FA)** / **Apply (Advisory) Trailing Stop (2FA)** /
  **Apply Stop-Limit (2FA)** / **Keep Current Stop**; operator-editable **order parameters** (stop $,
  limit $ — the backend accepted `limit_price` since Stage 2c but the UI never sent it — and trail %
  with tier-band hint + out-of-band amber warning; blank = advisory; `advised_stop` in the request
  always carries the PURE advisory for the audit trail).
- **Keep Current Stop** → `POST /api/v2/holdings/protective-stop/keep`: audit-only
  `stop_decisions` row (`KEEP_CURRENT`, `operator_web`, live-vs-advisory note). Never touches a
  broker order.
- **Policy migration panel** — Stop Management → Policy sub-tab: ranked divergences (stops outside
  their tier band) from `GET /api/v2/portfolio/stop-policy-migration` (disk read of
  `data/state/stop_policy_migration_latest.json`, regenerated by the 06:45 cron chain). Deliberately
  NO mass-update control (per-order 2FA rule; test-enforced).
- **Rotation surfacing** — `rotation_intelligence_engine` candidate evidence carries
  `stop_tier`/`volatility_tier` (display context only; never moves trim/add scores — test-enforced).
- Regression gates: `tests/test_stop_policy.py` (28 tests).

`holding_protection_advisor.py`, `holding_family.py`, `monthly_protection_meta_review.py`, `HoldingProtectionActions.tsx`, `PortfolioHub.tsx`, `stopManagement.ts`, `brokers/quote_time.py`; paper side: `alpaca_stop_manager.py` + `design/OCO_ATM_UNIFICATION_DESIGN.md`; runtime/lane policy: `diligence/current/LOCAL_LLM_RUNTIME_POLICY.md`; integration runbook: `runbooks/protective-stop-integration-2026-06-30.md`.

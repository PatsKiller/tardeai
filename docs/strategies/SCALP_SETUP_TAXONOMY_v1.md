# Momentum Scalp — Setup Taxonomy v1

**Status:** SHADOW / MANUAL_PAPER_TEST_ONLY. Deterministic. No order path. No LLM authority.
Additive to the existing `momentum_scalp_intraday` engine — it extends, it does not fork.

Backend source of truth: `config/scalp_setup_registry.yaml` (+ `scripts/scalp_setup_registry.py`).
The UI consumes the registry **through the API** (`/api/v3/active-trader/scalp/setups`) — rule text is
never hard-coded in React.

## Provenance vocabulary

Every rule line is tagged:

- **SOURCE-DERIVED RULE** — mechanic taken from a cited external article.
- **TRADE AI ENGINE ADAPTATION** — operator-directed adaptation the articles did not supply.
- **EXISTING ENGINE RULE** — already-shipped deterministic rule (IGN scorer / trigger FSM).
- **CONFIGURABLE THRESHOLD** — a number that lives in config, never presented as sourced.
- **UNVALIDATED HYPOTHESIS** — no Trade AI edge is claimed; article win-rates are NOT Trade AI facts.

The external articles are **educational source material, not proof of edge**. All new setups begin SHADOW.

## Three layers (never one opaque score)

1. **A. Named setup detectors** — the pattern that actually fired.
2. **B. Confirmation overlays** — evidence that supports/weakens a setup (never a fire on their own in v1).
3. **C. Universal execution-quality gate** — liquidity/spread/slippage/freshness/order-type; can veto any setup.

A **lane** (`IGN_60`, `IGN_ACCEL`, `TRIGGER`) is **not** a setup. A setup is a named, versioned, deterministic pattern.

## The 7 named setups

| setup_id | label | provenance | session · window ET | tier | one-line rule |
|---|---|---|---|---|---|
| SCALP_IGNITION_BREAKOUT_V1 | IGNITION BREAKOUT | EXISTING ENGINE RULE | REGULAR 09:30–12:00 | T0 | IGN lane crosses + trigger FSM fires |
| SCALP_L2_MOMENTUM_V1 | L2 MOMENTUM | SOURCE-DERIVED (TradeZella) | REGULAR 09:30–11:00 | **T2** | catalyst gap + early vol + book stacking + break; book flip invalidates |
| SCALP_VWAP_PULLBACK_V1 | VWAP PULLBACK | SOURCE-DERIVED (TradeZella) | REGULAR 09:45–11:30 | T0 | **continuation**: trend-side pullback to VWAP on declining vol, resume |
| SCALP_VWAP_REVERSION_V1 | VWAP REVERSION | SOURCE-DERIVED (TradeZella) | REGULAR 09:45–11:30 | T0 | **mean reversion**: stretched from VWAP + reversal toward it |
| SCALP_ORB_15_BREAKOUT_V1 | 15M ORB | SOURCE-DERIVED (TradeZella) | REGULAR 09:45–10:30 | T0 | close outside the 09:30–09:44 range + volume + market alignment |
| SCALP_MICRO_PULLBACK_V1 | MICRO PULLBACK | SOURCE-DERIVED (TradeZella) | REGULAR 09:30–11:30 | T0 | impulse → declining-vol pullback → reversal-candle high (reuses FSM) |
| SCALP_PREMARKET_MOMENTUM_V1 | PREMARKET MOMENTUM | TRADE AI ENGINE ADAPTATION | PREMARKET 07:00–09:29 | T0 | break of premarket structure on premarket VWAP/RVOL |

### The VWAP split (correctness)

The TradeZella article combines two **mechanically different** trades under "VWAP Deviation": a
pullback-to-VWAP **continuation** and a stretched **mean reversion**. They are implemented as two
separate setups (`VWAP_PULLBACK` vs `VWAP_REVERSION`) and **must never share a label**. Regular VWAP
variants do not fire before 09:45 (SOURCE-DERIVED: VWAP is still establishing in the opening 15 minutes).

### L2 MOMENTUM data honesty

Requires **actual, entitled, fresh** order-book / time-and-sales evidence. Stacking, bid-lifting, and
book-flip are **never inferred from OHLCV**. When T2 is unavailable → `setup_state = DATA_UNAVAILABLE`,
`fire = false`, `reason = L2_ENTITLEMENT_OR_BOOK_UNAVAILABLE`. (Current data plane: T2 is scaffold-only.)

### PREMARKET MOMENTUM

Uses a **separate** premarket VWAP + premarket time-of-day RVOL denominator + premarket structure.
Premarket and regular-session denominators are never mixed. Regular ORB rules do not apply before 09:30.
Fails closed to `DATA_UNAVAILABLE` until a premarket RVOL profile exists (`PREMARKET_RVOL_PROFILE_UNAVAILABLE`).

## Session model

`config/scalp_signal_engine.yaml → session` (+ `scripts/scalp_session.py`). America/New_York.

```
06:00  context collection start   (calculate; no alert/fire unless active start = 06:00)
07:00  default active fire start   (configurable to 06:00 — no code change: session.active_fire_start)
09:30  regular open
12:00  no NEW fire after noon       (existing positions still managed/journaled)
16:00  regular close
```

Phases: PREMARKET · REGULAR · POST_CUTOFF · CLOSED. `market_session` (PREMARKET/REGULAR) selects the denominators.

## B. Confirmation overlays (`config/scalp_confirmations.yaml`)

`VWAP_ALIGNED · EMA_ALIGNED · MOMENTUM_ALIGNED · MARKET_ALIGNED · L2_CONFIRMED · SUPPORT_RESISTANCE_REACTION`
(directional) + `CATALYST_CONFIRMED · VOLUME_CONFIRMED` + `ONE_MIN_CONFLUENCE`.

- Indicator periods (EMA/RSI/MACD) are **CONFIGURABLE THRESHOLDs** — the Kotak source specified none; they
  are documented as TRADE AI ENGINE ADAPTATION, not invented as sourced.
- Indicator **count alone never overrides a failed setup**.
- `ONE_MIN_CONFLUENCE` can **never authorize a fire by itself in v1** (`authorizes_fire: false`).

## C. Universal execution-quality gate (`config/scalp_confirmations.yaml → gate`)

Applied to **every** setup; can veto any. Bullish Bears material is INPUT here, never a setup. Checks:
freshness, min volume, min dollar-volume rate, max spread (bps), max expected slippage (bps), participation,
halt, entitlement, limit-price feasibility. Canonical outputs: `LIQUIDITY_SPREAD_PASS/FAIL`,
`SPREAD_TOO_WIDE`, `EXPECTED_SLIPPAGE_TOO_HIGH`, `INSUFFICIENT_VOLUME`, `PARTICIPATION_TOO_HIGH`,
`DATA_STALE`, `HALTED`, `PRICE_CONTROL_UNAVAILABLE`. **Never auto-markets** — `price_control.method = LIMIT`.

## FIRED definition

`FIRED` = all mandatory deterministic criteria true, on a closed bar / valid book event, **inside the
setup-specific window**, **with the universal execution gate passing**. A partial match is `ARMED`, never
`FIRED`. Multiple setups may match; all matches are retained; a deterministic PRIMARY is chosen
(tier specificity → mandatory-criteria count → family rank → version → id).

## Authority (hard invariants)

No AUTO_PAPER. No automatic/scheduled/agent/model order submission. No live account/adapter/2FA/credential.
The engine may compute, display, alert, journal, and prepare a **manual** paper ticket — it may not submit
any paper or live order. No LLM determines setup truth, arithmetic, risk, sizing, order type, or submission.

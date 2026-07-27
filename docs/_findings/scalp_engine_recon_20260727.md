# Momentum Scalp Signal Engine — M3-S0 Recon Findings (2026-07-27)

**Scope:** S0 diagnostic ONLY. No code written, nothing changed. Read-only DB queries + code
search. Confirms/corrects every `[VERIFY]` in `docs/strategies/MOMENTUM_SCALP_SIGNAL_ENGINE_v1.md`.
**Tree:** `main @ 4445b5d2` · **IRON RULE:** ✅ holdings.json `total_value=$1,253,766`, 33 holdings.
**Rule applied:** where live schema contradicts the design doc, **the live schema wins** (noted inline).

---

## Executive summary — the two flag-backs and their resolution

| # | Issue | Status |
|---|---|---|
| **FB-1** | Design doc `MOMENTUM_SCALP_SIGNAL_ENGINE_v1.md` did not exist in the repo | **RESOLVED** — operator provided it; saved to `docs/strategies/`. It is a v1 DRAFT ("nothing built or approved"), staged M3-S0…S10. |
| **FB-2** | **No 20-session 1m bar history exists, and none obtainable from yfinance** (hard ~7-day cap). `market_ohlcv_bars` 1m ingest died 2026-05-07. RVOL_tod core unbuildable as-was. | **RESOLVED (path decided)** — operator chose **Alpaca minute bars**. Verified live: Alpaca `/v2/stocks/{sym}/bars?timeframe=1Min` returns **19 full sessions over a 25-day window** with existing keys → a ~28-day query backfills the 20-session profile **immediately**. |

**Bonus resolution — the doc's own "single highest-impact unknown" (§14 Q2):** Alpaca **SIP feed
is entitled** (a `feed=sip` bars call returns full consolidated bars incl. extended hours). So the
later T1 microstructure work (Lee-Ready TFI, effective spread) runs on consolidated data, not a
~2% IEX sample. IEX also works and is sufficient for `RVOL_tod` (a same-feed ratio cancels venue-share bias).

**Overlap warning (HARD CONSTRAINT #6):** substantial existing capability. VWAP, ATR, EMA, MACD,
opening-range, alert dispatch, halt detection, and a scalp-signal scout **already exist** — reuse,
do not reimplement. Details in §S0.2.

---

## S0.1 — Bar data reality

`market_ohlcv_bars` **exists**. DDL: `(id int, symbol text, timeframe text, bar_time timestamptz,
open/high/low/close/volume numeric, source text, created_at timestamptz)`, unique on
`(symbol, timeframe, bar_time)`, `source ~ yfinance`.

**Live coverage (as of 2026-07-27):**

| timeframe | rows | symbols | span | last bar | live? |
|---|---|---|---|---|---|
| `1h` | 106,828 | 58 | 2025-10-31 → 2026-07-27 | today 12:30 | ✅ active |
| `15m` | 70,742 | 45 | 2026-04-27 → 2026-07-27 | today 13:00 | ✅ active |
| `daily` | 35,731 | 89 | 2024-07-22 → 2026-07-24 | 07-24 | ✅ active |
| `5m` | 38,654 | 9 | 2026-02-11 → 2026-05-07 | **2026-05-07** | ❌ dead |
| `1m` | 16,364 | **9** | 2026-04-29 → **2026-05-07** | **2026-05-07** | ❌ dead |

- **1m: 9 symbols, ~7 days, ~3 months stale. Zero symbols have any 1m bar in the last 40 days.**
- Root cause: the loader (`scripts/market_data_snapshot_loader.py`) pulls yfinance 1m with
  `period=5d, max_days=7` — **yfinance hard-caps 1m history at ~7 days**, so it can *never* yield
  20 sessions, and it only ran on-demand for pending proposals. `trade_intrabar_bars` (per-trade
  capture) is also thin (5m/16 syms, 1m/2 rows). No deep minute store anywhere.
- Ingest cadence/lag (live tf): 15m/1h refreshed intraday, last-bar → last-ingest lag ~6s (fresh).

**→ FLAG-BACK FB-2 fired and is answered by the Alpaca path (verified, see summary).** yfinance is
NOT a viable 1m source; do not substitute daily bars. Alpaca 1Min backfill makes M3-S1 buildable now.

**Decision needed (minor):** IEX vs SIP as the *profile source*. IEX = correct RVOL_tod ratios,
free, venue-partial volume. SIP = true consolidated volume (needed for `v_liq` $-volume), entitled,
more API calls + pagination. Recommend **SIP for the profile** (true volume), IEX fallback on rate-limit.

---

## S0.2 — What already exists (reuse, do not duplicate)

| Capability | Exists? | Where | Note |
|---|---|---|---|
| **VWAP (intraday)** | ✅ | `scripts/compute_intraday_vwap.py:36` (true session VWAP from 5m yf bars, cached `data/state/intraday_vwap_cache.json`, cron 20m); also `pullback_macd_screener.py:219` `_session_vwap` | `indicator_engine.py:387` is a *daily* rolling approximation — NOT intraday; don't use it for scalp |
| **ATR** | ✅ | `indicator_engine.py:536` `_compute_atr` (period **14**, `ta.atr`, **daily** bars); primitive `pandas_ta_shim.py:60` | No 1m ATR exists yet — S1 needs `ATR_1m`; must feed the shim minute bars |
| **EMA** | ✅ | `proposal_technical_snapshot.py:98` `compute_emas_from_bars` (8/21/50/200 from daily `market_ohlcv_bars`) | doc's guessed name is CORRECT |
| **MACD** | ✅ | `indicator_engine.py:214` `_compute_macd` (12/26/9, daily); `pandas_ta_shim.py:64`; `pullback_macd_screener.py` | For §6.1's 5m regime filter, reuse the shim on 5m bars |
| **Opening range / premarket** | ✅ | `scripts/opening_range_engine.py` (ORB 5/15/30m + premarket from 1m→5m fallback `market_ohlcv_bars`) | doc guess CORRECT; note it depends on 1m bars that are currently dead — Alpaca feed revives it too |
| **RVOL** | ✅ but Finviz-sourced | `finviz_enrichment.py:509` `get_rvol`, `premarket_rvol.py` (vol/avg_vol) | **No bar-cumulative minute-of-day RVOL engine exists** — this is exactly the §3.1 gap S1 fills; not a duplicate |
| **alert_dispatcher** | ✅ | `scripts/alert_dispatcher.py` | `dispatch_alert(alert_type,title,body,tier=,symbol=,source=,dedupe_scope=,force=)`; tiers `INFO/ALERT/URGENT/DIGEST/DASHBOARD_ONLY`; dedupe key `{date}:{type}:{symbol}`; rate-limit `MAX_TELEGRAM_PER_HOUR=15` (env), fatigue after 3d. **Also `alert_dispatcher_unified.py` exists — diff before wiring.** |
| **Ignition scorer / trigger state machine** | ❌ NOT FOUND | — | No IMPULSE/PULLBACK/ARMED/TRIGGERED intraday engine. `portfolio_stops.py` has `TRIGGERED` for *stop* surveillance (unrelated). **This is genuinely new — build it.** |
| **hermes_scalp_signal_scout** | ✅ (adjacent) | `scripts/hermes_scalp_signal_scout.py` | Reads `scalp_scan_results`/`trade_ai_scans` + `momentum_scalp.yaml`; conviction score (base 40 + rvol/catalyst bonuses); writes `qualified_signals.json`. Scores *scan* signals; does NOT compute minute-bar entry triggers. Different job from the S1 engine — but the universe/handoff should be reconciled (see decisions). |
| **scalp_live_signals.json** | ✅ | writer `scalp_ws_client.py:20` (ringbuffer, cap 50, `{timestamp,data}`); reader `api_v2.py:16346` `_scalp_live_poll` (WS 7778/7779, HTTP fallback) | Existing dashboard signal feed — the S1 read-only dashboard (Step 8) can follow this pattern |

---

## S0.3 — Schema collision check

- `scalp_ignition_events`, `scalp_trigger_fires`, `symbol_volume_profile` — **none exist. No collision.**
- Existing `scalp_*` tables: `scalp_decision_outcomes`, `scalp_scan_results` → the `scalp_*` naming
  convention is established; the doc's proposed names fit house style. ✅
- **Total public tables: 658** (design doc guessed "334+" — corrected UP).
- **Migration mechanism:** no alembic. Two house patterns coexist: (a) dated raw SQL in
  `migrations/` (`YYYY-MM-DD_name.sql`), and (b) python `scripts/create_*_schema.py` /
  `scripts/migrate_*.py`. Recommend a dated `migrations/2026-..._scalp_signal_engine.sql` +/or a
  `create_scalp_engine_schema.py` mirroring existing `create_*_schema.py` scripts.

---

## S0.4 — Scheduling and process reality

- `continuous_runner.py`: time-of-day `SCHEDULE` with `_current_interval()` (10–15 min cycles,
  ~04:00–11:00), main loop `time.sleep(wait*60)`. Launched by **systemd**:
  `tradeai-continuous.service` + `tradeai-continuous.timer` (timer active, service timer-launched).
- Many `systemd --user` timers exist (e.g. `hermes-momentum-catalyst-morning.timer`). Locking:
  `scripts/safe_flock.sh` (flock wrapper) is the house convention for scheduled jobs.
- **Where a sub-minute-cadence intraday job lives:** a dedicated `systemd --user` service with an
  internal loop (continuous_runner pattern) + `safe_flock` is the fit. A `*/1` cron is possible but
  the house lean is systemd for anything looping. **Decision on exact cadence deferred (see below).**

---

## S0.5 — Deterministic-signal feasibility

- **Prior close per symbol intraday:** available but DERIVED, not a clean reference-price store —
  `portfolio_repricer.py:160` (`price/(1+change/100)`), stored `prev_close` in
  `aegis_nightly_ingestion.py`/`ticker_snapshot_builder.py`, `opening_intelligence.py` for gaps.
  Alpaca daily bars give a clean prior close too. **Good enough for gap math; usable for a LULD
  reference price but NOT an official SSR/LULD band.**
- **Halt state:** ✅ `scripts/halt_detector.py` (NASDAQ halt CSV + Polygon zero-volume + catalyst
  keywords; per-ticker status; wired via `trade_ai_orchestrator.py:533`). LULD appears only as halt
  *reason codes* (`LUDP`/`LUDS`), **no LULD price-band computation**.
- **SSR / Reg SHO:** ❌ NOT tracked anywhere (only Finviz `short_float_pct` = short interest, not SSR).
- **Consolidated vs venue volume:** SIP (consolidated) **is available** via Alpaca (verified) — so
  §6.2 VenueShare is no longer forced to defer to moomoo; consolidated volume is queryable now.

**→ Design-doc consequence:** §3.2 `luld_headroom_pct`/`ssr_active` cannot be computed from an
official band today. Per the doc/prompt: **write NULL + flag, do not approximate the LULD reference
price.** Halt handling (§5.3) can use the existing `halt_detector`.

---

## S0.6 — Config decisions requiring the operator (live values)

`config/strategies/momentum_scalp.yaml` (the LIVE file):

| Field | Live value | Doc/playbook guess | Contradiction? |
|---|---|---|---|
| `max_float_m` | **20** (`preferred: 10`) | doc §9 said YAML=100 / pref 20 | ✅ doc STALE — live is already 20. Operator wants **30M** for the new key → still a 3-way decision (30 vs 20 vs inherit). |
| stop cap | disqualifier `STOP_OVER_15_PCT` (**stop_pct > 0.15 = 15%**) | playbook says **8%** cap; §6 uses 8% reject | ✅ real contradiction — 8% (design/playbook) vs 15% (live YAML). **Operator must pick one for the new key.** |
| `min_rvol` | 5.0 (`premium: 8.0`) | matches | — |
| `min_gap_pct` | 5.0 | matches | — |
| `min_price` / `max_price` | 1.0 / 25.0 (`preferred_max: 10`) | matches | — |

Per design §9 + guardrail #8: set these on the **new `momentum_scalp_intraday` key only**; leave
`momentum_scalp` untouched (it has a live review gate that a mid-flight universe change would corrupt).

---

## Open decisions before any M3-S1 code (operator/architect)

1. **Float band** for `momentum_scalp_intraday`: **30M** (operator stated) vs 20M (live) vs inherit? (doc §9 / §14 Q4)
2. **Stop cap:** **8%** (design/playbook) vs 15% (live YAML)? (doc §6)
3. **Universe:** inherit the existing scalp universe (from `scalp_scan_results` / hermes scout) or a new float≤band screener? (doc §14 Q4)
4. **Intraday cadence** for the shadow engine (e.g. every 60s during RTH) + systemd vs cron.
5. **Profile source:** SIP (true volume) vs IEX (free, ratio-correct) — recommend SIP.
6. **Premarket window** in v1 (doc §14 Q5) — author lean: log, don't trigger.
7. **Scope confirmation:** the execution prompt's "S0+S1" maps to the doc's **M3-S0 (done here)
   + M3-S1 (volume profile only)**. The doc also gates implementation on **"architects annotate
   v1 → v2 sign-off"**. Confirm S1 (volume profile builder) is authorized to start, or hold for v2 doc sign-off.

---

## S0 EXIT — status

Findings written · all FLAG-BACKs surfaced + resolved-in-principle · design doc saved · **no code
written.** Awaiting operator sign-off on the decisions above before M3-S1 (volume profile builder).
Per HARD CONSTRAINT and the doc's own review gate, not proceeding to S1 code in this session without
explicit go-ahead.

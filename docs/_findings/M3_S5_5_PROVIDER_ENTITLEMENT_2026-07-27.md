# M3-S5.5 — Provider Entitlement Proof & Observation Fabric (2026-07-27)

Status:      HISTORICAL
as_of:       2026-07-27T18:39:56-04:00
Measured at: efcc51365 / not measured

**Stage:** M3-S5.5 preparation (multi-source observation fabric + entitlement proof). **Shadow-only.**
No execution, no order path, no proposals, engine flag OFF, `multi_source.enabled` OFF.
**Base:** origin/main `392d9957` (= the prompt's `fa0ec680` M3-S5 + doc-only PR #231 which added the
phase-plan Status column; based on the newer commit to avoid a phase-doc conflict).
**IRON RULE:** not a deploy/extraction; no state mutation. Probes were bounded read-only market-data GETs.

---

## Alpaca T1 classification → `T1_IEX_ONLY`

Bounded read-only probes (1 symbol AAPL, one `…/latest` request per feed per type, market open, real
`data_ts` ~20:00 UTC; **no key/token/header printed**):

| type | IEX (real-time) | SIP (consolidated real-time) |
|---|---|---|
| bars `/bars/latest` | **200** (data_ts 19:59Z) | **403** "subscription does not permit querying recent SIP data" |
| trades `/trades/latest` | **200** (19:59:59Z) | **403** |
| quotes/NBBO `/quotes/latest` | **200** (20:00:02Z) | **403** |

**Resolution of the S0 contradiction:** S0 reported "SIP entitled" — that was **historical/delayed** SIP
only. **Real-time (recent) SIP returns 403 for bars, trades, AND quotes.** Real-time trades + NBBO
*do* exist, but **IEX-only** (a single venue, ~2-3% of consolidated volume) — NOT consolidated SIP.

→ **`T1_IEX_ONLY`.** Real-time consolidated (SIP) trades/NBBO are **UNAVAILABLE** on this subscription.
Per the stage rule: **do NOT implement Lee–Ready TFI, effective spread, Kyle's λ, or VPIN in M3-S6** —
computed on IEX-only flow they would be a ~2-3% sample, plausibly weaker than the T0 `BarPressure`
fallback (design §14 Q2). **M3-S6 must not begin until an eligible real-time consolidated source exists.**

---

## Provider capability matrix (evidence-based)

States: `AVAILABLE_REALTIME · AVAILABLE_DELAYED · AVAILABLE_HISTORICAL · IEX_ONLY · SIP_REALTIME ·
SIP_DELAYED · SCAFFOLD_ONLY · UNAVAILABLE · UNRESOLVED`.

| capability | **Alpaca** | **Yahoo** | **Schwab** | **Moomoo** |
|---|---|---|---|---|
| historical bars | AVAILABLE_HISTORICAL (both feeds) | AVAILABLE_HISTORICAL (daily/5m/15m) | AVAILABLE_HISTORICAL (`get_price_history`) | SCAFFOLD_ONLY |
| current bars | **IEX_ONLY** (SIP delayed) | AVAILABLE_DELAYED; **1m capped ~7d → UNSUITABLE** for 20-session profile | AVAILABLE_HISTORICAL (chart fallback) | SCAFFOLD_ONLY |
| trades / T&S | **IEX_ONLY** (venue-partial); only `/trades/latest` used today, no tape | UNAVAILABLE | UNAVAILABLE | SCAFFOLD_ONLY |
| bid/ask / NBBO | **IEX_ONLY** (venue-partial); **zero current callers** | AVAILABLE_DELAYED (context) | AVAILABLE_REALTIME (`get_quote` — cross-check only) | SCAFFOLD_ONLY |
| Level 2 / depth | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | SCAFFOLD_ONLY (intended T2) |
| extended hours | via SIP bars (delayed) | limited | — | SCAFFOLD_ONLY |
| provider timestamp | yes (`t`) | yes | yes | n/a |
| sequence id | no | no | no | intended (T2 gateway) |
| account | AVAILABLE_REALTIME (own) | UNAVAILABLE | AVAILABLE_REALTIME (own, managed tokens) | SCAFFOLD_ONLY |
| position | AVAILABLE_REALTIME (own) | UNAVAILABLE | AVAILABLE_REALTIME (own) | SCAFFOLD_ONLY |
| order | AVAILABLE_REALTIME (own) | UNAVAILABLE | AVAILABLE_REALTIME (own); **electronic-entry eligibility UNRESOLVED** | SCAFFOLD_ONLY |

**Roles:**
- **Alpaca** — current T0 primary (IEX 1m bars). Real-time trades/NBBO IEX-only → T1_venue, not T1.
- **Yahoo** — historical/reference & degraded fallback only. 1m unusable for the profile. Never broker truth.
- **Schwab** — authoritative for **Schwab** account/position/order (via managed-token `schwab_transport.py`,
  NOT the racy `SchwabAdapter`, which is on no quote path). Quotes = cross-check, must not override fresher
  consolidated data. **Electronic-entry / broker-restriction eligibility is not surfaced by any adapter
  today → UNRESOLVED** (exists only as product intent in the Active Trader Stage-0 baseline).
- **Moomoo** — **`SCAFFOLD_ONLY`.** OpenD is not configured on this host (example config only, health
  registry empty). Intended T2 (real-time quotes/tape/order-book/depth) but unproven; requires an actual
  gateway + entitlement + sequence/freshness contracts, and consumers must go through the Stage-0 client
  boundary, never a direct OpenD connection.

**Moomoo T2 state → `SCAFFOLD_ONLY`. Current selected T0 source → Alpaca IEX 1-minute bars.**

---

## Observation contract (aligned to house §5.2)

`scripts/market_observations/observation.py` — immutable `Observation` carrying the exact architecture
v3.3 §5.2 envelope fields (`source_system, source_record_id, symbol_or_entity, observed_at, provider_at,
received_at, normalized_at, source_version, source_hash, quality_state, freshness_state,
entitlement_state, sequence_id, payload_ref`; `to_house_envelope()` emits them verbatim). Provenance maps
to the §15.7 control tables (`md_entitlement_state`, `md_data_quality`, `md_feature_snapshot`,
`md_sequence_gap`) — **those tables are NOT created or written by this shadow stage.** Market-signal
observation types (bar/quote/trade/order_book) and broker-state types (account/position/order) are
partitioned; **broker-state observations may never be consumed as market-signal scoring inputs** (tested).

---

## Bounded concurrency (`concurrency.py`)

Global cap **8**; per-provider caps **alpaca 4 · yahoo 2 · schwab 2 · moomoo 1** (single gateway owner).
Task timeout 10s; bounded retries (max 2) with jitter, **never retried on auth/entitlement rejection**;
per-provider circuit breaker (threshold 3); deterministic result ordering (aligned to input order);
per-provider latency/success/timeout/throttle/breaker counters. **No one-thread-per-symbol.** Tested:
cap never exceeded, timeout isolation, no-retry-on-auth, deterministic ordering, breaker opens+skips.

## Source-conflict policy (`arbitration.py`, `source-authority-v1`)

Deterministic, **never averages**. Fresh beats stale; delayed can't replace real-time without a **visible
tier downgrade**; IEX quotes/trades are labeled **T1_venue**, never consolidated T1/SIP; RVOL numerator &
denominator **must share a feed** (`require_feed_match` raises otherwise); two fresh eligible sources
disagreeing > 50 bps → **`SOURCE_CONFLICT`** → directive `lower_dcf_or_block_gate` (never a silent pick);
**source availability can never raise a score or pass a failing trigger** (arbitration only selects the
canonical observation; IGN/trigger formulas untouched). Brokers authoritative only for their own resources.

## Shadow integration

Behind `multi_source.enabled: false` (HARD default off). Flag OFF → `acquire_bar_snapshot()` returns `{}`
and the existing single-source T0 path is used unchanged (tested reproducible). Flag ON (tests/dry-run) →
concurrent acquire → normalize → deterministic arbitration → canonical snapshot + provenance; **does not
enable T1/T2 because adapters exist; does not change IGN or trigger formulas.**

---

## S5 trigger-R quality diagnostics (measurement only — NO threshold change)

`scripts/scalp_trigger_r_diagnostics.py` over the 6 live `TRIGGER` rows (assumed slippage 40 bps @ T0).
The 0/6-hit finding is explained quantitatively — **R is routinely too small to be tradeable:**

| dimension | all (n=6) | proxy (n=2) |
|---|---|---|
| R (bps) median | 23.9 | 25.4 |
| **slippage / R** median · **max** | **1.69 · 77.8** | 1.61 · 1.87 |
| tick / R median · max | 0.28 · **2.33** | 0.28 · 0.33 |
| spread / R median | 0.10 | 0.08 |
| **R < 1 tick** | **2 / 6** | 0 / 2 |
| R < 4 ticks | 3 / 6 | 1 / 2 |

**Read:** for several triggers a single $0.01 tick exceeds the whole R (tick/R up to 2.3×), and the
assumed T0 slippage is a **median 1.7× and up to 78× the entire R** — the edge is gone before direction
matters. ATR-floor binding rate is now instrumented (`gate_reasons.floor_bound`) and accrues on new fires
(legacy rows lack it). **Do NOT add a minimum-R filter yet** — accrue the §12 sample (≥100 fires / ≥15
sessions), keep cohorts separate, and let the evidence drive the operator decision.

---

## First blocker (resolved by this stage's evidence)

Missing canonical multi-source truth + entitlement proof — now proven: real-time T0 = Alpaca IEX;
Yahoo 1m unsuitable; Schwab not connected to this engine (authoritative only for Schwab facts, eligibility
UNRESOLVED); Moomoo SCAFFOLD_ONLY; **Alpaca real-time consolidated trades/NBBO do NOT exist (T1_IEX_ONLY)**;
acquisition is now bounded-concurrent with deterministic provenance/arbitration behind a default-off flag.

## Open decisions / not started (surfaced, not resolved)

- **M3-S6 gating:** with `T1_IEX_ONLY`, real-time consolidated microstructure is unavailable. Options for
  the operator: (a) hold M3-S6 until a consolidated feed (paid Alpaca SIP real-time / Polygon / Moomoo T2)
  exists; (b) build IEX-only T1_venue metrics as a *labeled, degraded* experiment; (c) skip to Moomoo T2.
- **Min-R:** the R-quality evidence is strong but the sample is 6 — hold for the §12 gate.
- Moomoo T2 requires OpenD config + entitlement + sequence/freshness contracts before any T2 claim.

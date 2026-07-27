# GATES CLEAR WITH CORRECTIONS

**Stage:** M3-S2.5 gate clearance · **Date:** 2026-07-27 · **Tree:** `main` (post-M3-S3)
**IRON RULE:** ✅ `holdings.total_value = 1,254,050.06`, 33 holdings (non-zero).

> **Ordering note (surfaced + operator-ruled before work began):** this prompt was written to gate
> M3-S3, but M3-S3 had already shipped this session (PR #227, `7043d5da`) on an explicit "authorize
> M3-S3" — `scalp_ignition_events` exists with 208 logged rows and the shadow cron is live. Operator
> ruled: **adapt** (gates may touch merged S1/S2/S3) and **keep the design-doc tier numbering**
> (T0=bars). Several prompt premises were overtaken by S3's existence; each is noted at its gate.

---

## Enumerated answers

- **G3 → `INCLUDES_SAME_DAY`.** The builder's `end = datetime.now(timezone.utc).date()`; at the 20:30
  ET cron time the UTC clock is already `00:30` the next day, so `.date()` = D+1 and the fetch window
  covers session D (D 13:30–20:00 UTC < D+1 00:00 UTC). Holds across DST (EDT 20:30→00:30 UTC,
  EST 20:30→01:30 UTC — both past UTC midnight). The profile also does **not** depend on the local
  `market_ohlcv_bars` ingest at all — it pulls directly from Alpaca historical bars, so the
  "races-with-ingest" premise does not apply.
- **G5.1 → `CITATION_RETROFITTED`.** `docs/strategies/MOMENTUM_SCALP_SIGNAL_ENGINE_v1.md` has exactly
  one in-repo commit (`0aa7fc4e`, PR #225) and Abdi–Ranaldo was already present in §4.3 there (3
  mentions). No prior in-repo Roll revision exists to diff. The doc entered the repo with AR already
  cited; the operator's "design specifies Roll" refers to a pre-repo/mental version. CHANGE LOG added
  to the design doc (§16).

---

## G1 — Volume profile curve verification `[LOAD-BEARING]` — PASS

Diagnostic run inline against `symbol_volume_profile` (3 symbols across the liquidity range by median
full-session cumulative volume at minute 389):

| symbol | tier | n_sessions | cumulative monotonic? | violations | open/trough | close/trough | U-shape |
|---|---|---|---|---|---|---|---|
| SOFI | large | 20 | **True** | 0 | 2.6× | 3.3× | ✅ |
| AVAV | mid | 20 | **True** | 0 | 64.5× | 280× | ✅ |
| BIRD | thin | 17 | **True** | 0 | inf (trough=0) | inf (trough=0) | ✅* |

**Cumulative monotonic non-decreasing for all three, zero violations — G1 passes, no flag-back.**
U-shape confirmed. *BIRD caveat: the thinnest micro-floats have **zero** IEX incremental volume midday
(open=0, close=14/min) — the per-symbol profile is near-degenerate. Not a monotonicity defect; a
data-sparsity artifact of IEX on micro-floats → exactly the §3.1 universe-proxy-fallback population.

## G2 — Profile freshness contract — CLEARED (accessor added)

**G2.1 diagnosis.** `symbol_volume_profile` DDL columns: `id, symbol, session_window,
minute_of_session, median_cum_volume, median_incr_volume, n_sessions, feed, lookback_sessions,
built_at`. `built_at` (timestamptz) already records build time; `n_sessions` populated for all 42
symbols (dist: 20×34, 19×2, 18×1, 17×2, 15×3). **No TTL/staleness column exists** (confirmed). The
"42 vs 39" is **not stale orphans** — it is `AAPL/SOFI/PLTR`, the liquid spot-check symbols built
during M3-S1 verification, which are outside the 39-symbol universe. The builder upserts
(`ON CONFLICT (symbol,session_window,feed,minute_of_session) DO UPDATE`, builder.py:232) and never
deletes, so a symbol that drops out of the universe is **orphaned** (retained, goes stale) — hence the
freshness contract below is required. **The 3 rows were NOT deleted (operator call).**

**G2.2 contract implemented.** `symbol_volume_profile_builder.py`:
`get_profile_denominator(conn, symbol, minute, cfg, now, raise_on_refuse=False)` returns
`(median_cum_volume, meta)` or `(None, meta)` and **refuses** (None, or raises `ProfileUnavailable`)
when the row is absent, `n_sessions < min_sessions` (config, 15), or the profile is older than
`max_profile_age_sessions` (config, **new key, 3**) trading sessions (`trading_sessions_between`
counts weekdays). **Wired into the S3 shadow logger** (replaces the raw read). Thresholds are config,
not hardcoded. **Tests: 7 (incl. fresh/stale/under-populated/absent + raise-mode), all pass.**

## G3 — Cron / ingest — `INCLUDES_SAME_DAY` (see enumerated answers). No reschedule performed.

`timedatectl` = `America/New_York (EDT −0400)`. Cron: `30 20 * * 1-5 … run_scalp_volume_profile_refresh.sh
… logs/scalp_volume_profile.log`. First nightly run has not fired yet (installed today). No fix needed.

## G4 — Data-tier ladder invariant `[LOAD-BEARING]` — CLEARED (route: keep design-doc numbering)

**The functional risk-inversion the gate warns about does not exist in live config.** The prompt
assumed bar-only "T0" carries a 1.00× multiplier; the design-doc convention (operator-provided) numbers
**T0=bars=weakest**, and live config already assigns it the **lowest** DCF (0.40). The issue was
labeling convention only, not risk. **Operator route: keep T0=bars (no rename, no row migration).**

Added to config `data_tiers`: `quality_order: [T2,T1,T0]` (best→worst) and
`assumed_slippage_bps: {T2:8, T1:20, T0:40}`, alongside existing `dcf: {T2:1.00, T1:0.70, T0:0.40}`.
**G4.3 invariant test** `tests/test_scalp_data_tier_invariant.py` reads live config and asserts: along
`quality_order`, `dcf` is non-increasing and `assumed_slippage_bps` is non-decreasing, and the worst
tier never holds the top multiplier. **4 tests, wired into the suite, passing.**

## G5 — Provenance reconciliation — DONE

- **G5.1** `CITATION_RETROFITTED` (above). CHANGE LOG added to design doc §16.
- **G5.2** EvR documented as diagnostic-only in `scalp_t0_metrics.py` (module docstring) and design
  doc §16. **grep: no EvR/effort weight anywhere in `config/scalp_signal_engine.yaml`** (confirmed).
- **G5.3** canonical cohort table below.

### G5.3 — Canonical cohort table (with queries)

| cohort | count | query |
|---|---|---|
| total scalp universe (float_mm≤30, 21d) | **72** | `SELECT count(DISTINCT symbol) FROM scalp_scan_results WHERE scanned_at > now()-interval '21 days' AND (float_mm IS NULL OR float_mm<=30)` |
| profiled (usable `symbol_volume_profile`, n_sessions≥15) | **39** | universe ⋈ `(SELECT DISTINCT symbol FROM symbol_volume_profile WHERE feed='iex' AND n_sessions>=15)` |
| uncovered | **33** | 72 − 39 |
| ├─ proxy-eligible (had partial IEX bars) | **27** | 33 − 6 (skipped-with-partial-sessions from the build log) |
| └─ genuinely uncoverable (0 close-spanning IEX sessions) | **6** | build-log entries `SKIP (only 0 … sessions)` |

**Standing caveat (verbatim in substance):** *the covered cohort skews seasoned and more liquid; the
uncovered cohort skews new and thin, which is the population this strategy targets. Precision@1R
measured on the covered cohort is not directly generalizable to the deployed population. Cohorts are
reported separately and never pooled.*

## G6 — Split `max(CS,AR)` by consumer — DONE

`scalp_t0_metrics.py`: `spread_estimate_gate` (max — upward bias is risk-safe: wider spread → tighter
size) for the risk/sizing consumer; `spread_estimate_score` (median — unbiased) for the future scorer.
Each documents *why*. `spread_estimate` kept as a deprecated alias → gate (the shadow logger records the
conservative value). Single-estimator and equal-estimator cases handled. **5 tests, passing.**

---

## Full test run

`92 passed` — `tests/test_symbol_volume_profile_builder.py` (12 + 7 G2.2) ·
`tests/test_scalp_t0_metrics.py` (26 + 5 G6) · `tests/test_scalp_ignition_scorer.py` (38) ·
`tests/test_scalp_data_tier_invariant.py` (4 G4.3). Engine flag `enabled: false` unchanged.

## Open operator decisions

1. **The 3 orphan-prone rows (AAPL/SOFI/PLTR).** Not deleted. Options: (a) leave — the new freshness
   accessor now **refuses** them once they age past 3 sessions, so they cannot silently poison a
   denominator (self-healing; my recommendation); (b) delete them; (c) add them to a permanent
   "reference symbols" set the nightly refresh keeps current. Your call.
2. **G3:** no action required (`INCLUDES_SAME_DAY`).
3. **G4 route:** resolved (keep design-doc numbering) — noted for the record.

## INCIDENTAL OBSERVATIONS (not fixed)

- **Proxy ADV is circular.** The S3 shadow logger's universe-proxy path currently derives ADV_20d as
  `profile_cum / ExpectedFraction` — which is unavailable exactly for the symbols that need the proxy
  (no profile). A real ADV_20d source (Alpaca daily bars) is needed in M3-S3-proper for the 27
  proxy-eligible names. Logged, not fixed (out of this stage's scope).
- **v_cat age is approximate.** Catalyst age uses `scalp_scan_results.scanned_at`, not the true
  news-break time; v_cat is therefore a rough prior in shadow. Acceptable pre-refit; note for M3-S8.
- **Thinnest micro-floats are near-empty on IEX** (BIRD: open=0). SIP has the volume but is
  delayed-only on this subscription; these names may never get a real-time per-symbol profile without
  a paid feed — the proxy fallback is load-bearing for them.
- **AST isolation test (Step-7) still owed.** Isolation was verified this session by import inspection
  (all 4 engine modules import zero proposal/order paths); the formal two-pass AST test (import nodes,
  then string literals with docstrings excluded) remains a deliverable for the S3 hardening.

## Recommended next stage

**Proceed to M3-S4 (outcome backfill + dashboard)** — operator already indicated it. M3-S3 is live and
the shadow clock is running (6am–noon cron); M3-S4 makes that accruing data evaluable (MFE/MAE,
`hit_1r_first`, P@1R by IGN decile, reported per-cohort never pooled). Recommend also folding the four
INCIDENTAL items into the M3-S4/hardening scope: a real ADV_20d source for the proxy, and the AST
isolation test. Do **not** refit any weight until ≥ the sample gate (§12) is met on a held-out split.

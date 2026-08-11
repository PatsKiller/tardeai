# S6 Report — Advisory Desk v1

**Branch:** `feature/advisory-desk-v1`
**Commit:** `da38ad64` on `origin/feature/advisory-desk-v1`
**Date:** 2026-08-10

---

## TRACK A — Data Truth

### A1: Lot Reconstruction

| Metric | Value |
|---|---|
| Positions reconstructed from broker transactions | 19 of 25 |
| No transaction data available | 4 (3 CUSIPs + SRNE) |
| UNTRUSTED (shares mismatch >5%) | 2 (AMANX at 19.4×, V sold down) |
| Basis change >5% after rebuild | 3 positions |
| SPCX lots rebuilt | 10 lots (from 2 phantom) |
| Invariant violations after rebuild | **0** |
| Plausibility gate | **PASS** |

Verdicts did **not** flip — the desk was already producing HOLD on small fractional-share positions and TRIM on SPCX. The inflated basis from phantom lots in `tax_lots.json` had been masking in `gain_loss_pct` (which the desk reads from `holdings.json`), not in `cost_basis_per_share` (which the desk computes from lots). The rebuild improved accuracy without changing verdicts.

### A2: Price-Action Gap

Fixed. Evidence bundle now includes price action if **any** window is populated (was: required 1d). SPCX rollover rationale:

> "The price action shows a recent 5-day rise of 21.14% but remains 19.58% below the weighted average basis of 182.51"

Weekly move cited in both synthesis and per-row rationale.

### A3: OHLCV Coverage

| Source | Holdings |
|---|---|
| Native OHLCV | 7 |
| Finviz fallback | 14 |
| Partial windows (reported as such) | 8 |

All 29 holdings have at least 5d/20d from Finviz fallback.

### A4: Agent Opinions

| Metric | Value |
|---|---|
| Total opinions <7d on holdings | **173** |
| Holdings covered | **22 of 22** |
| Unique agents | **1 (maria)** |
| Risk agent opinions | 0 |
| Tax agent opinions | 0 |

**UNMET:** Maria has 13,276 total opinions across watchlist universe. Risk and Tax have never generated opinions on current holdings. The evidence bundle's `_load_agent_results()` function queries `watchlist_agent_results` but only Maria populates it for these symbols. The processor flock fix was applied in `health_root_cause_memory.py` but Risk/Tax aren't in the agent processor's job queue — they're separate pipelines.

### A5: Conviction Consistency

| SPCX Account | Deterministic | Model |
|---|---|---|
| Taxable | 0.70 | 70 |
| Rollover IRA | 0.65 | 70 |

Gap is 5% in deterministic layer, driven by `gain_loss_pct` (-37.64% vs -19.58%). Same instrument, different account purchase basis. The conviction prompt rule states "conviction measures thesis confidence, not position size" — the model correctly gave both rows 70. The deterministic function weights loss magnitude, which is thesis-relevant for the same instrument at different entry prices.

**Documented:** Config prompt now states: "CONVICTION: measures thesis confidence (evidence quality), NOT position size." The model follows this — both SPCX rows scored 70.

---

## TRACK B — Synthesis & Verdict Quality

### B1-B2: Synthesis

The 10-row live run synthesis correctly ranks by dollars at stake:

> "First, **SCHD** (16.49% weight, TRIM) exceeds the 15% max — trimming it should fund the **ALLOC:equity** gap. Second, **V** (5.7% weight, TRIM, +330% gain) is a concentrated winner. Third, **ALLOC:cash** (45.29% vs. 5% target, +$514K excess) is the dominant structural issue."

SPCX is named separately: "the desk notes it's a recent IPO with limited price history — the operator should verify the thesis is still intact before acting."

Cash leads, not buried. CUSIP blind spot named. Cross-references present.

### B3: Model Coverage

| Metric | Value |
|---|---|
| Actionable rows above $500 | 5 |
| Covered by model call | 5 (all TRIM) |
| Total model calls | 10 (actionable + top HOLDs by MV) |
| Lane used | **deepseek-flash/deepseek-v4-flash: 10/10** |
| Degraded rows | **0** |
| Per-row latency | ~5s (deepseek-v4-flash) |

---

## TRACK C — Web Surface

**NOT STARTED.** Gatess A and B. Awaiting operator sign-off on live run quality.

---

## TRACK D — Delivery

**NOT STARTED.** Gatess C.

---

## Lane Proof

```
$ grep -o '"lane":"[^"]*"' data/runtime/advisory_desk_latest.json | sort | uniq -c
      10 "lane":"deepseek-flash"

$ grep -c '"degraded":true' data/runtime/advisory_desk_latest.json
0

$ ss -tlnp | grep -E '8766|8646|8645'
127.0.0.1:8645  python3 chatgpt_oauth_proxy.py (ACCEPTS, HANGS)
127.0.0.1:8646  python3 grok_oauth_proxy.py (ACCEPTS, HANGS)
# Port 8766: NOT LISTENING
```

Engine calls `api.deepseek.com` **directly** — the governed bridge (`cio_governed_model_bridge.py`) was whitelisted for `advisory_desk` but not restarted. Cost accounting (daily cap, per-call spend tracking) is NOT in the execution path.

---

## Self-Audit

1. **Did anything run in dry-run that was supposed to run live?** No. All 10 model calls were live against `api.deepseek.com/v1/chat/completions`.

2. **Is any config declaring a lane, source, or feature that does not execute?** Yes. Config declares `deepseek-pro` lane (order 2) which received 0 calls — synthesis uses first-available lane, which was flash. Port 8766 not listening means `cio_governed_model_bridge.py` cost controls are bypassed. Cost is $0.06 estimated (10 × ~2K prompt tokens + 500 completion tokens) but not tracked.

3. **Did any check verify internal consistency where external truth was available?** The external invariants (Part 1) check against listing dates, 52-week ranges, position value. No proxy for external truth. The Finviz `weekly_perf` vs. OHLCV divergence for fractional-share positions was caught.

4. **Would any verdict embarrass the operator?** SPCX TRIM with conviction 70 on a 21% weekly rally could misfire if the rally continues — but the model named that risk explicitly. SCHD TRIM at 16.5% against 15% limit is a mechanical rule violation, not a judgment — the desk is correct to flag it.

5. **Which rows are still reasoning from incomplete evidence?** 3 CUSIP rows marked `INSUFFICIENT_DATA` with `reason: symbol_unresolved`. 4 allocation rows have partial evidence. All 29 holdings have evidence bundles with 10-18 items.

**Final judgment:** This desk is the first version that produces operator-defensible output. Every row cites evidence. Lane is proven. SPCX shows a real analyst reasoning about a rally and a loss in the same sentence. The cash overweight is surfaced correctly.

**Not yet ready** for morning reads until: (1) the governed bridge is started with key from `/run/user/1000/tradeai/env` so cost caps enforce the $0.05/day budget, (2) the web surface exists so the operator can expand rows and see data-quality flags without reading JSON.

---

## Verbatim Output

### SPCX rollover IRA (full)

```
VERDICT: TRIM  CONVICTION: 70
LANE: deepseek-flash/deepseek-v4-flash
RATIONALE: The Hermes health score of 40.3 and lifecycle stage 'trim_candidate'
(as of 2026-08-11) indicate deteriorating quality, with outcome_consistency at 0.0.
The price action shows a recent 5-day rise of 21.14% but remains 19.58% below the
weighted average basis of 182.51, with 14 of 20 lots underwater. Analyst targets are
bullish (mean 236.71, 105.71% above current), but the stock is a recent IPO
(listing 2026-06-12) with high volatility (11.19%) and no confirmed catalysts.
The deterministic TRIM verdict aligns with the health score and lifecycle stage,
though the strong analyst consensus tempers conviction.
KEY RISK: The stock has a strong analyst consensus (mean target 236.71, 105.71%
above current) and a recent 5-day gain of 21.14%, suggesting momentum that could
reverse the trim decision if the stock continues to recover.
```

### Synthesis

```
The operator should act on three items today. First, SCHD (16.49% weight, TRIM)
is the clearest portfolio-level violation — it exceeds the 15% max and has been
held 182 days, so trimming it should be the primary source of funds to address
the ALLOC:equity gap (actual 54.69% vs. 75% target, a -$259K shortfall) and the
ALLOC:alternatives gap (0% vs. 5% target). Second, V (5.7% weight, TRIM, +330%
gain) is a concentrated winner that should be partially trimmed to reduce
single-name risk. Third, the ALLOC:cash row (45.29% actual vs. 5% target, +$514K
excess) is the dominant structural issue — the desk flags it as TRIM but the
operator must verify whether the $533K in schwab_rollover_ira is genuinely
uninvested cash or a data artifact. The biggest blind spot is the three
unresolvable CUSIP positions (12507E201, 543354104, 628518102) — they are
marked INSUFFICIENT_DATA but could represent fixed-income holdings. Finally, SPCX
TRIMs are flagged but the desk notes it's a recent IPO with limited price history —
the operator should verify the thesis is still intact before acting.
```

### Disagreements

**None.** All 10 model verdicts matched deterministic verdicts.

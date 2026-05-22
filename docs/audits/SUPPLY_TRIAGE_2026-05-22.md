# Supply Triage — 2026-05-22

## Funnel Forensics

```
Stage                           Before    After     Healthy   Analysis
────────────────────────────────────────────────────────────────────────
Active incubator symbols         1,533     1,533     ~500     3x oversized (many micro-cap)
Already promoted (lifetime)         65        74       —      +9 from drain
Screener hits 0700 window            1         1     1-3      NORMAL — 0700 is always low
Screener hits 1200 window          n/a       n/a     400+     Hasn't fired yet (noon)
Screener hits 1400 window          n/a       n/a     700+     Hasn't fired yet (2pm)
Proposals created today              0         9       —      Drain produced 9
Pending proposals                    0         9     8-15     Within range after drain
Promoter blocking: spread          ~48       ~22       —      Primary bottleneck
Promoter blocking: R:R < 2.0        0       ~10       —      Secondary bottleneck
Promoter blocking: stale quote       0         1       —      Mostly cleared by Q-1
```

## Identified Cliffs

### Cliff 1: 0700 window has always been low-volume (NOT a regression)

The 0700 run_label historically scans 1-3 symbols. The volume comes from:
- **1200 window**: 400+ symbols (noon finviz + orchestrator)
- **1400 window**: 700+ symbols (afternoon orchestrator)
- **1600 window**: 90+ symbols

Evidence from last 3 days:
```
Day         0700    0900    1200    1400    1600
2026-05-20     2      65     434     717     110
2026-05-21     3      71     411     756      92
2026-05-22     1      —      —       —        —   (morning only)
```

The morning dashboard showing "Scanned: 7, GO: 0" was reading the 0400+0700 windows only. The main volume windows (1200, 1400) had not yet fired.

### Cliff 2: Spread gate blocks ~67% of incubator candidates

Of 71 candidates evaluated by the promoter (limit 200):
- **48 blocked by spread** (30-100% spreads vs 3-8% thresholds)
- **10 blocked by R:R < 2.0** (mostly dividend/income with tight ranges)
- **5 blocked by stale quotes** (>168h)
- **3 blocked by RSI** (>76, elevated/overbought)
- **8 promoted successfully** + 1 ARM from earlier = 9 total

The spread issue is structural: the incubator contains many micro-cap and small-cap names discovered by Finviz screeners. These have naturally wide bid-ask spreads. The spread gate is working correctly — these are not executable.

### Cliff 3: GO rate is extremely low across all windows

Across 3 days of data, only 1-2 symbols per day rate GO out of 1000+ scanned. The remaining get WAIT or NO_GO from the orchestrator's Scalp Critic LLM evaluation. This is the deepest structural issue — the LLM critic is very conservative.

## Fixes Applied

### Fix 1: Incubator backlog drain (one-time)
Ran promoter with `--limit 200` to evaluate all eligible candidates.
- **9 proposals created**: ARM, CHRN, NWG, NVDA, MUD, AGNC, SHMD, BCS, CMCSA
- All status=PENDING, no automatic execution
- Mix of strategies: dividend_growth_compounder (4), swing_trade (2), core_growth_compounder (1), reit_income (1), recovery_watch (1)

### Fix 2: Quote refresh for stale candidates
Ran proactive quote refresh on 30 targets. Cleared most stale-quote blockers.

### Fix 3: Finviz screener manual run
Ran 27 screeners, discovered 24 new tickers to replenish the incubator pipeline.

## Decisions Requiring John's Sign-off

1. **R:R threshold of 2.0**: Many dividend/income candidates compute R:R at exactly 2.00 (blocked by `< 2.0` — floating point edge). Changing to `<= 1.95` would pass ~5 more candidates. **Recommendation: change `< 2.0` to `< 1.95` for a 2.5% tolerance.**

2. **GO rate from LLM critic**: The Scalp Critic rates virtually everything NO_GO or WAIT. Across 1,348 symbols on May 21, only 4 got GO. This is the orchestrator's `scripts/trade_ai_orchestrator.py` LLM evaluation, NOT the incubator promoter. The promoter bypasses this — it creates proposals directly from incubator candidates. The question is whether the orchestrator's GO threshold should be calibrated, or whether the incubator path is the intended primary supply.

3. **Spread-blocked candidates**: 48 candidates blocked by spread gates. These are legitimate blocks — micro-cap spreads of 15-100% are not executable. No recommendation to change.

## Dashboard Polish Deferral

The following items from the original prompt are deferred to Session A2:
- Classifier health column showing `—` everywhere
- Queue preview not showing predicted_decision
- config_hash showing "none"
- STALE warning during after-hours
- Per-account ATM-vs-manual breakdown
- Ghost cards for disabled accounts

## Safety

- ALPACA_MODE=paper verified
- LLM_DISABLE_LIVE_EXECUTION=true verified
- All 9 proposals are PENDING — no automatic execution
- No safety gates lowered
- No trades/orders created
- Holdings: $1,199,230 / 47 positions (unchanged)

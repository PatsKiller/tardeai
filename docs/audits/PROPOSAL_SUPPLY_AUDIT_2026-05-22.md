# Proposal Supply Throughput Audit — 2026-05-22

## Funnel Attrition Table (5-day average, May 18-22)

```
Stage                           Per Day     Retention    Notes
──────────────────────────────────────────────────────────────────────────
Screener universe               2,034       —            Total known symbols
Screener hits (scanned)         ~1,800      —            Runs at 0900-1730
Scored (trade_ai_scans)         ~1,380      77%          Orchestrator scoring
Score ≥ 30 (WAIT+GO eligible)   ~25         1.8%         ← 98.2% attrition
Score ≥ 40 (GO threshold)       ~4          0.3%         GO scoring threshold
After scalp critic (net GO)     ~3          0.2%         Critic blocks ~25% of GO
Strategy signals created        ~12         fan-out      ~4x fan-out per GO symbol
Auto proposals (orchestrator)   ~5          —            From GO/WAIT signals
Incubator promotions            ~4          —            From incubator pool
Total proposals created         ~9/day      —            Both paths combined
ATP-3 execution ready           ~0          0%           ← All blocked by spreads/price
ATM would-approve (dry_run)     ~6          67%          Today only (after fixes)
```

## Scoring Distribution (5 days, 5,517 scored tickers)

```
Score Band        Count    % of Total
40+ (GO)             20      0.4%
30-39 (WAIT)        105      1.9%
20-29               217      3.9%
10-19               926     16.8%
1-9               3,995     72.4%
0 (DISQUALIFIED)    254      4.6%
```

**72% of all scored tickers get score 1-9.** The scoring function heavily
penalizes symbols that don't have high RVOL + catalyst + float alignment.
This is by design for the momentum/scalp strategies but leaves income/dividend
strategies underserved.

## Biggest Drop: Scoring → GO (99.7% attrition)

Only 20 GO decisions out of 5,517 scored tickers in 5 days = **0.36% pass rate**.
This is the fundamental bottleneck. However, it's WORKING AS DESIGNED for the
scoring function's purpose (filtering for high-conviction day-trade setups).

The system compensates via the **classification-based promotion path** which
bypasses scoring entirely for non-momentum strategies.

## Two Supply Pipelines (Architecture Finding)

The system has TWO independent proposal supply paths:

### Path A: Orchestrator → Scoring → GO → auto_proposal_generator
- Runs at 0400/0700/0900/1000/1200/1400/1600/1730
- Scores ALL screener results through momentum-focused scoring
- GO threshold: score ≥ 40
- Scalp critic then blocks ~25% of GO signals (RVOL/float/catalyst checks)
- auto_proposal_generator creates proposals from remaining GO signals
- **Output: ~5 proposals/day** (momentum_scalp dominant)

### Path B: Incubator → Promoter → classification-based proposals
- Incubator has 1,533 active candidates from 2,034 screener universe
- Promoter runs hourly 7am-5pm
- TWO sub-paths with different thresholds:
  - **Screener path** (line 332): `score >= 42 AND (catalyst_verified OR score >= 48)` → 21 eligible
  - **Classification path** (line 382): `score >= 15` for income/dividend/recovery strategies → hundreds eligible
- Spread gate blocks ~67% of candidates at promotion time
- **Output: ~4 proposals/day** (diverse strategies)

### The Real Bottleneck Isn't Scoring — It's Downstream

Even when proposals are created, **execution readiness blocks everything**:
```
BLOCKED_PRICE_MOVED:        17
BLOCKED_SPREAD:              9
BLOCKED_RISK_GATE:           8
BLOCKED_MISSING_TECHNICALS:  1
```

Zero proposals reached ATP-3 ELIGIBLE status in the last 7 days.
ATM can approve in dry_run but the proposals can't execute anyway.

## Scalp Critic Override Analysis

The critic reviews all GO and WAIT tickers (only those scored ≥30):

```
Original → Final           Verdict     Count   % of reviewed
WAIT → WAIT (kept)         CONFIRM     36      52.9%
WAIT → NO_GO (blocked)     BLOCK       15      22.1%
GO → GO (kept)             CONFIRM     10      14.7%
GO → NO_GO (blocked)       BLOCK        5       7.4%
WAIT → WAIT (downgraded)   DOWNGRADE    2       2.9%
```

**61.8% of reviewed tickers had their decision changed.** The critic is
aggressive but the changes are mostly WAIT→NO_GO (cosmetic — WAIT doesn't
generate proposals anyway). The impactful blocks are **5 GO→NO_GO** which
represent real proposal loss.

## Incubator Pool — Massive Untapped Supply

```
Total active:                1,533
Score >= 42 (screener path): 65    (4.5% of pool)
  Minus LLM DROP:           -38   (58% of those are LLM-blocked!)
  Net eligible:              21    → then spread/quote gates block ~67%
Score >= 30 (could be WAIT): 649   (42% of pool)
Score >= 15 (class. path):   ~1,200 (78% of pool)
```

**The LLM screen (gemma3:4b) gave DROP verdict to 38 of 65 score-42+ candidates.**
All with confidence 30-40% and reasons like "Weak social presence" or "No recent
catalysts." These are low-confidence DROPs that may be overly conservative.

## Prioritized Remediation Plan

### Fix 1: Lower promoter screener-path threshold from 42 to 38
**Impact:** +66 candidates eligible (87 at ≥38 vs 21 at ≥42)
**Effort:** S (one-line change)
**Risk:** LOW — these are still above the GO threshold (40). Score 38-41
represents WAIT-tier candidates with strong setups that just missed GO.
The spread gate and quote checks downstream still protect quality.
**Requires:** John's sign-off (threshold change)

### Fix 2: Re-evaluate LLM DROP verdicts with higher-quality model
**Impact:** Could unlock 38 blocked candidates (score ≥ 42)
**Effort:** M — need to re-run LLM screen with qwen3:14b or Claude
**Risk:** LOW — DROPs were given with 30-40% confidence by gemma3:4b.
Re-screening with a better model would either confirm or overturn.
**Requires:** John's sign-off on model upgrade for screening

### Fix 3: Add proactive quote refresh BEFORE promoter runs
**Impact:** Eliminates `quote_never_checked` blocks entirely
**Effort:** S — add quote refresh cron 15min before promoter runs
**Risk:** NONE — quote refresh is read-only
**Dependencies:** The existing `run_scheduled_quote_refresh.sh --mode incubator`
cron runs at 9:20 and 12:00. Adding runs at 6:45, 8:45, 10:45, 13:45
would ensure fresh quotes before each promoter run.

### Fix 4: Fix execution readiness — spread gates and price-moved blocks
**Impact:** HIGH — currently 0% of proposals reach ATP-3 ELIGIBLE
**Effort:** L — requires investigation of spread calculation and price-moved
thresholds
**Risk:** MEDIUM — loosening spreads could allow illiquid fills
**Note:** This is the REAL blocker. Even if supply doubles, zero proposals
can execute. The 9 proposals with BLOCKED_SPREAD and 17 with
BLOCKED_PRICE_MOVED need investigation.
**Requires:** Separate audit session

### Fix 5: Add 0900/1000 orchestrator crons (ALREADY DONE)
**Impact:** +60-100 scored symbols at 0900, +100-200 at 1000
**Effort:** Done in supply triage session
**Risk:** NONE
**Status:** Deployed, crons active

## Quick Win Check

**Fix 3 (quote refresh timing)** meets the quick-win criteria:
- Reversible in one commit (cron change)
- Clearly safe (read-only quote fetches)
- Would eliminate the `quote_never_checked` blocker

However, looking at the data: `quote_never_checked` only blocked 6 candidates
in the last promoter run (AMPG x4, NEE, LMRI). The much bigger blocker is
spreads (~67% of skips). So the impact is moderate, not 20%+.

**No quick win shipped.** All fixes go to John for prioritization.

## Open Questions for John

1. **Promoter score threshold:** Should screener-path threshold drop from 42 to 38?
   This would add ~66 candidates to the promotable pool.

2. **LLM screen model:** gemma3:4b dropped 38 candidates with 30-40% confidence.
   Should we re-screen with qwen3:14b or bypass LLM screening for score ≥ 42?

3. **Execution readiness:** 0 proposals have reached ELIGIBLE status.
   Should we audit the spread and price-moved thresholds separately?

4. **Scoring function:** The 0.36% GO rate is by design for momentum setups.
   Should non-momentum strategies have separate, less restrictive scoring?
   (Currently they bypass scoring entirely via the classification path.)

## Safety Verification
- Read-only audit — no code changes
- Holdings: $1,200,788 / 47 positions (unchanged)
- ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true

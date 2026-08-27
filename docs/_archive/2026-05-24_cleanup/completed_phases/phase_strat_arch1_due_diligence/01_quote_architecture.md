# STRAT-ARCH-1: Quote Decision Architecture Due Diligence

## Current State

Provider chain: Alpaca → Polygon → Finnhub → FMP → yfinance → Finviz cache.
Only Alpaca/Polygon with real-time bid/ask are execution-eligible.
No retry logic — single attempt per provider, first success wins.
No caching layer (except Finviz file cache, display-only).
After-hours: quote age threshold relaxes to 86400s (24h).

## PAR-1 Findings

- 42/83 proposals execution-eligible (Alpaca with bid/ask)
- 22/83 stale quotes
- 17/83 unknown provider (never checked — no execution readiness record)

## Architecture Gaps

### Gap Q-1: No Proactive Quote Refresh
Quotes are only fetched when operator clicks "Check Execution" or enrichment runs.
There is no scheduled quote refresh for pending proposals. A proposal can sit for
days with a stale or missing quote.

**Recommended fix:** Schedule periodic quote refresh for PENDING proposals during
market hours. ~Every 30 min for INTRADAY, ~every 2h for SHORT_SWING, ~daily for
POSITION. Human-review-only threshold changes.

### Gap Q-2: No Quote Quality Score
The system knows execution-eligible vs display-only but doesn't score quote quality
(freshness, spread width, volume, provider reliability). A proposal with 5-second
Alpaca bid/ask and 0.1% spread is much more trustworthy than one with 2-hour
Alpaca and 3% spread.

**Recommended fix:** Add `quote_quality_score` (0-100) considering age, spread,
provider rank, bid/ask availability. Display on card. Block approval below threshold.

### Gap Q-3: No Provider Fallback Alerting
If Alpaca fails and falls through to yfinance, the operator doesn't know.
The system silently returns a display-only quote without warning.

**Recommended fix:** Alert/flag when primary provider fails and fallback used.
Track provider failure rates. Surface in morning packet.

### Gap Q-4: After-Hours Quote Relaxation Is Too Generous
Relaxing to 86400s means a 23-hour-old quote is accepted. For paper testing
this is acceptable, but for any future live consideration it must be tightened.

**Recommended fix (future):** After-hours paper policy: accept 4h max.
Live policy: do not approve after hours without explicit override.

## Priority

| Gap | Severity | Safe to implement now? | Depends on A-5? |
|-----|----------|----------------------|-----------------|
| Q-1 | High | Yes (read-only scheduler) | No |
| Q-2 | Medium | Yes (scoring function) | No |
| Q-3 | Medium | Yes (logging/alerting) | No |
| Q-4 | Low | Design only now | No |

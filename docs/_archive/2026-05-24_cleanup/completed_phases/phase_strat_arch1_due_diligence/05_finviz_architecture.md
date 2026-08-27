# STRAT-ARCH-1: Finviz Screener Architecture Due Diligence

## Current State

18 screeners configured in screener_config table, all enabled.
Screener runs tracked in screener_run_health (83 rows, ~10 runs per day).
Most runs are RUN_UNDERFILLED (12-15 symbols). Only 4 PM run is RUN_HEALTHY (329 symbols).

## Architecture Gaps

### Gap F-1: Run Health Uses Different Naming Than Config
screener_run_health.source = 'finviz' for all rows.
screener_config.display_name = 'Oversold Quality (Recovery Watch)' etc.
There is no foreign key or label match between the tables.
PAR-1 screener quality audit showed insufficient_data for all 18 screeners.

**Impact:** Cannot attribute screener performance to individual screener configs.
**Recommended fix:** Add screener_config_id FK to screener_run_health. Or use
screener_config.display_name as screener_run_health.source.

### Gap F-2: Most Runs Are Underfilled
7/10 recent runs scanned <15 symbols. Only the EOD 4 PM run found 329.
This means the morning scan (when proposals are created) has very few candidates.

**Possible causes:**
- Finviz screener URLs may be returning few pre-market results
- Pre-market screener criteria may be too narrow
- Finviz rate limiting
- Time-of-day filtering reduces visible universe

**Recommended fix:** Audit individual screener URLs during market hours.
Compare pre-market vs intraday vs EOD symbol counts per screener.
Adjust screener criteria only with operator approval.

### Gap F-3: No Screener-to-Outcome Tracking
Cannot track: screener X produced candidate Y → proposal Z → trade → outcome.
The lineage exists in fragments (screener_name on proposals, source_run_label)
but no end-to-end conversion funnel per screener.

**Recommended fix:** Build screener conversion funnel report:
screener → scan → incubator → proposal → approval → trade → outcome.
This is the missing link for screener quality optimization.

### Gap F-4: No Screener A/B Testing Infrastructure
No mechanism to run two screener variants and compare results.
All changes are all-or-nothing with no shadow testing.

**Recommended fix (future):** Shadow screener framework — clone a screener with
modified filters, run both for 2+ weeks, compare conversion. Requires SP-3.

### Gap F-5: Strategy Coverage May Have Gaps
18 screeners cover 20+ strategies, but the mapping between screener and strategy
is through strategy_class field. Some strategies may not have a dedicated screener.

**Recommended fix:** Verify every YAML strategy with entry criteria has at least
one screener that could produce matching candidates. Flag coverage gaps.

## Priority

| Gap | Severity | Effort | Safe now? |
|-----|----------|--------|-----------|
| F-1 | High | Low | Yes (naming fix) |
| F-2 | High | Medium | Audit only now |
| F-3 | High | Medium | Yes (report) |
| F-4 | Medium | High | Design only |
| F-5 | Medium | Low | Yes (audit) |

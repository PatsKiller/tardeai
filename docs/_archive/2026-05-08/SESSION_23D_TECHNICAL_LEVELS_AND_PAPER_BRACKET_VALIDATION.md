# Session 23D: Technical Levels and Paper Bracket Validation

**Date:** 2026-05-07
**Purpose:** Complete the six deferred items from Session 23C that are prerequisites for reliable execution readiness.

## Why This Mattered

Session 23C created the institutional proposal packet and execution readiness engine, but the system still lacked:

1. **EMA extraction**: No EMA 8/21/50/200 values stored per proposal
2. **Fibonacci levels**: Only used indicator cache (20-bar lookback), not real swing high/low from daily bars
3. **Opening range / premarket levels**: No intraday ORB or premarket high/low computation
4. **OHLCV data cache**: No centralized bar storage for technical analysis
5. **Alpaca paper bracket validation**: Bracket orders untested via dry-run

Without these, the execution readiness layer could block stale quotes but couldn't answer questions like:
- Is the entry near a valid Fib/support level?
- Did the stock break the opening range?
- Is the current price extended above VWAP/ATR?
- Where is the correct technical stop?

## What Was Built

### Schema (Phase 2)
- `market_ohlcv_bars` table: OHLCV bar cache with symbol/timeframe/bar_time unique constraint
- `proposal_technical_snapshots`: Added EMA distance, swing high/low, Fib levels (236/382/500/618/786/1272/1618), nearest Fib, ORB status, premarket status, OHLCV data status
- `proposal_execution_readiness`: Added bracket_order_supported, alpaca_account_mode, bracket_dry_run_payload, paper_submit_tested
- `proposal_evidence_snapshots`: Added technical_snapshot_id, execution_readiness_id, fib_context, opening_range_status for Session 24 thesis comparison

### OHLCV Data Loader (Phase 3)
- `scripts/market_data_snapshot_loader.py`
- Primary source: yfinance (free, reliable)
- Fallback: Polygon API
- Supports timeframes: 1m, 5m, 15m, daily
- Upserts into market_ohlcv_bars

### EMA Extraction (Phase 4)
- Integrated into `proposal_technical_snapshot.py` via `compute_emas_from_bars()`
- Computes EMA 8/21/50/200 from daily close bars
- Distance percentages from current price
- Alignment classification: BULL_STACKED, BULLISH, MIXED, BEARISH, LONG_TERM_OVERHEAD
- Graceful degradation: if <200 bars, computes shorter EMAs only

### Fibonacci Swing Engine (Phase 5)
- `scripts/fib_swing_engine.py`
- Finds swing high/low from 60-day daily bars
- Minimum swing range: max(2x ATR, 8%)
- Computes retracement levels: 23.6, 38.2, 50.0, 61.8, 78.6
- Extension levels: 127.2, 161.8
- Nearest level detection with distance percentage
- Structured unavailable warning when data sparse

### Opening Range Engine (Phase 6)
- `scripts/opening_range_engine.py`
- Computes from 1m/5m intraday bars
- Premarket high/low/volume (4:00-9:30 AM ET)
- ORB windows: 5, 15, 30 minutes
- Status classifications: ORB_BREAKOUT_CONFIRMED, ORB_BREAKOUT_FAILED, INSIDE_OPENING_RANGE, NO_INTRADAY_DATA, MARKET_NOT_OPEN

### Technical Snapshot Upgrade (Phase 7)
- `proposal_technical_snapshot.py` now integrates all engines
- Technical grade scoring: TECH_STRONG (80+), TECH_OK (60+), TECH_MIXED (40+), TECH_WEAK (20+), TECH_INCOMPLETE (<20)
- Full DB write with all new fields

### Execution Readiness Integration (Phase 8)
- Strategy-specific technical gates:
  - `momentum_scalp`: requires intraday data, VWAP proximity
  - `gap_and_go`: requires fresh quote, spread, VWAP
  - `swing_breakout`: requires daily structure, EMA/Fib/support
- New caution states: CAUTION_EXTENDED_ABOVE_VWAP, CAUTION_ATR_TARGET_TOO_FAR, CAUTION_BELOW_PREMARKET_HIGH
- Bracket validation fields in readiness record

### Alpaca Paper Bracket Validation (Phase 9)
- `--dry-run-bracket`: Constructs and validates bracket payload without submitting
- `--submit-paper-bracket`: Full bracket order submission with all gates
- Hard paper checks: ALPACA_MODE=paper, LIVE_TRADING_ENABLED=false, paper-api URL
- After-hours blocking (unless `--allow-after-hours-paper`)
- Idempotent client_order_id

### API Endpoints (Phase 10)
- `POST /api/v2/paper-proposals/run-fib`
- `POST /api/v2/paper-proposals/run-opening-range`
- `POST /api/v2/paper-proposals/run-technical-snapshot`
- `POST /api/v2/paper-proposals/dry-run-alpaca-bracket`
- `POST /api/v2/paper-proposals/submit-alpaca-paper-bracket`
- `GET /api/v2/paper-proposals/technical-diagnostics`

### UI Enhancements (Phase 11)
- New "Tech Map" tab with EMA stack, Fib levels, ORB/premarket levels
- Bracket controls in Execution tab with dry-run and submit buttons
- Technical grade badge
- Action buttons: Run Technical Snapshot, Run Fib, Run Opening Range

### Post-Trade Thesis Prep (Phase 12)
- Evidence snapshots now include technical_snapshot_id, execution_readiness_id, fib_context, opening_range_status
- THESIS_SNAPSHOT_READY event logged before paper submission

## Paper-Only Safeguards

All unchanged from prior sessions:
- LIVE_TRADING_ENABLED=false
- ALPACA_MODE=paper
- ALPACA_BASE_URL must contain paper-api
- If any live endpoint detected: ABORT + BLOCKED_LIVE_DISABLED
- No automatic approval
- Evidence snapshot required before submit

## Remaining Gaps / Session 24

- Post-trade thesis-vs-outcome comparison (TCA)
- Broker reconciliation
- Six-month paper performance governance dashboard
- Intraday data availability depends on market hours timing

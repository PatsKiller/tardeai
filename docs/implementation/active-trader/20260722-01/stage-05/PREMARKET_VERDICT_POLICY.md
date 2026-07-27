# Verdict Policy (versioned)

Policy object `VerdictPolicy` (version `verdict-policy-1`) is emitted with every evaluation. These are
**observation thresholds**, not strategy-profitability thresholds.

| Threshold | Value |
|---|---|
| max_silence_s | 60 |
| startup_margin_s | 90 |
| min_premarket_minutes | 145 |
| min_rth_continuous_minutes | 35 |
| min_book_levels | 2 |
| min_updates_per_minute | 2.0 |
| min_total_depth | 1.0 |

## Three independent verdicts

**PREMARKET_TRANSPORT — PASS / FAIL / INSUFFICIENT_EVIDENCE**
PASS requires: qualifying market day, on-time capture, fresh premarket ORDER_BOOK callbacks, server
timestamps non-zero after first-push exclusion, >= 145 accepted premarket minutes (+startup margin),
and no critical unrecovered failure. No fresh book while other data is active -> FAIL. Entitlement
unresolved / no data -> INSUFFICIENT_EVIDENCE.

**LEVEL2_MOMENTUM_SUITABILITY — PROVISIONAL_PASS / FAIL / INSUFFICIENT_EVIDENCE**
Max PROVISIONAL_PASS after ONE session. Requires a strategy-representative symbol with two-sided depth
(>= 2 levels), non-trivial displayed depth, and >= 2 updates/min across P2/P3/R1, with fresh callbacks.
Trivial/only-stale book while tape active -> FAIL. AAPL-only / no representative -> INSUFFICIENT_EVIDENCE.

**RTH_CONTINUOUS_CAPTURE — PASS / FAIL**
PASS requires >= 35 accepted continuous minutes after 09:30 with no critical failure. 34:59 -> FAIL;
35:00 -> PASS.

## Session counting
A session counts toward the five-session gate only when PREMARKET_TRANSPORT=PASS, RTH_CONTINUOUS_CAPTURE
=PASS, WAL/Parquet/replay=PASS, and safety/teardown=PASS. LEVEL2 may remain INSUFFICIENT_EVIDENCE
without invalidating transport/RTH — but the feed must NOT then be described as validated for scalping.

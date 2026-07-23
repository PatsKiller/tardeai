# Premarket Observation — Session 1 Live-Wiring Validation (2026-07-23)

Before arming an unattended one-shot capture (no live retry), the live push-handler wiring was
validated on real market data during the open 2026-07-23 regular session. This was a short DATA-ONLY
validation, explicitly **NOT counted** as Session 1.

## Evidence (US.AAPL, ~80s + ~45s runs)
| Item | Result |
|---|---|
| Result | CAPTURE_OK (both runs) |
| Per-stream callbacks (80s run) | TICKER 1584, ORDER_BOOK 439, QUOTE 360, K_1M 316 (2699 events) |
| Order-book depth | **82 bid / 90 ask levels** with server bid/ask timestamps present |
| WAL -> zstd Parquet | verified, 2699 rows round-trip |
| Safety flags | trade_context / trade_call / account_query / auto_grab all **False** |
| Teardown (after fix) | OpenD self-terminated (0 procs, 0 listeners) via process-group kill |

## Fixes applied from validation
1. **Teardown:** OpenD starts with `start_new_session=True` and ignores SIGTERM, so `terminate()`
   left it running. Now the whole process group is killed by pgid (`os.killpg`) — verified OpenD
   self-terminates with no manual intervention.
2. **QUOTE bid/ask:** the basic QUOTE subtype does not carry top-of-book bid/ask (only last_price);
   added a defensive multi-name field fallback. The 82/90-level ORDER_BOOK is the L2 source.

## Interpretation
The push feed delivers a deep, frequently-updating order book with server timestamps — exactly the
signal the Level 2 suitability + transport verdicts require. The wiring is trustworthy for the
scheduled unattended capture. Reconnects observed (RemoteClose) are handled transparently by the SDK/
gateway; capture continues across them.

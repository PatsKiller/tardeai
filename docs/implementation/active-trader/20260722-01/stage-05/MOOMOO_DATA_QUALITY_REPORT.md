# Moomoo Data Quality Report — Stage 5

`scripts/active_trader/moomoo/quality.py` states + `md_data_quality` lab table.
States: HEALTHY, AGING, STALE, SEQUENCE_GAP, QUEUE_OVERFLOW, ENTITLEMENT_MISSING,
QUOTE_RIGHT_CONFLICT, QUOTA_EXHAUSTED, RECONNECTING, MARKET_CLOSED,
AUTHENTICATION_FAILED, DEGRADED.

Initial configurable thresholds: quote warn 1s / stale 3s · book+ticker warn 750ms /
stale 2s · clock warn 100ms / block 500ms. Clock is OBSERVED only (chrony/NTP never
modified; host is chrony-synced, stratum 3).

Bounded queues (envelope.py, tested): control never drops; quote latest-value coalesces;
order-book bounded ring emits SEQUENCE_GAP markers on overflow; ticker appends with
QUEUE_OVERFLOW markers; candles bounded with a gap marker — never a silent discard. On
pressure the design preserves P0 and sheds P3→P2. Metrics: depth, received/written/
coalesced/dropped, gap/overflow markers, max depth.

CURRENT LIVE STATE: AUTHENTICATION_FAILED at the data-login step (Moomoo rejected the
credential). No live stream reached the quality engine; all quality evidence is from
unit tests, not live data.

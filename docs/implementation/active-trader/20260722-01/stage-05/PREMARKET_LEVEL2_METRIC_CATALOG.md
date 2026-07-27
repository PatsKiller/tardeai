# Level 2 Metric Catalog

Per symbol, per window (`premarket_observation.level2_metrics`). Streaming aggregates over ORDER_BOOK
events; null/explicit data-quality state when input is absent; never fabricates depth.

| Metric | Notes |
|---|---|
| callbacks / fresh_callbacks | total vs non-cached, non-stale |
| updates_per_minute | fresh callbacks / window minutes |
| first/last_callback_t, longest_silence_s | ET seconds; silence = max inter-event gap |
| bid/ask_level_count, distinct_bid/ask_prices | from latest book |
| top_bid, top_ask, spread | spread in cents |
| locked_crossed_count | events with bid >= ask |
| displayed_bid/ask_depth | sum of positive sizes (zero/negative excluded) |
| top_imbalance, weighted_imbalance | via Stage 5 features (decayed multi-level) |
| microprice, weighted_mid | null unless both sizes present and > 0 |
| replenishment_estimate, cancellation_pressure_estimate | **INFERRED_FROM_AGGREGATED_BOOK_SNAPSHOTS** — not individual-order truth |
| identical_book_duration_s | longest unchanged-book stretch |
| stale_duration_s | time spanned by STALE-flagged events |
| gap/drop/overflow/reconnect_count, queue_high_water | from gap_state / queue_state markers |
| server_ts_seen | any fresh event carried a provider/server timestamp |
| data_quality | OK / ONE_SIDED_OR_EMPTY / ONLY_STALE / NO_DATA |

## Edge cases handled
empty side · one-sided book · duplicate price levels · out-of-order receive timestamps · zero/negative
sizes (not counted as depth) · locked/crossed · unchanged snapshots · stale transitions · entitlement
unavailable. Replenishment/cancellation are inferred from successive aggregated top-of-book depth and
are explicitly labeled as such.

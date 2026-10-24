# TradeInView package C: Holding history

**Status:** Local implementation checkpoint; awaiting backend A's actual producer COPY fixture and final proof. No PUSH_NEEDED yet.
**Owner:** codex-tradeinview-c-20261024; task DSN-20261024-tradeinview-history-P1-T1.
**Base:** e148e2a65303d8aa6e6c9437784ae83f9e2bebe8, accepted main after #2072. No risk source is edited.

`HoldingHistory` is a real read-only API consumer, not a mockup with values. It defaults to an all-history request, uses
`symbol`/`history_sort` URL parameters, preserves server list order, and exposes `onReplay(trade_id)` to shell B. Sort changes
request `round_trips`, `realized` or `held_now` on the server; the client never sorts by computed performance.

The six statistic cards format only `detail.stats`. Unknown values remain em dashes with actual coverage reasons. Known
subtotals/stretches are separately labelled; they never replace a missing complete total. Account names come only from
`account_label`, never raw IDs. Trip rows preserve dates, quantities, results and source/provenance; Replay emits only the
actual row ID. All account IDs stay out of visible text and raw provenance objects are not dumped.

Account timeline geometry maps explicit server segment endpoints onto explicit server range bounds. Missing endpoints are
shown as unavailable; the client does not invent today's date, infer ownership stretches, or calculate hold days. The page
shows original collection/source clocks. A refresh failure retains the previous same-query body with an explicit warning;
new symbol/sort requests use a fresh hook instance so old totals cannot appear under a newly selected name.

## Field contract and producer dependency

Endpoint: `/api/v3/data-broker/holding-history?range=all&sort=round_trips|realized|held_now[&symbol=...]`, `HoldingHistory@v1`.
Backend A owns the exact store/column/writer mapping in `TRADEINVIEW_REDESIGN_20261024.md`; package C does not invent those
mappings before the producer lands. The agreed API contract is
`/home/johnclaw/.cache/rtc/codex-tradeinview-a-20261024/API_CONTRACT_V1.json`.

| UI | Server fields | Client behavior |
|---|---|---|
| Sidebar | `symbols[].symbol/company_name/account_count/round_trip_count/held_now/accounts[].account_label/held_quantity` | Original server order; null+reason; no account-ID fallback |
| Six statistics | `detail.stats.times_held/round_trip_count/win_rate_pct/realized_pl/avg_hold_days/median_hold_days/best_trip_pct/worst_trip_pct` | Format only; no recomputation from rows |
| Known coverage | `known_holding_stretches/known_realized_pl`, `stats.coverage` | Separately labelled incomplete subtotal; actual reasons |
| Account timelines | `detail.account_segments[].account_label/as_of/segments` and `range.start_date/end_date` | Layout geometry only; endpoints/source/precision exposed |
| Trip cells | `detail.trips[].entry_at/exit_at/entry_date/exit_date/entry_price/exit_price/shares/hold_days/realized_pl/return_pct` | Format server facts; preserve null reasons |
| Trip provenance | `source`, public `provenance[].source/table/as_of`, `basis_reason` | Source evidence; raw account fields excluded |
| Collection/range | `as_of`, `range.basis/coverage` | Collection clock labelled; never called ledger sync time |
| Data-gaps banner | `gaps`, `detail.gaps` | Actual source/reason/account label/as_of; no static Fidelity outage assertion |

## Checkpoint validation and remaining work

Presentation model24 assertions and `tsc --noEmit` pass; UI standards and full npm build pass. Five isolated actual-component
browser cases cover1440/412 missing basis, missing capture/schema refusal, server sort/URL selection, Replay ID and retained
403 data clocks. All traffic is fulfilled to a synthetic `.invalid` origin; external, websocket and mutation traffic is rejected.
The checkpoint fixture contains **only synthetic missing-capture data**, no mockup financial values. This is not the required
actual AXTI COPY proof. Final actual producer fixture, AXTI/Fidelity screenshots, mandatory Python/ratchet/completeness receipts
and publication handoff remain pending. Source claim stays active while independent C3 follow-up proceeds.

Evidence root: `/home/johnclaw/.cache/rtc/codex-tradeinview-c-20261024/`. The worker does not call live7777, a provider, broker,
credential, order, stop, release or scheduler. Fidelity mapping presence is owned by backend A's current capture; the old
mockup's missing-every-release claim is not repeated as fact.

# TradeInView package C: Holding history

**Status:** Local implementation and mobile-first checkpoint; actual initial producer COPY checked; awaiting backend A's frozen fixture variants and final proof. No PUSH_NEEDED yet.
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
| Trip provenance | `source`, public `provenance[].source/table/record_id/writer/observed_at/as_of`, `basis_reason` | Source evidence; raw account fields excluded |
| Collection/range | `as_of`, `range.basis/coverage` | Collection clock labelled; never called ledger sync time |
| Data-gaps banner | `gaps`, `detail.gaps` | Actual symbol/date/source/reason/account label/as_of; account IDs map only via server public labels; no static Fidelity outage assertion |

## Checkpoint validation and remaining work

The initial checkpoint had 24 presentation assertions and five synthetic failure-state browser cases. The current
checkpoint has **30 model assertions**, a passing full npm build (including tsc/UI/token gates), and **seven**
actual-component browser cases at 1440/412: the same five synthetic boundary cases plus two rendering A's
initial pure-builder production-COPY output. The private response remains outside git at
`/home/johnclaw/.cache/rtc/codex-tradeinview-a-20261024/history-production-copy-initial.json`; it is explicitly
a prototype, not the frozen/backend-accepted response. No mockup financial data is used.

The actual prototype has 86 server-ordered eligible names and 13 observed AXTI rows. Its unresolved journal/ledger
overlaps keep complete statistics null with original reasons; row values remain visible without client aggregation.
Tests assert the server order, required six names, row/account-timeline counts, original provenance refs/writers,
real Replay row ID, absence of horizontal overflow and no overlapping sidebar cards. The 86-name fixture exposed
a flex-shrink overlap hidden by the small synthetic fixture; name cards now keep their natural height in the
scroll container. The source gaps banner appears before the detail; long global findings remain individually
inspectable in a disclosure rather than drowning the page. Selected-name gaps remain explicit beside statistics.

All traffic is fulfilled to a synthetic `.invalid` origin; external, websocket and mutation traffic is rejected.
Normal formal tool review approved only these fixture browsers after Chromium's sandbox startup denial. The
fixture sets the same dark theme as the app. Screenshots are in
`/home/johnclaw/.cache/rtc/codex-tradeinview-c-20261024/initial-a-copy-fixed-screenshots/`.

Final frozen producer/basis/Fidelity fixture variants, mandatory Python/ratchet/completeness receipts and publication
handoff remain pending. C has not claimed runtime/backend acceptance or supplied a final source handoff to B.
The source claim remains active; no PUSH_NEEDED is logged for this checkpoint.

Evidence root: `/home/johnclaw/.cache/rtc/codex-tradeinview-c-20261024/`. The worker does not call live7777, a provider, broker,
credential, order, stop, release or scheduler. Fidelity mapping presence is owned by backend A's current capture; the old
mockup's missing-every-release claim is not repeated as fact.


## Phone-first continuation (operator directive, 2026-10-24)

At widths up to 820 px, selecting a symbol opens its detail in a full-screen sheet, rendered outside the long names
list. Its fixed header has a Back button; the sheet body scrolls independently and the background is inert and
scroll-locked. Back and browser Back restore the selected name and focus. A bookmarked `symbol` URL opens the same
sheet; its Back action removes only the symbol, retaining sort, tab and other URL state. Focus enters the sheet,
Tab stays inside it, Escape closes it, and closing/restoring the desktop breakpoint releases the scroll lock.
All buttons and source disclosures have 44 px minimum phone targets. Each trip ends with a full-width Replay action.
The list keeps server order and names, without a 280 px nested phone scroll box.

The actual-component fixture now has **13 passing browser cases**: the original five source/transport boundaries,
four touch/deep-link flows at 412×915 and 390×844, two touch flows using A's immutable initial production-COPY,
and the existing actual-COPY render checks at 1440/412. Tests tap sort, a name, Back, provenance and Replay;
assert full sheet viewport bounds, no horizontal overflow, focus restoration, 44 px targets, real account names
and preservation of URL/source clocks. Replay here proves C's exact row-ID callback; shell B must separately prove
actual History → Replay navigation. No mock shell is described as the actual Replay screen.

Phone screenshots use the real viewport rather than a full-page capture of the hidden underlying names list.
`mobile-viewport-screenshots/impl-history-actual-axti-phone-detail-{412,390}.png` shows the actual nullable AXTI
COPY facts and source gaps; `impl-history-phone-names-{412,390}.png` shows the isolated missing-data protocol case.
The COPY is still the same initial A prototype (86 names / 13 AXTI observed rows), not final backend/schema or
Fidelity/basis acceptance. Final producer variants and B integration remain pending; this continuation does not
activate a schedule, alter financial aggregation or claim served acceptance.

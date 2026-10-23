# Watch — My Watchlist, System Suggests, Full universe (2026-10-23)

```
Status:      ACTIVE (code on branch feat/watch-my-watchlist-suggests-20261023; not deployed by this PR)
as_of:       2026-10-23T10:00:00-04:00
Measured at: origin/main 53aa1b619; live read-only measurements 2026-10-23 09:15–09:45 ET (served build 0f5bf2453)
```

Operator, 2026-10-23 (verbatim): "aesthetically, the watch list looks better, but I don't see stuff that I had starred
that I was watching ... And what's the difference between a proposals and the opportunities? They don't even align
right now. So where is my traditional watch list, the stuff that I was watching, and where is the automated watch
list, the stuff that the system is proposing for me?" — and at 09:25: "NAVN is saying add. When I actually sold that
yesterday, it should be tracked that formerly held ... if I made money with it or not. And you need to make it
tighter." — and "we should be able to filter on this information."

## What the page shows now

| Tab (slug) | What it is | Source |
|---|---|---|
| **My Watchlist** (`my-watchlist`, default) | Every name that is yours: starred, your personal watchlist, your ticker watch directives, names you added or proposed. Starred first, then by stage and conviction. Never dropped by a cap or by expiry — an expired signal shows "Review suggested". Each row: stage, conviction, stance, next trigger, what's missing, armed alerts (🔔), and for a name you sold the last trade and the re-entry advice. | `GET /api/v3/data-broker/watch-curation` |
| **System Suggests** (`suggests`) | The top 20 (`?n=10/20/30`, max 30) of the same ranked list as Full universe, minus what you hold, what is yours and what you dismissed (each skip counted). Rotation with a reason for every entry and exit. **Add to my watchlist** / **Dismiss** (30 days, restorable). | same |
| **Prospects** (`prospects`) | Every Watch name (yours and the system's) by stage. Your names are always listed (caps bound only the system's names) and never sit in Expired. | `GET /api/v3/data-broker/watch-prospects` |
| **Full universe** (`opportunities`, slug kept) | Research: everything the CIO curator scored (~1,640), ranked by conviction. Dense rows (19 px at 1440 wide, was ~42 px): # · symbol + position · conviction · type·stance · Risk / Reward · R:R in one cell · upside · last trade · re-entry · price; technical, sector, coverage and the curator's own values in the row detail. **Re-entry** quick filter = formerly held first. | `GET /api/v3/data-broker/watch-universe` |
| Trading → Proposals | Not a watchlist: sized trade ideas waiting for approve / reject. Pressing Propose on an actionable row creates one; watching never does. | — |

"How this page works" (under the tabs) states those five differences; every tab has a tooltip.

## Where the starred / operator names lived, and why they were missing (finding)

Measured 2026-10-23 09:20 ET (read-only):

| Store | Names | On Watch before this PR |
|---|---|---|
| `operator_starred_symbols` | 12 (ANET AXTI BETA CECO DXCM FATN FTH MRLN NUAI RDDT SMCI SWBI) | yes, but scattered: 5 in Expired (BETA FTH MRLN NUAI RDDT), no star shown |
| `watchlist_items` source `personal_watchlist` (= `portfolios/state/watchlist.json`, the traditional list) | 13 (PLTR HII GD BWXT AXON MAIN ARCC HTGC MSFT NVDA VCIT JEPI PPC) | only if held or in `DEFAULT_PRIORITY` |
| `watch_directives` kind ticker, created_by operator, active | 37 (SKYD DT INTC QURE PL NFLX S CXMT OUST JEPQ RGTI QBTS IBM GFS …) | 1 of 14 sampled (JEPQ) |
| `watchlist_items` origin_system/source operator | 73 | mostly no |
| `tos_watchlists` | 0 | — |

Why: `watch_intelligence._universe_symbols` built the Watch universe from `DEFAULT_PRIORITY` + stars + held + 40
screener names + "more active watchlist items" with `SELECT DISTINCT ON (upper(symbol)) … ORDER BY upper(symbol) …
LIMIT 120` over 5,648 active/researched names — the `DISTINCT ON` forced **alphabetical** order, so the 120 slots
went to `824430300` … `ACLZ`. Directives and the personal list were never read. Then the Prospects lanes capped
Setup forming at 25 (77 overflow by name only) and put expired signals in the collapsed Expired lane.

Fixed: `watch_domains.membership_operator()` reads all four sources (each failing on its own, reported); the
universe always includes them; the fill is active-first then most recently updated; lane caps and Expired apply to
the system's names only. Live dry run after the fix: 104 operator names, all on Prospects (actionable 7, forming 68,
re-entry 21, held 8, expired 0).

`watchlist_items.in_directive_watch` is TRUE on every starred row, so it cannot identify operator names; PR #1960
(open) narrows it to operator directives.

"Whispering" (speech-to-text): no list, tab or label in the code contains "whisper". The Watch tab nearest in sound
is **Watchpool**; "curated by the watch list" matches the Opportunities header "curated by the CIO".

## One ranking

System Suggests is the top of the Full universe list (the curator's `rank`, conviction order); every suggestion shows
its `#rank` there. My Watchlist, Suggests and Prospects rows come from ONE composition
(`watch_prospects.gather()`, cached 60 s), so a symbol shows the same conviction, stance and stage on all three.

Rotation (the focus-list rule of `lib/scalp_focus.py` on PR #1997, not imported — that module is uncommitted
scalp-specific scoring; the rule is restated in `watch_curation.rotate` and should be shared once #1997 lands):
enter at position ≤ N; a member stays while inside the top ⌈1.5 N⌉ eligible; an entrant displaces the weakest only
when it sits more than ⌈N/2⌉ below N. The previous membership comes from `rank_history` — the curator's projection
writer (`CIOOpportunityStore.write_projection`, the single writer) now carries the last 8 runs `[as_of, rank,
conviction]` per item. No new store. Until the curator runs once on this code, Suggests says "rotation reasons start
with its next run".

## NAVN — held status, round trip, re-entry

- **What happened:** the 09:00 ET curator run read `holdings.json` (it still listed NAVN; rewritten 09:15) while
  `positions_current` had dropped NAVN at the 10-22 16:24 sync. The 09:30 run already shows NAVN `re_entry /
  RE_ENTER`; the lag is the defect.
- **On Watch now:** every row carries `position_state` from the Watch held reader (positions_store reader batch #1):
  held / formerly held (not held + a sell in `trade_transactions` within 365 days) / never held. A sold name is Type
  **Re-entry**, status **formerly held · sold 10/22**, never Add-On/ADD; the curator's own values are kept in the row
  detail with a ⚠ note (AGENTS.md §26.5).
- **Last round trip** (CIO prospect lifecycle — `cio_prospect_builder.lifecycle_for` over schwab_round_trips,
  trade_transactions, stop_lifecycle, ticker_prices; the store is not live, so `watch_position_facts` runs the same
  pure functions and says so): NAVN 10/19 $25.64 → 10/22 $26.02, **+$189.73 (+1.48%), 0.36 R, trailing stop**,
  stop raised 5× $24.59 → $26.02, exit reads as noise (close-basis giveback 2.27% from the peak, close ≥ SMA20/50).
- **R:** 0.36 R is measured against the first observed stop by broker order id (24.59, order 1008345100877). The
  operator's figure 0.29 R uses 24.31 (order 1008345101170, placed the same minute). Both orders exist; which one was
  the initial risk is not recorded (no per-order timestamps in `stop_lifecycle`/`stop_last_known`).
- **Stop order defect found:** `stop_lifecycle` is rewritten newest-first each scan, so `cio_prospect_builder`'s
  `seq = id` ordering runs backwards (it reported "raised 1× from 26.02"). `watch_position_facts` orders by broker
  order id; the builder itself is the CIO owner's to fix.
- **Re-entry advice** (Re-Entry Desk classifier `reentry_rules.derive_intel_state`): NAVN WAIT, +3.7% above the
  zone $24.80–$25.10, or a close back above $26.02; alert levels 25.853 / 25.1 / 26.02.

### The curator's own held flag — reader batch #4 (APPROVED 2026-10-23)

`opportunity.gather` now asks the one held reader `watch_domains.held_positions(surface="opportunity")` and stamps
`position_basis` on every assessment (and `held_basis`, `held_basis_reason`, `held_overridden` on the curator
receipt). It reads `positions_current` (fresh) through **positions_store reader batch #4** — granted by the operator
2026-10-23 ~10:55 ET, verbatim "Yes, I approve" to "approve positions reader batch #4 (curator held flag)";
recorded in `config/data_source_authority.json` → `positions_store.approved_readers[batch 4]`; switch
`held.positions_store_reader_surfaces: [watch, opportunity]`. "Paper right" in the same reply is not read as a
paper_proposals grant. A stale, empty or unreadable store falls back to the holdings file with the reason. Dry run
after the grant: `held_basis {positions_store.positions_current: 1643}`, reason none, `held_overridden []` (NAVN
had already left the holdings file at 09:15). It takes effect on the served curator after release. Dry run 2026-10-23 09:40
(`scripts/cio_opportunity_curator.py`, no `--apply`): universe 1,642, `held_basis {holdings_accounts.holdings_json:
1642}`, reason `reader_batch_4_not_approved …`, `held_overridden []` (before the grant). PR #2000 (open) adds a complementary ledger
check (sale newer than the holdings snapshot → shown conflict).

## Position filters (all three lists)

URL parameters, applied on the server, combined with the existing filters; count chips from server facets; each
chip's tooltip is the server rule (`watch_position_facts.FILTERS[key].server`):

`position` held/formerly_held/never_held · `result` won/lost/breakeven (±0.25%) · `pnl_usd_min/max` ·
`pnl_pct_min/max` · `exit_cause` stop/trailing/target/manual/time/unknown (no classifier produces "time" yet) ·
`exited_within` 1d/1w/1m/older · `reentry` ready/near/waiting/invalidated · `reentry_dist_min/max` · `r_min/max`.
Sorts (`psort`): formerly_held_first, exit_date, pnl_pct, pnl_usd, r, reentry_distance. Prospects applies the filters
inside each lane and recounts.

## Writes

- **Add to my watchlist** → existing `POST /api/v2/watch/directives` (ticker directive, label "Watchlist",
  created_by operator). If an active directive for the symbol already exists (any creator) the response says
  `reused`; the page then offers ★ Star (existing `POST /api/v2/watchlist/star`).
- **Dismiss / Restore** → `POST /api/v3/watch/commands/suggest-dismiss|suggest-restore` (governed Watch commands
  module): one row in the existing `watchlist_events` log, `event_type watch_suggest_dismissed|restored`, `source
  operator`, payload `{by: <cc_auth principal, never the body>, reason, universe_rank, conviction}`. Read back by
  `watch_curation.read_dismissed` (latest event per symbol, 30 days). Not a broker action. `watchlist_events` has no
  registry domain; it belongs under the proposed `watchlist_membership` domain (§26.2).

## Re-entry context banner "502 · 502"

The banner (`SharedIntelligenceBridge`) reads two saved caches through `/api/v2/ui/prefs/get`. The served API
process was SIGKILLed at 09:30:57 ET (restart counter 2; earlier restart 09:15:05; unit `MemoryHigh=1.5G`,
`MemoryMax=2G`, peak 1.5G) — during the outage `tailscale serve` answers 502. The banner's fetch hook never cleared an
error after a later success, so one 502 stayed on screen. Fixed: success clears the error; a gateway error reads
"Re-entry context unavailable — the Command Center API did not answer (…); retrying". The kill itself (memory
pressure on `portfolio-server`) is reported, not fixed here.

## Files

`scripts/lib/data_broker/watch_curation.py`, `watch_universe.py`, `watch_position_facts.py` (new);
`watch_prospects.py` (gather, operator rows, filters), `watch_domains.py` (membership_operator,
OPPORTUNITY_SURFACE), `watch_intelligence.py` (universe), `opportunity.py` (held_basis), `cio_opportunity_store.py`
(rank_history), `scripts/cio_opportunity_curator.py` (receipt), `scripts/api_v3_watch_commands.py`,
`scripts/api_v3_data_broker_watch.py`, `scripts/api_v2.py` (routes), `catalog.py`; UI `WatchHub.tsx`,
`WatchMyList.tsx`, `WatchSuggests.tsx`, `OpportunitiesHub.tsx`, `WatchProspects.tsx`,
`components/watch/PositionFilterBar.tsx`, `SharedIntelligenceBridge.tsx`, `lib/watchListsModel.ts` (+ test in `npm
run build`), fixture `src/fixtures/watchLists.fixture.ts`, e2e `e2e/watch-lists.spec.ts`; tests
`tests/test_watch_lists_20261023.py` (gate `watch_lists_20261023`).

## Operator decisions (§17)

1. ~~Grant positions_store reader batch #4~~ — granted 2026-10-23 ("Yes, I approve").
2. Merging this PR changes what Watch opens on and ranks (My Watchlist default; Suggests = top of the curator rank).
3. Optional: register `watchlist_events` suggest decisions under the proposed `watchlist_membership` domain.

## Choose what you watch (operator 2026-10-23 ~10:55: "I still don't see an area where I can select what I want to watch")

- **＋ Add symbol** box at the top of My Watchlist, always visible: typeahead by ticker or company name
  (`GET /api/v3/data-broker/watch-symbol-search?q=` — tickers from the identity registry `by_symbol`, names from the
  broker instrument feed and the curator; CUSIP keys never offered), optional note, Enter or click to add.
- **★ / ☆ on every row** of My Watchlist, System Suggests, Prospects and Full universe: one click adds to / removes
  from My Watchlist. "Add" in Suggests is the same action.
- **Remove** on every My Watchlist row (with an optional reason).
- One write: `POST /api/v3/watch/commands/mine {symbol, action: add|remove, note}` —
  add = the operator star (starred_by = the signed-in user) + `watchlist_events` `watch_mine_added`;
  remove = unstar + archive the operator's own active ticker directive(s) for it (governed writer) +
  `watch_mine_removed`. `membership_operator()` hides a name whose latest add/remove event is a removal unless a
  membership reason is newer. Watching only — no order, size or stop (MBI_BEHAVIOR = 0).
- Empty state: "Search a ticker above, or ★ any row in Suggests/Full universe."

## Playwright (fixtures only)

`e2e/watch-pages.spec.ts` drives every tab at 1440 px and 412 px: My Watchlist (add box, typeahead, add with note,
star off, Remove with reason, detail, filters, empty hint), System Suggests (star, Add, Dismiss), Prospects (lanes,
star, filters, detail), Full universe (NAVN formerly held, row detail with alert levels, star, position filters,
Re-entry preset) — 14 tests with `watch-lists` and `watch-prospects`, all green. Every `/api` call is fulfilled in the
browser; the preview ran with an offline proxy so nothing reached `:7777`. Screenshots (`WATCH_SHOTS_DIR`):
`~/.cache/rtc/watch-playwright/*_{1440,412}.png`. The live read-only smoke was dropped (coordinator: agent traffic
on `:7777` caused today's `portfolio-server` SIGKILLs).

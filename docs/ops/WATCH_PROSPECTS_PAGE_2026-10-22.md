# Watch — prospect lanes (the Gate 3 Watch redesign, 2026-10-22)

```
Status:      ACTIVE (code on branch feat/watch-redesign-20261022; not deployed by this PR)
as_of:       2026-10-22T16:30:00-04:00
Measured at: origin/main b9804fa57 / not measured live (built and tested against the captured 2026-10-22 ~11:30 ET payloads)
```

Operator directive 2026-10-22: build the Gate 3 Watch mockup (`Watch.dc.html`, "Watch — one CIO prospect record";
no changes requested). `/v3/watch` now opens on **Prospects**: your prospects in the order you should look at them,
one row per security, one next step each. The previous Intelligence view stays one release as **Classic view**
(`/v3/watch?tab=intelligence`).

## Where it lives

| Piece | File |
|---|---|
| Projection (read-only, zero provider calls) | `scripts/lib/data_broker/watch_prospects.py` → `GET /api/v3/data-broker/watch-prospects` (`scripts/api_v3_data_broker_watch.py`, route in `scripts/api_v2.py`, catalog entry `watch_prospects`) |
| Shared composition | `watch_intelligence.compose_universe()` — the Watch universe with cards, membership, held and `watch_decision.v1` attached; `list_watch_intelligence` and the prospects adapter both read it |
| Page | `apps/command-center-v3/src/pages/WatchProspects.tsx` (default tab of `WatchHub.tsx`) |
| Page model (alerts tie-up, tones, tooltips) | `apps/command-center-v3/src/lib/watchProspectsModel.ts` |
| Fixture (captured, regenerate from a capture only) | `apps/command-center-v3/src/fixtures/watchProspects.fixture.ts` |
| Tests | `tests/test_watch_prospects_20261022.py` (gate `watch_prospects_20261022`), `src/lib/watchProspectsModel.test.ts` (in `npm run build`), `e2e/watch-prospects.spec.ts` |

## Where the record comes from

**When the CIO prospect store is live** (AGENTS.md §26; `docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md` §5.3),
the adapter reads `lib.data_broker.cio_prospect.get_prospects()` and only maps each record's `stage` to a lane
(`from_cio_prospect`; `source = "cio_prospect"`); the one next step comes from the same `next_step()` rules. That
module is being built on its own branch (`feat/cio-prospect-p0-p1-20261022`, PR #1944, checked against its head);
the mapping follows its record shapes as read from that working tree (`cio_prospect_builder.assemble`: conflicts
`{field, values[2], resolved}`, components `{name: {value, weight, source, evidence_at}}`, next_trigger
`{kind, entry_zone, entry_ref, invalidation_level, observed_by}`) and is re-checked when that PR lands. **A shadow
build is not read** (`source.kind == "shadow"` → interim, `cio_prospect_status: "shadow"`): moving Watch onto the
shadow is the P3(b) reader batch, an operator decision.

**Until then — interim**, labelled on the page and in the payload (`interim: true`,
`source_label: "interim — CIO prospect store not live"`). The adapter builds the same shape from today's sources:

| Field | Interim source |
|---|---|
| conviction + components | `cio_opportunity_projection.json` via `CIOOpportunityStore` (registry domain `opportunity_assessment`) — `conviction`, `factors{score, weight, detail, source}`, `factors_missing`, `rank`, `stance`, `position_status` |
| stage, status, expiry, actionability | `watch_decision.v1` on each Watch card (`config/watch_decision_standards.yaml`) |
| Trade AI state | the rockville decision projection already on each card (`trade_ai_state`) |
| held | the one Watch held reader `watch_domains.held_positions(surface="watch")` (positions_store reader batch #1) |
| re-entry | `watch_decision.reentry_rows()` (the deterministic re-entry desk) — names outside the Watch universe that the desk marks NEAR ENTRY / READY TO REVIEW are added |
| identity | `identity_registry.lookup_symbol` (security_guid / issuer_guid; not CONFIRMED → "Identity unresolved" in what's missing) |

## Lanes — one per security (curation, applied in the adapter)

Evaluated in this order; the first that holds wins.

1. **Manage (held)** — every held name, whatever its signal says (a held name is managed, never entered; 2026-10-22 audit).
2. **Expired** — not held, and the decision is `expired` / `invalidated` or past `expires_at`. Closed automatically;
   returns when new evidence arrives. A desk-only re-entry row older than 96 h is also expired.
3. **Actionable now** — not held, signal active, a proposable rule fired (`proposal_ready`, `plan_ready_strong`,
   `plan_ready`, `reentry_confirmed`) or the re-entry desk says READY TO REVIEW, and Trade AI is not
   DETERMINISTIC_FAIL / BLOCKED / AVOID.
4. **Re-entry near** — the desk says NEAR ENTRY, or the decision's category is re-entry.
5. **Setup forming** — everything else that is live.

Within a lane: conviction high → low (no conviction last), then decision priority. **Size caps:** actionable 12,
forming 25, re-entry 20, manage 60, expired 150. Rows over a cap are returned by name (`overflow`) and the page
prints them — never silently dropped. Each lane's `count` is the full count.

## Conflicts — shown, never resolved (AGENTS.md §26.5)

Each conflict keeps both values, both sources and both times. The adapter flags:

- `stance_vs_review` — conviction stance vs the CIO watch review verdict (different stance family);
- `stance_vs_synthesis` — conviction stance vs today's desk synthesis;
- `ownership` — the conviction record's `position_status` vs the held reader;
- `trade_ai_block` — Trade AI failed a hard check while the stance or the re-entry desk says go.

Stance families: positive (ADD, BUY, BUY_SETUP, RE_ENTER …), neutral (HOLD, WATCH, WAIT …), negative (SELL, TRIM,
EXIT, AVOID …). Nothing picks a winner; "Ask the CIO to review" queues the existing CIO symbol review
(`POST /api/v3/opportunities/{symbol}/review-request`).

## The one next step

| Step | When | What it does |
|---|---|---|
| **Protect first** | held and a risk rule fired (`held_negative`, `held_blocked`) or the stance is negative | link to Open Trades (`/v3/trading?tab=Open+Trades&symbol=X`) |
| **Resolve conflict** | any conflict on the row | opens the record with both sides and "Ask the CIO to review" |
| **Propose** | Actionable now | opens the existing `WatchlistProposeModal` (`POST /api/v2/watchlist/:sym/propose`), seeded with the plan's reference levels; the operator sizes it and it goes to Proposals for approval. The endpoint still requires the symbol on the active watchlist and returns its own error otherwise |
| **Set alert** | Setup forming / Re-entry near | opens the existing `ReEntryAlertArmModal` (`POST /api/v2/watch/alerts`, note tag `watch-prospect`) |
| Review add-on | held, stance positive | link to the symbol intelligence page |
| Decide hold/exit | held, conviction < 50 | link to Open Trades |
| View position | held otherwise | link to Open Trades |

Reference levels carry `_ref` keys (`entry_low_ref`, `stop_ref`, `target_ref` …) so no key is a
`cio_instrument_record.BEHAVIOR_FIELDS` name; a test walks the whole payload. `MBI_BEHAVIOR = 0`.

## Drawers

- **Alerts tied to prospects** — every active Watch alert either belongs to a prospect (same symbol, any lane,
  overflow included) or is listed as an orphan with the reason from its own note (trim ladder, hedge). On the
  2026-10-22 capture: 16 armed → 8 belong to a prospect · 8 orphaned.
- **Expired and invalidated** — the Expired lane by symbol.
- **How this page works** — the one-record design, and while interim, the sources and caps above.

## Same record everywhere

The detail panel lists what each surface shows. Interim, only the sources this adapter reads are joined (Trade AI,
Open Trades held, CIO curator rank, re-entry desk); Home, Options and Telegram say "not joined (interim)" instead of
guessing. After the switch to `cio_prospect` every surface reads the same record.

## Measured on the capture (2026-10-22 ~11:30 ET)

`build_watch_prospects` over the captured Watch cards (188), `cio_opportunity_projection.json` (1,586 items) and the
re-entry desk (92 rows): actionable 5 · forming 90 · re-entry 19 · manage 20 · expired 67; 13 conflicts outside
Expired. NAVN (held, 88): desk synthesis SELL vs conviction WATCH and an ownership conflict → Protect first. SPCX
(held, 80.3 ADD): CIO watch review HOLD → Resolve conflict. FATN: re-entry desk NEAR vs Trade AI deterministic fail.

## Operator decisions this touches (§17)

- **Changing what is ranked onto an operator surface** is §17. The operator directive "build it" approved the
  mockup's order (lane, then conviction). This PR does not merge itself; merging it is that decision.
- The switch from the interim adapter to the `cio_prospect` projection is the P3(b) reader batch of the data
  foundation (CIO_PROSPECT_DATA_FOUNDATION.md §7) — its own operator decision.

## Not done here, stated

- The Classic view is removed in the release after this one (its own PR).
- Stops are not read: "Protect first" fires on the risk rules, not on a missing stop (no data-broker stop projection
  exists; `broker_stops` is a proposed registry row).
- No CI workflow runs `e2e/watch-prospects.spec.ts` (same as the options desk spec); it ran locally against
  `vite preview` (3 passed).

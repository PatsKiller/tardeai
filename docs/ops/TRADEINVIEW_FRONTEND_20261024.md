# WP-29 B: TradeInView tabs, Journeys, Calendar and Replay

Design-Task: DSN-20261024-tradeinview-tabs-replay-P1-T1

Worker: `codex-tradeinview-b-20261024`; claim `20261024T201519Z-codex-5aaefe7f`.
Accepted base: `8b6cd3be6d9776d3051ea24fbbcfc65248431c45` (batch 21, PR #2071).
The phone continuation locally merges accepted `d635873e1063efb8a9ff8e8ce542654ed2ef7654`, preserving the exact union of accepted and B native-build checks.

## Checkpoint status

This is an incomplete local implementation checkpoint, not a publication or acceptance receipt. The coordinator/operator owns remote publication, merge, release and runtime verification. No push is attempted.

The operator's full SPEC and Main/Calendar/Replay reference markup were read before implementation. Reference layouts were rendered with all external resources blocked and inspected locally. The mockups' `renderVals()` sample values remain confined to the reference rendering; they are not product data or new shipped fixtures. House design/chart tokens supply the implementation colours and typography.

The frontend implements bookmarkable Journeys, Calendar, Replay, Holding history and Classic tabs, with compatibility for `?view=classic`, classic tab names and the existing session handoff. Holding history currently has an integration dependency slot; the real package C component must be wired before this package can be published. There is no fabricated History data or placeholder screen.

Journeys displays Awaiting fill with info tone while retaining the unconfirmed machine kind. The selected record shows its existing disagreement evidence once and retains original sources/timestamps. Server-provided counts, account labels, receipt chips, reconciliation facts and condition counts replace browser-calculated display statistics. Missing sync evidence remains a gap rather than a fill/stop timestamp relabelled as a successful sync.

Calendar consumes an explicit server month and server totals, day/week dates, event classifications, coverage, account names and gaps. It replaces the classic journal's duplicate calendar calculation. The frontend formats and places these facts; it does not compute financial totals, win rates or green-day counts. Other events retain their supplied type/source, and absent sources are explicit.

Replay addresses actual trade IDs through `stored_only=1`, displays only server-supported intervals and reuses the existing chart with supplied data. Even loading or missing data in the new embedded path cannot fall through to legacy provider fetching. Close-only observations render as a line, without fabricated OHLC. Server performance measures retain their basis/missing reasons; a session-range proxy is explicitly labelled as such. The comparison uses trade identity rather than a symbol that could identify several different lots. Original legacy chart callers remain supported.

## Evidence boundaries and remaining work

The backend contract is owned by package A. The UI field binding map is [in this packet](packets/tradeinview-frontend-20261024/ui-field-bindings.json); A owns the complete store/column/writer lineage in its master report. The frontend uses the agreed `TradeCalendar@v1` / `TradeReplay@v1` fields and additive Journey fields, and rejects incomplete payload envelopes with a visible gap.

Current focused model tests, the TypeScript checkpoint and the native frontend checkpoint pass. Existing actual-App Journey and Classic navigation regressions pass (3 tests). A Calendar-only preliminary browser run passed ten cases: populated, empty, day drawer, unavailable source and delayed/wrong-query response at 1440/412, using A's pure builder and synthetic unit inputs. It verifies source totals, Replay links, phone controls at least 44×44, minimum visible text contrast 6.23:1 and zero unexpected/mutating/external traffic. Its [compact receipt](packets/tradeinview-frontend-20261024/calendar-preliminary-proof.json) records tested source hashes and scope; this remains preliminary until the frozen A/C integration is verified.

The staged checkpoint also passes the dark-contract, retention, test-coverage and host-path guards with no new violations, plus 44 isolated registry tests with injected scheduler discovery. These checks do not establish host scheduler state. Both strict real-tree CIO completeness checks pass (2 tests, hidden database driver). Final native build, backend-generated fixtures, all-screen screenshots and integrated repository gates remain required.

Query-scoped bodies remount when month/account/names or trade/interval identity changes. Display guards also reject responses for another identity, including a nested trip that disagrees with the Replay envelope. The delayed Calendar fixture proves the old total disappears during navigation and cannot reappear when the previous month's valid body is deliberately returned for the new query. Same-query retained data can still show its original source clock; no shared API-hook behavior was changed.

## Phone Journey continuation

The operator's mobile-first directive requires immediate detail after tapping a Journey. At ≤820px, selection now opens a focused full-screen sheet with Back navigation, contained scrolling and 44px targets. The selected trade comes from the URL; a phone list does not silently select its first trade. A tap pushes `?trade=…` while retaining unrelated query parameters, and Back/Forward closes/reopens the sheet. Direct links without in-app history clear only their trade/symbol selection on Back. Filters remain URL-backed. The row's primary Journey action is full-width, and detail facts use two phone columns. Original financial/source facts and the existing advisory alert flow remain unchanged.

Nine actual-component navigation, direct-link and wrong-detail cases pass at 1440×1100, 412×915 and 390×844. Phone cases actually tap Journey, Back, a filter and a filtered Journey, assert full-viewport focused sheets and ≥44px visible controls, and exercise browser Back/Forward. A deliberately mismatched detail response cannot contribute another trade's chart; the recorded list facts remain with an explicit gap. Screenshots are true phone-viewport captures beside the approved mockups. The [phone proof](packets/tradeinview-frontend-20261024/journey-mobile-proof.json) binds all source/input hashes and records zero mutating, unexpected, provider or live-server traffic.

This independent proof uses the existing generated NAVN broker-projection fixture's **three actual fixture rows**, not an invented 57-row financial population. It does not replace the final frozen A/C source, endpoint-copy receipts, all-screen states or integrated acceptance. The 390 detail and 412 filtered-list screenshots were inspected.

The phone checkpoint's native frontend build, existing actual-App Journey/Classic/advisory-form regression (3 tests), hidden-driver registry/workflow profile (163 tests), both strict real-tree CIO checks and all four no-new ratchets pass. Commands and immutable log hashes are in the [phone validation receipt](packets/tradeinview-frontend-20261024/journey-mobile-validation.json). The existing Vite bundle-size advisory remains. No full B `PUSH_NEEDED` is issued while its A/C integration gates remain open.

Before final `PUSH_NEEDED`:

- Integrate package A's actual generated fixtures and exact source head, preserving valid source identity and null/coverage semantics.
- Integrate the real package C HoldingHistory component and replace the temporary dependency slot.
- Verify store-projected stop-step timing without collapsing multiple real observations silently.
- Produce all Journeys, Calendar and Replay states at 1440×1100, 412×915 and 390×844 beside the operator mockups as `impl-*.png`, using isolated static fixtures with no live server, provider or database traffic and real phone taps.
- Run the native frontend profile, hidden-driver Python/strict record-edge checks and the required dark-contract, retention, coverage, host-path, registry and documentation gates.
- Commit the final verified source, append exactly one `PUSH_NEEDED` with the real publication command, retain the claim and leave final publication/release to the coordinator/operator.

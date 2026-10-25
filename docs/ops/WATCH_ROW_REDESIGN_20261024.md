# WP-29: Watch company, setup and price cards with server-side view controls

Design-Task: DSN-20261024-watch-row-redesign-P1-T1

Worker: `codex-watch-redesign-20261024`; retained claim `20261024T161036Z-codex-5ced82f6`.
This is a local source delivery. The coordinator/operator owns publication, merge, release and runtime acceptance.

## Result and source boundaries

My Watchlist and the shared Prospects/Suggests row renderer now use the operator's five-column desktop card and phone layout: company, setup/catalyst, price versus levels, conviction/stance and existing next action. House tokens supply colours, typography and rails. The phone Support/Price/Resistance strip keeps ownership names beside the zone, uses 44px button targets, and exposes secondary controls through keyboard-operable More actions. The highest existing block appears once; the full original conflicts and source declarations remain in the record panel. No decision, source confidence, level or readiness is manufactured by this rendering change.

The implementation preserves the exact corrected C1 company-facts head `7ab9a37c9bd055608d4b516c21670c720d81b874` and C2 freshness/levels head `593246bb84bbe821e67f672092e23e324a155458`, merged locally into base `e5fa288ecc6971d1a55a79f7e3ba5bbbb46c5dd0` as `c7463a4e3` and `313afad70`. C1 source/consumer record edges remain traceable through the actual card child. The redesign owns presentation and narrowly scoped stored-row query operations; canonical company/market records, providers, stores, recommendations and writers remain unchanged.

C2 original price, source and timestamp are retained. The compact line says **Closed session · date · intraday time ET** for a stored intraday LAST from that session; it never claims an official closing price. The full source, original timestamp, missing/stale reason and selected/broken level provenance are accessible through Source details and descriptions. One unknown-level-time footnote replaces repeated diagnostics. Missing or crossed references remain explicit, and missing price creates no ladder marker. On 503/403 refresh failure the retained data becomes **Last snapshot**; a 403 still stops polling. The existing weekday/session helper retains its documented holiday/early-close limitation; this change adds no calendar.

Prospects rows without a canonical market-facts projection display their existing price/level references with **source/freshness not exposed** rather than inventing provenance. There is no Watch-only data store or new per-process fetching. Existing add/remove/star, alert, review, propose and navigation handlers/targets remain in place. This package adds no broker, order, stop, scheduler, provider, model, live-server or secret operations.

## Server-side view controls

The approved ADDENDUM extends only the existing CC data-broker read projection:

- `psort` in the page URL maps to the existing server `sort` argument. Conviction header cycles descending, ascending, default; Setup toggles its stored-stage order. Header cells expose `aria-sort`.
- Finite scores precede n/a in both directions, including starred missing-score rows. Within scored rows existing starred priority remains first, followed by score, stance severity (EXIT, TRIM, HOLD, WATCH, RE-ENTER, ADD), then symbol. Zero is a real score; booleans/nonfinite values are missing.
- Setup uses existing Actionable, Re-entry near, Forming, Held, Expired, Missing categories, preserving starred priority and then conviction/symbol ties. It changes no stored lane or judgment.
- Conviction presets, stance choices, position filters and setup subgroups combine AND. Choices within stance or setup category combine OR; Blocked and catalyst selections form separate AND groups. Selecting both catalyst choices admits either.
- Has catalyst requires a CURRENT headline from the canonical CIO company-facts projection; a raw overlay or stale headline does not qualify. Facets omit only their own group while retaining the other filters. Clear filters resets these controls and the view sort.
- **My Watchlist is uncapped:** filtering, sorting and facets evaluate its entire enriched population. Filtered counts show the selected population against the original total.
- **Prospects remains a capped shown-row window:** controls explicitly say so. Sorting reorders shown items without dropping total counts or overflow identities; filtering preserves and labels unevaluated overflow. This package does not pretend to sort unseen rows or change the underlying ranking/caps.

## Verification and review

Final commands, source digests,14 required PNG digests and fixture request receipts are in [the packet](packets/watch-row-redesign-20261024/validation.json). All screenshots are also beside the operator's original mockups in `persistent-state/data/coordination/handoffs/watch-row-redesign-20261024/impl-*.png` for side-by-side review. Seven required states are held, formerly held, never held, conflict, no catalyst, missing level and missing price at 1440/412.

| Check | Local result |
| --- | --- |
| Pure stored-row Python integration, existing list regressions and both strict real-tree record-surface checks | 36 passed, with psycopg2 hidden; new files staged before final completeness run |
| Pure presentation/model fixtures | 22 new card assertions; 35 retained C2 assertions; existing Watch list/prospect model checks |
| Actual MyList card/source/query fixture | 14 state cases + 2 server-backed URL interaction cases; pinned clock; no external/unexpected/mutating traffic or page errors; no overflow; visible text contrast ≥ 4.5; all visible phone card buttons including opened secondary actions ≥ 44px |
| Actual MyList failed-refresh fixture | 6 cases: 1440/412 × normal/503/403; original source/asof stable and keyboard source details available |
| Existing App Watch/account/company/market browser suites | 47 passed on an isolated static preview, empty env, disabled proxy; all API responses mocked |
| Frontend native profile |`npm run build` passed, including house token/style checks; existing chunk-size advisory only |
| Repository ratchets and docs |Host-path and coverage `--fail-on-new`, generated INDEX check; exact receipts in packet |

Tests follow the real layout: More is opened before secondary action clicks and the mobile record overlay is explicitly closed before underlying filters are used. Original assertions about write routes, source facts, account names, navigation targets, zero/sub-cent/missing values and denied refreshes remain covered. A capped-population regression caught and now prevents a sort-only query from silently erasing overflow/counts. The screenshot fixture clears focus only after proving Escape restores it; product focus styling remains enabled.

The local required checks do not establish remote CI or served-runtime acceptance. After publication, the coordinator should review the 14 state PNGs against the approved mockups, run the new attempt-specific fixture workflow on the final integrated head and use the normal authorized release procedure. Keep the claim and task until coordinator acceptance; no runtime-complete status is implied.

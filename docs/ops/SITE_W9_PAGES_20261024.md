# W9 page fixes and shared phone details — 2026-10-24

Status: DRAFT
as_of: 2026-10-25T00:13:48.181448+00:00
Measured at: exact W9 frontend 10c6aca9773e28418625dcd5d9b55838c9989d4e plus four W2 dependency blobs at 6d84c466b3bb114b7e936b0f84df47ff0ec1c1ac; runtime not measured

Design task: `DSN-20261024-w9-nonops-pages-P2-T1`. Worker only; no publication, merge, deployment, broker call, or scheduled-job change.

## Scope and ownership

The initial ops-page work was preserved in local checkpoint `34139b362` and handed normally to W4. Its old claim was released. This branch contains the independent non-ops work, the requested shared mobile drawer, and the shared conflict presentation dependency.

W2 normally froze and released `WatchMyList.tsx` and `WatchProspects.tsx` at `a20167e5fb5909e48b8aaf1dc721c32f22555e59`. W9 then extended its claim and preserved that paging source. W2 retains ListPager/model/CSS dependencies, Active Trader and Communications. Exact dependency files are consumed only in private combined validation; W9 does not edit retained paths. AskCioBar/MyQuestions and App/navigation remain with their existing owners.

## Resulting page behavior

- Research Intelligence retains a deliberately empty search across polls. A same-page symbol link updates the search; typing and Clear update the URL while retaining unrelated context. Browser Back restores the previous query.
- Trading and Watch show descriptive section labels. Owned Trading/Research files use semantic color variables, including valid token-based alpha fills rather than appending a hex alpha suffix to a CSS variable.
- Classic Watch links to the existing gated rollback route with its required query parameter. Its phone inspector and Full universe record details use the shared full-screen sheet rather than a panel below the list.
- Shared `MobileDetailSheet` owns focus, keyboard containment, scroll locking and a visible Back control. `useMobilePageDetail(queryKey)` owns record selection in URL history. Existing `DetailDrawer(ctx,onClose)` remains compatible and uses the same shell on phones. Desktop keeps its existing drawer layout.
- My Watchlist and Prospects render the unchanged `row.conflict_section` envelope. Resolve opens a focused full-screen phone sheet or desktop side panel; the shared sheet alone reads the selected durable record, history and decision. A submitted review request cannot clear the finding. Missing engine/record output stays an explicit gap.
- Existing W2 paging uses the server's actual `next_offset`; full-list counts are preserved. Phone record selection and browser Back use URL history.
- Trading's manual-entry grids adapt to two columns on phones through a page-scoped style; the child component's execution logic is unchanged.

## Field trace

| UI or interaction | API / field | Authoritative store or source | Writer / owner |
|---|---|---|---|
| Research query, empty result and retained scope | `/api/v2/research-intelligence?q=…`; `items`, `stats.matched`, `stats.universe` | Existing Research Intelligence reader of `hermes_research_intelligence`, `user_research_topics`, `topic_monitor` and feedback | Existing research producers; `scripts/lib/research_intelligence.py` is the reader |
| Research title and article detail | Same feed; `items[].title`, `symbol`, summary and article fields passed in `DrillContext.rows` | Same existing stored research inputs | Existing research producers; no new writer |
| Trading section labels | Existing `tab` / `section` URL model; display copy only | Browser URL, existing `tradingDeepLink` parsing | Operator navigation; no backend fact added |
| Trading scanner colors and existing displayed values | Existing `/api/v2/trade-ai/scanner` fields | Existing scanner projection and `trade_ai_scans` | Existing Trade AI orchestrator; unchanged by this work |
| Full universe row and detail | `/api/v3/data-broker/watch-universe`; `items[]`, position fields, risk/reward, round trip, re-entry | Existing `watch_universe` projection, curator and broker-synced Watch position reader | Existing registered owners; no page-side ranking or statistics added |
| Full universe account names | `held_accounts`, `held_account_labels`, last-sell account label | Existing account display registry through the existing label helpers | Registry owner; names only |
| Classic card and inspector | `/api/v3/data-broker/watch-intelligence`; cards, company description, reviews and source metadata | Existing Watch data-broker projection | Existing research and Watch owners |
| Classic rollback link | `/watch-legacy?legacy=1` | Existing `WatchLegacyGate` in App | Existing route; no authorization change |
| Mobile record selection / Back | `detail` or caller-supplied query key; generic drawer uses `detail-drawer` | Browser history only | Shared UI helper; no durable store |
| Shared conflict headline | Whole Watch `row.conflict_section` `{findings, headline, gap}` | W10 engine/ledger through canonical batch adapter | W10 engine; W2 projection owner; no page-side classifier |
| Conflict facts | `ConflictFinding@v1` sides, summary, clearing condition, owner and next run when supplied | Same engine finding; account values use existing account-name formatting | W10 / W1; absent fields remain explicit gaps |
| Conflict selection | `?conflict=<backend finding key>` via shared `useConflictSheet` | Backend key; browser history | Engine owns key; UI does not invent one |
| Saved review state/history/decision | Sole selected GET `/api/v3/conflicts/{encoded-key}`; bare `ConflictRecord@v1` (optional transport wrapper), key/state/subject/decision/history | `data/conflicts/conflict_events.jsonl`; keyed/schema/key/history guard prevents another record appearing | W10 ledger and governed producers; `DECIDED` remains pending re-evaluation, only `CLEARED` says cleared |
| Review request | Existing explicit POST `/api/v3/opportunities/{symbol}/review-request`; symbol response plus exact row/record GUID binding | Existing review owner queue; actual receipt/readback must precede ledger `review_queued` | Existing governed CIO writer; C3/root queue-to-ledger integration pending. UI acknowledgement says submitted while waiting for durable history |

The shared conflict primitives do not compare values, apply freshness thresholds, infer compatible actions, or resolve findings. A missing engine result stays a visible gap. A null server headline produces no flag. Operator decisions belong to W11's shared Approvals flow; Watch does not POST a conflict decision.

## Validation and limits

The fixture driver bundles the actual page components and real `useApi`. All requests are intercepted; an existing Finviz chart-image request in the generic drawer receives a local placeholder. Any unmocked external request, unexpected read or mutation fails the proof.

The hidden-psycopg2 affected suite has 64 passes and 20 failures. A clean `origin/main` worktree at the same base produces the identical 20 failure IDs: unchanged `watch_canonical_quote` reaches `None.cursor()` when psycopg2 is deliberately absent. No failure has been hidden or counted as a pass. CIO completeness has 23 passes. Registry, retention, test coverage and host-path checks pass. Final receipts and screenshots are recorded in the evidence packet as they complete.

W10's exact synthetic final-matrix R11 and T0/T1 sections replace the older reference sample, with source head and rulebook SHA recorded in each fixture. The shared fixture proves engine order/other-finding selection and state/history/decision display. Six actual My Watchlist/Prospects cases at 1440×1000, 412×915 and 390×844 prove 104-row Resolve, focused visible details, ≥44px taps, mocked request plus durable queued history, DECIDED distinct from CLEARED, evidence/Back, actual next offset 17 rather than requested limit 25, missing-engine gaps and a mismatched-key guard. Traffic receipts show zero external, unexpected or unapproved mutation requests.

The initial frozen W2 dependency package failed the native token guard in ListPager/WatchRecordCard.css and type checking in its model test. W2 corrected its retained files in committed source `6d84c466b3bb114b7e936b0f84df47ff0ec1c1ac`. The exact private combination of W9 `10c6aca9773e28418625dcd5d9b55838c9989d4e` plus those four W2 dependency blobs now passes the full native build and refreshed nine actual-page browser cases. No retained W2 worktree path was edited. `combined-source.json` and browser input hashes identify every accepted blob.

The standalone branch still requires W2's retained dependency source to be integrated before publication. No PUSH_NEEDED is emitted for a base that lacks ListPager. The coordinator has exact minimal source packages and the dependency order.

This is not acceptance of the 31-flag golden replay, a working review producer, a live conflict resolver lane or a deployed Watch Resolve fix. C3/root must bind actual persisted queue receipts to ledger progress; W10 owns durable resolution, and the applicable operator gates remain. No endpoint was implemented here, so this change does not claim a new real-tree endpoint acceptance test.

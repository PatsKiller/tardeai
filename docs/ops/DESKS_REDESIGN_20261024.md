# Restored desks: shared frame (board 0)

**Status:** Local frame candidate; route registration and browser proof pending.
**Date:** 2026-10-24
**Authority:** READ_ONLY_ADVISORY

Design-Task: DSN-20261024-desks-frame-a-P1-T1. Approved layout/copy:
`handoffs/desks-redesign-20261024/mockups/Main.dc.html` in persistent coordination.
This first change provides the shared frame, source-clock reader and restored rail.
Boards 1–4 follow on another branch after this frame lands. W6/W7 and the seven
W4 operations pages consume the same component; `JobsHealth` remains W4's single
shared job-execution component. No duplicate jobs-health calculation is added here.

## Consumer contract

```tsx
import DeskPage, { DeskGap, useDeskTab } from '../components/DeskPage'

<DeskPage
  title="Desk name"
  purpose="What the operator does here."
  tabs={[{ id: 'overview', label: 'Overview' }]}
  defaultTab="overview"
  tabAliases={{ legacy: 'overview' }}
  sources={[{ id: 'source', label: 'Source name', asOf: response?.as_of,
    laneIds: ['exact-registered-lane-id'], maxAgeHours: 48,
    gap: response ? undefined : 'The source has not answered.' }]}
  decisions={decisionsFromTheCanonicalQueue}
  decisionGap="The decision queue has not answered."
>{activeTab => <ActualPanel activeTab={activeTab} />}</DeskPage>
```

`asOf` must be the underlying source's explicit timestamp with timezone. Do not
pass a request/receive time, last trade date, file mtime or invented midnight.
`laneIds` names exact registry IDs. An omitted ID says the writer is unidentified;
a queried ID absent from a successfully read registry is `NONE`. An unreadable
registry is unknown, never `NONE`. No page should reinterpret `ACTIVE` as healthy.
The optional freshness window belongs to the page's actual source contract;
the frame invents none. No source/decision result means a reason is shown.

`useDeskTab(tabs, defaultTab?, aliases?)` returns `[activeTab, setTab]` for pages
with existing conditional panels. Both the hook and frame use the URL as state:
valid tab IDs and display labels match case-insensitively; tabs survive reload/back/forward, aliases and invalid tabs normalize with
replace, and unrelated query parameters and the hash are preserved. A page may
use the hook and render ordinary children instead of a function.

`DeskGap({title, reason, children?})` is the shared in-panel notice. Place it
inside the panel whose evidence is missing. It never conceals other panels.

## Field trace (zero-hallucination contract)

| On-screen field | UI input / API field | Store or rule | Writer / evidence |
|---|---|---|---|
| Title, purpose, tab labels | DeskPage props | Approved board copy in page code | Reviewed UI configuration; not a runtime fact |
| Updated age / absolute time | `sources[].asOf` from the consuming page's existing API | The source timestamp, never fetch time | Consuming page must name the exact API/store/writer in its own trace |
| Writer state | `/api/v2/desk-sources?lanes=…` → `data.writers[].state` | `config/lane_registry.json` exact `lane_id` and `state`; NEVER_SCHEDULED → NONE | W8 owns approved registry edits; no registry change here |
| Last successful run | `data.writers[].last_success_at` | Read-only `data/governance/n8n_coordination_ledger.sqlite`, up to 50 completed live runs per requested lane | Existing n8n executor receipt, matching run_id/lane_id/mode/state/exit/finished time; RUN_DONE + exit 0; not lock skipped/timed out |
| Alternative successful-run evidence | Same field, `evidence_source=missed-run monitor` | Existing `data/runtime/cron_outage_watchdog_latest.json`, valid schema, mode monitor and nonfuture capture | Existing independent watchdog's validated execution evidence; reader never runs it |
| Evidence capture age | `data.writers[].evidence_as_of` | Actual monitor capture time, or read time for receipt lookup | Reader clock; explicitly separate from run and source timestamps |
| Source/writer gaps | caller `gap`, missing/invalid/future asOf, absent writer or missing receipt reason | Input validation and measured absence | No zero/healthy fallback; no inference from mtime |
| Decisions for you | `decisions[]` / `decisionGap` props | Consuming page's canonical decision queue | Frame never computes approvals or competing CIO facts |
| Back badges | NavRail fixed restoration instant 2026-10-24T22:51:33Z | Fourteen elapsed days; all eleven restored destinations | Static restoration metadata; not a runtime health claim |
| Research lineage destination | App `/closed-loop` → existing `ClosedLoopPanel` | Approved board 6 own-page destination | W6 owns the page and subsequent content redesign |

The frame resolves registry/run metadata only. It does not size, order, mutate a
stop, call a broker, refresh a producer, collect host commands or schedule a job.
A run's successful execution does not establish fresh business output. Paused and
retired writers can retain historical last successes. Missing cached monitor
coverage remains explicit; this GET never tries to repair or run that monitor.

## API and bounds

`get_sources(query)` in `scripts/lib/desk_sources.py` accepts comma-separated
`lanes`, max 24 unique identifiers. No caller-supplied file paths are accepted.
Registry read is bounded to 8 MiB, monitor snapshot to 2 MiB, receipt bodies to
64 KiB each and history to 50 matching rows per lane. SQLite is opened `mode=ro`
with a 250ms lock timeout and is not created if absent. Only compact clock fields
leave the handler; commands, raw receipts and account identifiers do not.

The small api_v2 route-registration hunk is handed to that file's current owner;
W5's claim extension was refused for W2's live claim and no override was used.
Registration is a first-frame acceptance dependency, not permission to edit W2's
file. Missing registration keeps the frame's writer clocks visibly unavailable.

## Proof and delivery status

- Pure source-clock tests run with psycopg2 hidden; gate:
  `config/ci_gates/desk_sources_20261024.json`.
- Browser fixture bundles the actual DeskPage/NavRail and house CSS. Every
  navigation/API response is intercepted at `http://desk-frame-fixture.test`;
  external traffic and mutations fail the proof. It exercises 412×915 and 390×844 touch flows plus desktop 1440,
  all writer states, missing/stale/invalid/future source clocks, history/reload,
  URL aliases, query/hash preservation, 44px targets, in-viewport tap outcomes and fourteen-day badge expiry.
  The frame has no list/detail layout: source evidence is inline; the existing
  phone navigation is a full-screen sheet. Page-specific list/detail sheets stay
  with their page owners and require their own mobile tap proof.
- Required screenshots are `impl-0-source-clocks-{1440,412,390}.png` and
  `impl-0-rail-{1440,412,390}.png` and `impl-0-writer-unavailable-{1440,412,390}.png`
  beside the approved mockups. Browser receipts include source SHA-256 hashes.
- Chromium failed to start in the configured sandbox. Automatic approval review
  rejected sandbox escalation as expanded execution access. No browser assertion
  or screenshot is claimed as passed. Operator approval is required before any
  retry that expands access; no indirect execution workaround is requested.
- The delivery packet records exact check results and remaining route/browser
  dependencies. Coordinator owns full-suite CI, publication, merge and release.

W6 owns `docs/ops/DESKS_B_REDESIGN_20261024.md`. W7 and W4 record page-specific
API/store/writer traces in their own documents. Common frame semantics are here.

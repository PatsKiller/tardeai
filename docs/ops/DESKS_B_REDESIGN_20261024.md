# Desks B: approved boards 5–11

**Status:** Backend review unit; shared-frame UI pending.
**Owner:** W6, `codex-w6-desks-b-20261024`.
**Updated:** 2026-10-24.

Task: `DSN-20261024-desks-b-P1-T1`. W6 owns Intelligence, Research lineage,
Hermes, Advisory, Reports, Rotation and Rec Intelligence. W5 owns the frame,
navigation and routes. W2 owns paged Hermes handlers; W8 owns writer registration.

## Board 6 backend, first review unit

The Research lineage backend reads the existing challenge history and lineage
snapshot. It starts no job, constructs no writer and writes no store. Lists are
bounded to 50 rows with real totals. The snapshot's large transition and evidence
arrays remain behind the existing `lineage/<id>` detail route.

| UI element | API path under `/api/v3/intelligence/` | Field | Store / key | Writer |
|---|---|---|---|---|
| Backlog rows and delay reason | `backlog?page=1&per_page=50` | `items[].stream_id`, `status`, `symbols`, `stuck_reason`, `reviewer` | `data/cio/hermes_challenge_queue.jsonl`; lifecycle event type, original metadata/payload, `claimed_by` | `HermesChallengeQueue` enqueue/reviewer lifecycle methods |
| Opening age | `backlog` | `items[].age_hours`, `backlog.oldest_age_hours`, `median_age_hours`, `p95_age_hours` | Original enqueue `occurred_at`, measured against response `as_of`; invalid/future clock → null | Same challenge ledger writers |
| Backlog count and reason totals | `backlog` | `total`, `backlog.pending`, `by_reason` | Latest lifecycle event per stream, excluding terminal streams and genesis | Same challenge ledger writers |
| Throughput, last seven days | `throughput` | `throughput.opened`, `closed`, `net_change`, window clocks | Unique streams enqueued within window; latest terminal event in window, including failures/cancellations/expiry. “Closed” is not “successful research.” | Same challenge ledger writers |
| Completed history | `completed` | `items[].status`, `resolution_reason`, `updated_at` | Terminal challenge events; resolution/failure/cancellation reason, never an invented outcome | Same challenge ledger writers |
| Lineage table | `research-lineage` | `items[].lineage_id`, `symbol`, `status`, research/memory counts, case/outcome/decision IDs | `data/cio/intelligence_lineages.json`; `lineages[]` | `intelligence_lineage.rebuild_lineages` and live-forward attachment methods |
| Decision changed | `research-lineage` | `items[].decision_changed` | `lineages[].advisory_use.what_changed_material`; absent → null | `intelligence_lineage.attach_advisory_use` |
| Snapshot age | `research-lineage` | `snapshot_as_of` | Snapshot `generated_at`; response `as_of` is observation time, not writer time | Same lineage writers |
| Authority | `authority` | `rules`, `mutation`, `financial_action` | Existing challenge queue actor model and this read-only adapter | Code contract, no new store |
| Auto-expire switch, OFF | `authority` or `backlog` | `auto_expire.enabled=false`, `days=null`, `editable=false`, reason | Approved board 6: operator expiry decision pending. Request parameters cannot enable it. | No expiry writer added |
| In-panel source gaps | All paged views | `gaps[].source/reason`; unavailable totals are null | Missing, invalid, oversized or unreadable history/snapshot | Source writer named above; no file mtime used |

Original source evidence and parent metadata survive later claim/start events.
Backlog reasons describe recorded lifecycle evidence. An unclaimed challenge says
no reviewer has claimed it; this does not assert that the worker service is down.
The throughput window is inclusive and excludes future timestamps. The lists count
rows available in the snapshot, rather than copying a mockup count.

This first review unit provides data only. The shared-frame UI, per-row retry/close
controls and fixture screenshots follow after W5's frame lands. Existing API root,
queue-health and lineage detail routes remain available. `authority` now returns
its own policy view instead of duplicating the dashboard.

## Validation and gaps

Pinned fixture tests cover opening age across reviewer events, terminal reasons,
stream throughput, 50-row paging, malformed/missing sources and immutable expiry
OFF. The missing-source fixture returns null totals and named gaps; it creates no
genesis record or directory.

Read-only copied-state receipt:
[`research-lineage-real-tree.json`](packets/desks-b-20261024/research-lineage-real-tree.json).
It records hashes, measured totals, source clocks and response sizes without
committing production rows. It is source evidence, not a deployment claim.

W5 interface: `DeskPage`, `useDeskTab`, `DeskGap` from `components/DeskPage`.
W6 requested `/closed-loop` → existing `ClosedLoopPanel` from W5 and will consume
`/api/v2/desk-sources` for lane clocks. No W5 files or lane registry are edited here.

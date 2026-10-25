# Jobs DATA_ERROR consumer: canonical conflict section

Date: 2026-10-24. Owner: W4 monitoring. Design-Task: DSN-20261024-w4-monitoring-P1-T1.
Status: private native reader/UI integration validated; public owner dependency integration and installed runtime acceptance remain pending.
Approved reference: conflict-engine-build.md, DESIGN.md and the binding EXCEPTIONS_MATRIX.md; Jobs is the DATA_ERROR consumer.

The Jobs response gains a separate `data_errors` observation. It does not add conflict findings to failed or missed execution counts or independent execution incidents. `scripts.lib.jobs_conflict_errors.get_data_errors` calls only the canonical W10 export `scripts.lib.conflicts.api.data_error_section(root=STATE_ROOT)`. W10 confirmed that `root` is the persistent-state root; its ledger is `ROOT/data/conflicts/conflict_events.jsonl`.

The engine owns record conversion, active-state filtering, bounded paging, truncation gaps, T0–T4/R1–R16 ordering and headline selection. Jobs preserves the returned section and its fields unchanged, including null headline, gaps, stale status, backend order and future fields. Jobs does not classify, filter, sort, select a headline or infer a resolution.

## Field trace

| Jobs response field | Source | Semantics |
| --- | --- | --- |
| `data_errors.section` | W10 `data_error_section(root=STATE_ROOT)` | Whole canonical section containing `findings`, `headline`, `gap`, `source`, `as_of`, `stale`; unchanged |
| `data_errors.unavailable_reason` | Jobs availability boundary | Nonempty explanation when the canonical reader is absent, fails or returns an incomplete section; section remains null |
| `summary.failed/missed` and `incidents[]` | Existing Jobs execution model | Execution evidence only; DATA_ERROR findings never change these counts |
| Selected record state, history and decision | Shared ConflictSheet → `GET /api/v3/conflicts/{encodedkey}` | Full W10 record; DECIDED remains distinct from CLEARED, unavailable history stays visible |

A missing reader is unavailable, never a zero count or a clear result. If the engine returns a ledger gap, Jobs retains that exact section and gap. Reader exceptions do not expose exception detail to the page. The shared Jobs observation retains its existing 60-second cache; filtering and paging execution rows preserve the whole DATA_ERROR observation.

## Shared UI integration contract

The UI uses W9's frozen shared `ConflictLine`, `ConflictSheet` and `useConflictSheet`. Jobs passes the whole canonical section. Null headline produces no flag; missing engine data displays an availability gap. The shared hook owns `?conflict=backendkey`, and ConflictSheet owns the selected `GET /api/v3/conflicts/{encodedkey}` read, including full record history and decision or an explicit unavailable state. Jobs adds no second detail reader or local classifier.

W4 exposes no conflict write or resolution action, including safety, protection, money or policy decisions. This change does not activate the conflict writer, modify or repair a ledger, replay work, acknowledge production dead letters or send notifications.

## Verification and remaining acceptance

Fixture tests verify whole-section identity, retained nulls/gaps/stale state, the named producer import and root argument, visible unavailable states without leaked exception details, separation from job execution counts, and preservation through the public filtered/paged Jobs response. They run with `TRADE_AI_CI=1` and psycopg2 hidden.

The private fixture integration uses the exact accepted six runtime blobs from W9 mobile checkpoint `00db0a59063edbe24d6eca074043393d2fd3a7cb` and conflict runtime checkpoint `58b8a940b31cac3d1b29e114ff46baf3ad51be8a` with owner type correction `fdb3334ec685eb6f8b3cf7d3b8bdf0f741f83339` (`stale` admits null; emitted JavaScript is byte-identical). W9 owns those source files; W4 changes only the Jobs consumer. No W10 work-in-progress source is copied. The private dependency snapshot commit is excluded from the W4 publication sequence; the coordinator must integrate owner source separately. All 33 browser fixtures passed with the actual global stylesheet at 1440×1000, 412×915 and 390×844: 21 conflict cases plus 12 existing Jobs regressions. They cover full-screen detail, actual phone taps, both Back paths, 44px controls, no page horizontal overflow, encoded selected GET, missing history gap, canonical fields, a DECIDED record still awaiting engine re-evaluation, preserved non-date next-run text, and selection of multiple findings in backend order. Screenshots live beside the approved mockups as `impl-16-dataerror-*.png`. The private producer is pinned to corrected W10 checkpoint `e9d3c76fe74f39103603b171ea09018ba5443689`, which filters active lifecycle records before bounded paging. The prior `9f4ef245d` native run is historical. All 12 producer runtime/rulebook files match that corrected owner source by SHA-256; the proposed rulebook is unchanged and no authority is activated. Public owner source must precede companion publication. Phone proof must tap the conflict line, verify full-screen in-viewport detail and canonical summary/clears_when, close through browser Back and the Back control, and assert 44px controls plus no page horizontal overflow. The corrected private integration passes 44 psycopg2-hidden affected tests, including five native producer/ledger cases: missing/corrupt ledger gaps, whole-section preservation, selected full history, write refusal and a public Jobs read keeping data errors separate from execution failures. Directory/file hashes and modification times remain unchanged by reads; owner writer methods are forbidden during the checks. A delayed missing-profile import is reported as unavailable without breaking execution observations. Three additional browser cases consume exact native Section/Record JSON generated from that corrected producer, bringing the total to 36 styled cases. No local classifier or conflict lifecycle writer is added. CIO completeness/gate tests, ratchets, registry CHECK and build evidence accompany the packet. No source checkpoint or fixture result establishes installed runtime behavior.

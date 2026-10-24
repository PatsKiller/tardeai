# Jobs DATA_ERROR consumer: canonical conflict section

Date: 2026-10-24. Owner: W4 monitoring. Design-Task: DSN-20261024-w4-monitoring-P1-T1.
Status: preparatory reader checkpoint; shared producer and UI frozen source, page integration and phone proof remain pending.
Approved reference: conflict-engine-build.md, DESIGN.md and the binding EXCEPTIONS_MATRIX.md; Jobs is the DATA_ERROR consumer.

The Jobs response gains a separate `data_errors` observation. It does not add conflict findings to failed or missed execution counts or independent execution incidents. `scripts.lib.jobs_conflict_errors.get_data_errors` calls only the canonical W10 export `scripts.lib.conflicts.api.data_error_section(root=STATE_ROOT)`. W10 confirmed that `root` is the persistent-state root; its ledger is `ROOT/data/conflicts/conflict_events.jsonl`.

The engine owns record conversion, active-state filtering, bounded paging, truncation gaps, T0–T4/R1–R16 ordering and headline selection. Jobs preserves the returned section and its fields unchanged, including null headline, gaps, stale status, backend order and future fields. Jobs does not classify, filter, sort, select a headline or infer a resolution.

## Field trace

| Jobs response field | Source | Semantics |
| --- | --- | --- |
| `data_errors.section` | W10 `data_error_section(root=STATE_ROOT)` | Whole canonical section containing `findings`, `headline`, `gap`, `source`, `as_of`, `stale`; unchanged |
| `data_errors.unavailable_reason` | Jobs availability boundary | Nonempty explanation when the canonical reader is absent, fails or returns an incomplete section; section remains null |
| `summary.failed/missed` and `incidents[]` | Existing Jobs execution model | Execution evidence only; DATA_ERROR findings never change these counts |

A missing reader is unavailable, never a zero count or a clear result. If the engine returns a ledger gap, Jobs retains that exact section and gap. Reader exceptions do not expose exception detail to the page. The shared Jobs observation retains its existing 60-second cache; filtering and paging execution rows preserve the whole DATA_ERROR observation.

## Shared UI integration contract

The pending UI will use W9's frozen shared `ConflictLine`, `ConflictSheet` and `useConflictSheet`. Jobs passes the whole canonical section. Null headline produces no flag; missing engine data displays an availability gap. The shared hook owns `?conflict=backendkey`, and ConflictSheet owns the selected `GET /api/v3/conflicts/{encodedkey}` read, including full record history and decision or an explicit unavailable state. Jobs adds no second detail reader or local classifier.

W4 exposes no conflict write or resolution action, including safety, protection, money or policy decisions. This change does not activate the conflict writer, modify or repair a ledger, replay work, acknowledge production dead letters or send notifications.

## Verification and remaining acceptance

Fixture tests verify whole-section identity, retained nulls/gaps/stale state, the named producer import and root argument, visible unavailable states without leaked exception details, separation from job execution counts, and preservation through the public filtered/paged Jobs response. They run with `TRADE_AI_CI=1` and psycopg2 hidden.

The source checkpoint requires no W9/W10 work-in-progress copy. Publication remains pending the owners' frozen source checkpoints, real shared component integration, full build and 1440×1000 / 412×915 / 390×844 fixture browser proof. Phone proof must tap the conflict line, verify full-screen in-viewport detail and canonical summary/clears_when, close through browser Back and the Back control, and assert 44px controls plus no page horizontal overflow. No source checkpoint or fixture result establishes installed runtime behavior.

# Batch 27: ops pages on the desk frame, Jobs tab everywhere, Watch Resolve end to end

Date: 2026-10-25. Branch: `release/batch-27-ops-conflicts-20261025`. Boards: 0 (frame), 16 (Jobs & health),
19–21 (Approvals, Amendment, Rulebook); `watch-resolve-conflict-fix.md`; W4 ops-pages directive. AGENTS.md 28.9–28.11.

## What changed on screen

- The seven ops pages (Health, LLM Spend, Coordination, Broker Access, Releases & Schedules, Ops Controls, System) and
  `/ops/jobs` sit in the shared desk frame: title, purpose line, Source clocks, Decisions band. Every existing tab and
  panel stays (change control); the frame is added around them.
- Coordination gains a `?tab=jobs` "Jobs & health" tab. Health, Releases, Ops Controls and System already embed the
  same component (W4). Coordination's Automation tab is unchanged.
- Approvals (`/approvals`, `/approvals/:id`) and Rulebook (`/policy`) are routed and on the Ops rail.
- The conflict sheet names the rule that decides the conflict in plain words and, once the engine clears a decided
  conflict, says who decided and what ("Resolved — the CIO chose HOLD …").

## Field trace

| UI element | API / field | Store / key | Writer |
| --- | --- | --- | --- |
| Frame Source clock: writer state, last successful run | `GET /api/v2/desk-sources?lanes=…` `writers[].state/last_success_at` | `config/lane_registry.json` `state`; run receipts | registry owner; lane executors |
| Frame Source clock: "Updated" | page's own payload time (`health.captured_at`, broker-access `as_of`, releases `generated_at`, ops-controls `applier.heartbeat_at`, coordination runs `as_of`) | that page's store | that page's producer |
| Frame source with no page time | gap text: "This page does not record when this source last updated …" | — | — |
| Decisions band link | static link to `/approvals` | — | — |
| Lane ids per page | constant in `apps/command-center-v3/src/components/OpsDeskFrame.tsx`; every id exists in `config/lane_registry.json` | registry | registry owner |
| Coordination › Jobs & health | `GET /api/v2/jobs-health` (same as `/ops/jobs`) | run receipts, wrapper events, registry | W4 projection `scripts/lib/jobs_health.py` |
| Conflict sheet "Rule that decides it" | `/api/v3/conflicts/{key}` `rule` (or the row's section finding) | `data/conflicts/conflict_events.jsonl` | `scripts/lib/conflicts/ledger.py` |
| Rule wording | `lib/watchConflictPresentation.ts::conflictRule` (copy of EXCEPTIONS_MATRIX rule names; unknown ids shown as-is) | — | — |
| "Resolved — the CIO chose …" | record `state == CLEARED` + `decision.actor_kind/chosen_side` | conflict ledger | CIO review completion (`conflicts/review.complete_review`) then engine re-evaluation |

## Routes registered (api_v2.handle)

`GET /api/v2/jobs-health`; `GET /api/v3/conflicts`, `GET /api/v3/conflicts/{key}`, `POST /api/v3/conflicts/{key}/decision`
(operator identity + CSRF; refused `CONFLICT_WRITER_NOT_ACTIVATED` until the operator activates the writer);
`/api/v2/governance/*` (W11); `/api/v2/health` and `/api/v2/health/remediation` through `scripts/lib/health_surface.py`.

## Proof (fixtures only, no :7777 traffic)

- `e2e/ops-pages-frame.spec.ts`: 8 pages × 1440/412/390; frame visible, writer clocks, Decisions link, Jobs tab tapped
  (44 px) and Jobs content in the viewport, no horizontal scroll.
- `e2e/watch-resolve.fixture.mjs`: My Watchlist and Prospects × 1440/412/390; Resolve → full-screen sheet → sides,
  rule, Ask the CIO → under review → decided (still flagged) → cleared (Resolved line, line gone from the row).
- `tests/test_b27_watch_resolve_e2e_20261025.py`: the backend path on disposable roots (engine shadow run, Watch
  section, api_v2 route, CIO review decision, engine clear, agents refused, gap fallback).
- `e2e/approvals.spec.ts`, `e2e/jobs-health.spec.ts`, `e2e/jobs-data-errors.spec.ts`, `e2e/system-tab-requests.fixture.mjs`.

## Not done here

The conflict-resolver lane is not admitted or activated (W8, operator). The production C3 review-completion hook that
calls `complete_review` is an owner integration still pending; until it lands and the lane runs, Watch shows the
engine gap and the existing flags (AGENTS.md 28.11).

# Phase 8 — Command Center UX Convergence: Alex is the front door

Status:      HISTORICAL
as_of:       2026-08-13T19:58:47-04:00
Measured at: efcc51365 / not measured

**"Stop forcing the operator to browse pages to discover decisions."**

## Goal

`/v3/cio` becomes the private investment office home. The operator lands on the
decision, not on a data wall. Everything the desks already produce (capital
plan, sector synthesis, opportunity queue, institutional report) converges into
six sections, decision-first.

## Top-level hierarchy

1. **CIO NOW** — the decisions that need the operator, above the fold.
2. **CAPITAL PLAN** — cash, reserve, investable, band, deploy/raise, sources/uses.
3. **PORTFOLIO POSTURE** — thesis, concentration, risk heat, tilts, performance, income, tax, constraints.
4. **OPPORTUNITIES** — watch / re-entry / rotation / research gaps with readiness.
5. **REPORT** — the institutional report v2 (embedded) + Generate Now.
6. **EVIDENCE / AUDIT** — provenance, source refs, validator states, run IDs, internal codes.

## Delivered

| Artifact | Path | Purpose |
| --- | --- | --- |
| Office-home composition (pure) | `scripts/lib/cio_command_center.py` | deterministic 6-section payload with plain-English labels |
| Dry tests | `tests/test_cio_command_center.py` | 14 tests over the pure composition |
| API endpoint | `GET /api/v3/cio/home` (`api_v2.py` → `api_v3_cio.get_cio_home`) | live office-home payload |
| Disposition endpoint | `POST /api/v3/cio/decision/{key}/disposition` | durable ACK/DEFER/DONE/REJECT/RATE |
| Disposition read | `GET /api/v3/cio/dispositions` | current operator dispositions |
| Front door | `apps/command-center-v3/src/pages/CioHub.tsx` | 6-section office home, decision-first |
| Browser audit | `scripts/cc_v3_cio_office_audit.py` | Checkpoint 8 (desktop + narrow) |

## CIO NOW

Above the fold shows at most 5 decision cards. Each card carries:

- **decision** — symbol + the actionable signal (e.g. "SCHD · Trim"), not a bare
  snake_case code;
- **dollars** — recommended dollar change and position value, before percentages;
- **why now** — the plain-English reason;
- **urgency** — Act now / Review / Watch, color-coded;
- **next review** — when present;
- **one-click "Why? · evidence"** — expands risk, tax note, counter-thesis;
- **operator actions** — ACK / DEFER / DONE / REJECT / RATE.

No model/process telemetry appears above the fold. That lives in EVIDENCE.

A decision surfaces when it has a real signal: a non-zero recommended delta, a
non-neutral "why now", or a concentration/risk breach. Pure "hold because
nothing changed" rows are omitted — they are not decisions.

## Disposition store (durable, advisory-only)

Operator actions append to `data/cio/decision_dispositions.jsonl`, never to
broker/order/stop state. This is durable advisory state — not conversational
memory — so it survives restarts and feeds Phase 10 outcome learning. Keys are
stable per decision (`position:{symbol}:{account}` or `action:{id}`).

## UX rules enforced

- decision first, evidence later;
- dollars before percentages when discussing action;
- plain-English labels; no snake_case in primary views;
- one responsive design for desktop/tablet/mobile (auto-fit grids, wrap);
- keyboard accessible (real `<button>`/`role="tab"` elements);
- `title` tooltips explain unfamiliar financial metrics;
- stale/missing evidence is muted (`--text3`/`--amber`), never red — red is
  reserved for negative investment judgment (a loss, a trim, a breach);
- render state never implies a model ran when it did not (the report iframe and
  "generated at" only appear after a real fetch).

## Existing pages

Deep-dive pages (Advisory Desk, Hermes, Rotation, Watch, Reports) are not
deleted. They remain specialist/evidence workspaces and are deep-linked from the
office home (EVIDENCE and REPORT link out). The prior `/v3/cio` plan detail
workspace is preserved via `?plan=<id>`.

## Checkpoint 8

`scripts/cc_v3_cio_office_audit.py` runs the six sections through a real browser
at desktop (1440px) and narrow (390px) widths and asserts:

- all six sections reachable;
- decision evidence drawer opens;
- zero horizontal overflow;
- zero console errors / page errors;
- zero raw JSON in primary UX (no snake_case payload keys leaked to the DOM).

## Authority

`READ_ONLY_ADVISORY`. The office home composes canonical state and records
operator dispositions. It cannot trade, move stops, or touch 2FA.

## Phase 8 status

Complete (code + dry tests + docs + browser audit written). Live deployment of
the rebuilt frontend and the new endpoints is gated on the operator's
Git/release checkpoint (Phase 11 convergence), not performed automatically here.

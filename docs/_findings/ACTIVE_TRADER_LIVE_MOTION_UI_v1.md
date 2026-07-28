# Active Trader Live Motion UI v1 — Findings

Bounded FRONT-END-ONLY tranche. Read-only aggregate motion surface for the Active Trader Review
page. Display-only: no order, flatten, broker, session, 2FA, feature-flag, or deployment change.

## Commits

- **Base (required, verified):** `53362c8af28182295d017f5931f961601387e900`
- **Branch:** `agent/active-trader-live-motion-ui-v1`
- **Final SHA:** recorded in the draft PR head (this doc is committed within that commit).

Start condition was met: `git checkout -B` set HEAD exactly to the base and the tree was clean
before any change.

## Changed files (all within the allowlist)

New:
- `apps/command-center-v3/src/hooks/useActiveTraderMotion.ts` — the single aggregate polling hook.
- `apps/command-center-v3/src/components/active-trader-motion/normalizeMotion.ts` — defensive normalizers.
- `apps/command-center-v3/src/components/active-trader-motion/motionFormat.ts` — pure display helpers.
- `apps/command-center-v3/src/components/active-trader-motion/T2CapacityIndicator.tsx`
- `apps/command-center-v3/src/components/active-trader-motion/MotionRail.tsx`
- `apps/command-center-v3/src/components/active-trader-motion/PositionMomentumPanel.tsx`
- `apps/command-center-v3/src/components/active-trader-motion/MotionSection.tsx` — composer + honest states.
- `apps/command-center-v3/e2e/active-trader-live-motion.spec.ts` — 10 deterministic tests.
- `docs/_findings/ACTIVE_TRADER_LIVE_MOTION_UI_v1.md` — this file.

Modified:
- `apps/command-center-v3/src/pages/activeTrader.types.ts` — appended motion snapshot types + constants.
- `apps/command-center-v3/src/pages/activeTrader.mock.ts` — added `MOCK_MOTION_SNAPSHOT` (REFERENCE SAMPLE only).
- `apps/command-center-v3/src/pages/activeTrader.css` — appended `.at-motion*` styles (tokens only, reduced-motion aware).
- `apps/command-center-v3/src/pages/ActiveTraderPage.tsx` — import + render `<MotionSection reference={reference} />`.

No backend Python, routes, broker code, session control, feature flags, other pages, package
manifests, lockfiles, deployment files, or existing workflows were modified. `package-lock.json`
is byte-identical after `npm ci` (no dependency added; only existing deps installed).

## Read contract

`GET /api/v3/active-trader/motion` (contract `active-trader-motion-snapshot-v1`). Every field is
normalized defensively: unknown/absent/malformed values become `null` / `''` / `[]` / a widened
`UNKNOWN` enum — never a fabricated live value. A payload that is not an object at all is treated
as a fetch failure (fails closed). A payload whose `contract` field does not match surfaces an
honest "UNEXPECTED CONTRACT" banner while still rendering only the fields that normalized.

**Known gap:** this tranche does NOT implement the aggregate endpoint. At the base commit the route
does not exist, so in a real deployment the hook fails closed to **MOTION API UNAVAILABLE** and the
surface renders no fabricated panels.

## Polling / backoff behavior (`useActiveTraderMotion`)

- Exactly **one** aggregate request per refresh cycle regardless of ticker count. `requestCount` is
  incremented once per fired request and exposed as a test seam (`data-testid="motion-request-count"`).
- Honors server `ui_refresh_after_s`, clamped to **5–30 s**. Missing/invalid hint → 30 s idle ceiling.
  Next poll is scheduled per-response via `setTimeout`, so 5 s (T2/open-position), 10 s (near-fire T1),
  and 30 s (idle) hints are each honored.
- `AbortController` aborts any in-flight request before a new one and on unmount (overlap-safe).
- While `document.hidden`, polling materially slows (no fetch; reschedule at the 30 s ceiling) and a
  `visibilitychange` handler refreshes immediately on return to visible.
- Bounded exponential backoff after failure: 5 s → 10 s → 20 s, capped at 30 s, never below 5 s — so
  a persistently-absent endpoint can never become a tight retry loop.
- Last-good snapshot is preserved during failure and labelled **MOTION DATA STALE** with age + error.
- Mock/reference data is never presented as live — the reference sample renders only behind an
  explicit REFERENCE SAMPLE label and the hook is disabled in that mode.
- No WebSocket in this tranche.

## UI behavior

- **Near-fire rail:** rows keyed + sorted by symbol (stable — never reordered by a price/priority
  tick), preserving selected-row identity across refreshes. Shows T0/T1/T2 tier, admitted/not, lease
  reason code, snapshot age, per-row refresh cadence, and a not-live indicator when degraded.
- **T2 capacity:** operating usage and provider ceiling shown separately
  ("T2 n / 2 operating · 8 provider ceiling"); ceiling labelled a ceiling, never a target; plus
  push-primary and bounded pull-fallback budget.
- **Open-position momentum panel:** state HOLD/WATCH/EXIT_ARMED/EXIT_SIGNAL/PROTECT_ONLY, normalized
  deterioration score, confirmation count, drawdown-from-HWM in R, HWM/entry/hard-stop/current price,
  arm/fire/recovery persistence, reason code, evidence freshness. EXIT_ARMED is styled distinctly
  from EXIT_SIGNAL; every state carries a non-color glyph + accessible label + description.
- **Operator safety:** EXIT_SIGNAL is display-only EVIDENCE. The motion surface contains no order
  button, POST, broker call, session activation, auto-flatten, or hidden side effect. Each position
  card carries a "DISPLAY ONLY · NO ORDER PATH" marker.
- **A11y:** state is never color-alone; tier/freshness/exit-state have accessible text; focus-visible
  outline on rail rows; `prefers-reduced-motion` disables transitions; no layout shift.

## Test evidence

`e2e/active-trader-live-motion.spec.ts` — route interception + Playwright fake clock (`page.clock`).
All 10 pass:

1. one aggregate request updates multiple ticker rows (3 rows, `requestCount === 1`).
2. 5 s hint honored with no per-symbol fan-out (+1 request per 5 s, not +3).
3. 10 s hint honored for near-fire T1 cadence (no request at 9 s, one at 10 s).
4. selection stays on the same ticker after a refresh.
5. temporary deterioration renders WATCH, never EXIT_SIGNAL.
6. persistent payload renders WATCH → EXIT_ARMED → EXIT_SIGNAL.
7. stale evidence renders PROTECT_ONLY without implying an automated exit (no order control).
8. API failure preserves last-good + STALE badge + bounded retry (no tight loop).
9. no enabled order/flatten control appears from an exit signal.
10. malformed payload fails closed (UNEXPECTED CONTRACT + honest empty states), no fabrication.

```
10 passed (4.3s)
```

## Build result

`cd apps/command-center-v3 && npm ci && npm run build` — PASS.
Design-token guard PASS (272 files), chip-scope tests PASS, `tsc` clean, `vite build` succeeded.
`package-lock.json` unchanged.

## Existing focused Active Trader test

`e2e/active-trader-tab.spec.ts` fails at this base for a **pre-existing** reason unrelated to this
change: its `openActiveTrader()` helper navigates to `/v3/trading` and clicks an "ActiveTrader" tab
button, but at this base ActiveTrader was moved to its own top-level route `/v3/active-trader`
(`TradingHub` `TABS` no longer lists it). The failure is at the first navigation assertion, before
`ActiveTraderPage` renders. This spec is outside the allowlist and was left untouched. The new spec
drives the correct `/v3/active-trader` route and renders the full page (queue, authority rail, and
the motion surface), confirming the page still mounts cleanly with the addition.

## Statement

No backend, broker, order, 2FA, session, deployment, or feature-flag file was changed. No POST or
order path was added. No live routing was enabled. No dependency or lockfile changed. All edits are
within the allowlist. EXIT_SIGNAL is display-only evidence.

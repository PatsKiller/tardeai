# Claude Code Prompt — Active Trader Live Motion UI v1

You are implementing a bounded front-end tranche for Trade AI Active Trader.

## Immutable start point

- Repository: `PatsKiller/tardeai`
- Required base commit: `53362c8af28182295d017f5931f961601387e900`
- Create branch: `agent/active-trader-live-motion-ui-v1`
- Open a **draft** PR to `main`; do not merge.

Before changing anything, run:

```bash
git status --short
git rev-parse HEAD
git branch --show-current
```

The worktree must be clean and `HEAD` must equal the required base commit. If either differs, make no changes and report the exact discrepancy.

## Governing backend contracts

Read these first and do not alter their semantics:

- `scripts/active_trader/t2_jit_policy.py`
- `scripts/active_trader/momentum_exit_policy.py`
- `docs/design/ACTIVE_TRADER_T2_JIT_AND_MOMENTUM_EXIT_v1.md`

T2 is just-in-time execution evidence, not scanner data. The UI must use one aggregate motion request rather than one request per ticker. The momentum policy emits evidence states only; `EXIT_SIGNAL` is not permission to send an order.

## Allowed files

You may change only:

- `apps/command-center-v3/src/pages/ActiveTraderPage.tsx`
- `apps/command-center-v3/src/pages/activeTrader.types.ts`
- `apps/command-center-v3/src/pages/activeTrader.mock.ts`
- `apps/command-center-v3/src/pages/activeTrader.css`
- new files under `apps/command-center-v3/src/components/active-trader-motion/`
- new files under `apps/command-center-v3/src/hooks/` whose names begin with `useActiveTraderMotion`
- `apps/command-center-v3/e2e/active-trader-live-motion.spec.ts`
- `docs/_findings/ACTIVE_TRADER_LIVE_MOTION_UI_v1.md`

Do not modify backend Python, routes, broker code, session control, feature flags, other pages, package manifests, lockfiles, deployment files, or existing workflows.

## Required read contract

Implement a typed client for:

```text
GET /api/v3/active-trader/motion
```

Expected top-level shape:

```json
{
  "contract": "active-trader-motion-snapshot-v1",
  "generated_at": 0,
  "ui_refresh_after_s": 5,
  "push_primary": true,
  "max_pull_fallbacks_per_minute": 2,
  "t2": {
    "operating_cap": 2,
    "provider_hard_cap": 8,
    "leases": [],
    "decisions": []
  },
  "positions": [],
  "exit_signals": []
}
```

Add defensive normalizers. Unknown, absent, or malformed fields must fail visibly to an honest unavailable/stale state. Never fabricate live values.

## Polling and bandwidth behavior

Create one aggregate polling hook. It must:

1. Perform no more than one request per refresh cycle, regardless of ticker count.
2. Honor server `ui_refresh_after_s`, clamped to 5–30 seconds.
3. Therefore refresh T2/open-position state at 5 seconds, near-fire T1 state at 10 seconds, and idle state at 30 seconds when the server returns those hints.
4. Prevent overlapping requests with `AbortController` or equivalent.
5. Abort on unmount.
6. Pause or materially slow polling while the document is hidden, then refresh immediately when visible again.
7. Apply bounded retry/backoff after failures; do not create a tight retry loop.
8. Preserve the last good payload during a temporary failure but label it stale with age and error state.
9. Never fall back to mock data while presenting the result as live.
10. Expose request count or a test seam so Playwright can prove one aggregate request per cycle.

Do not add WebSocket code in this tranche. The existing gateway remains push-primary internally; this UI is a bounded aggregate read fallback until the websocket contract is implemented separately.

## Required UI behavior

### Near-fire motion rail

For every displayed actionable ticker, update the existing row in place and show:

- T0/T1/T2 tier
- admitted/not admitted
- lease reason code
- last update age
- next refresh countdown or cadence
- a truthful stale/unavailable indicator

Do not reorder rows solely because a price tick changed. Preserve selected-row identity across refreshes.

### T2 capacity indicator

Show normal operating usage and provider ceiling separately, for example `T2 1 / 2 operating · 8 provider ceiling`. Never render the provider ceiling as a target. Also show `push primary` and the bounded pull-fallback budget.

### Open-position momentum panel

For each open position, show:

- state: `HOLD`, `WATCH`, `EXIT_ARMED`, `EXIT_SIGNAL`, or `PROTECT_ONLY`
- normalized deterioration score
- confirmation count
- drawdown from high-water mark in R
- high-water mark, entry, hard stop, and current price when present
- arm/fire/recovery persistence progress
- reason code and evidence freshness

A temporary deterioration must visibly remain `WATCH` or return to `HOLD`. `EXIT_ARMED` must be visually distinct from `EXIT_SIGNAL`.

`EXIT_SIGNAL` remains display-only. Do not enable an order button, POST, broker call, session activation, auto-flatten control, or any hidden execution side effect.

### Honest empty and failure states

- Endpoint unavailable: show `MOTION API UNAVAILABLE` and last-good age if one exists.
- Payload stale: show `MOTION DATA STALE`.
- No near-fire symbols: show a normal empty state, not an error.
- No open positions: show `No active paper/shadow positions`.
- Reference samples, if retained, must remain explicitly labelled `REFERENCE SAMPLE` and must never merge into live counts.

## Accessibility and operator safety

- Do not encode state by color alone.
- Add accessible text for T2 tier, data freshness, and exit state.
- Preserve keyboard selection and modal focus behavior.
- Respect reduced-motion preferences; no flashing tick animations.
- Price changes may use a brief non-flashing highlight, but avoid layout shift.

## Tests

Create Playwright coverage that proves:

1. One aggregate request updates multiple ticker rows.
2. A server 5-second hint is honored without one-request-per-symbol behavior.
3. A 10-second hint is honored for near-fire T1 data.
4. Selection remains on the same ticker after refresh.
5. A temporary momentum deterioration does not display `EXIT_SIGNAL`.
6. Persistent policy payload states render `WATCH` -> `EXIT_ARMED` -> `EXIT_SIGNAL` correctly.
7. Stale data renders `PROTECT_ONLY` and does not imply an automated exit occurred.
8. API failure preserves last good data with a stale badge and bounded retry behavior.
9. No enabled order/flatten control appears as a consequence of an exit signal.

Use route interception and fake timers where practical. Keep the test deterministic.

## Validation

Run at minimum:

```bash
cd apps/command-center-v3
npm ci
npm run build
npx playwright test e2e/active-trader-live-motion.spec.ts --reporter=line
```

Also run any existing focused Active Trader tests affected by your change.

## Findings artifact

Write `docs/_findings/ACTIVE_TRADER_LIVE_MOTION_UI_v1.md` containing:

- exact base and final SHA
- changed files
- polling/backoff behavior
- screenshots or textual test evidence
- build and Playwright results
- explicit statement that no backend, broker, order, 2FA, session, deployment, or feature-flag file changed
- known gap: the aggregate endpoint is not implemented by this front-end tranche

## Stop conditions

Stop without continuing if any of these is required:

- changing a backend contract
- adding a POST or order action
- enabling live routing
- changing package dependencies or lockfiles
- modifying files outside the allowlist
- inventing motion data because the endpoint is absent

Commit tersely, push the branch, and open a draft PR. Do not merge or deploy.

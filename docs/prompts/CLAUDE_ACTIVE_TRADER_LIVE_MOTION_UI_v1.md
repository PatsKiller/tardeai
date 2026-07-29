# Claude Code Prompt — Active Trader Live Motion UI v1

## Immutable start point

- Repository: `PatsKiller/tardeai`
- Required base commit used for the original implementation: `53362c8af28182295d017f5931f961601387e900`
- Branch: `agent/active-trader-live-motion-ui-v1`
- Draft PR only; do not merge or deploy.

## Governing contracts

Read these first and do not alter their semantics:

- `scripts/active_trader/t2_jit_policy.py`
- `scripts/active_trader/momentum_exit_policy.py`
- `docs/design/ACTIVE_TRADER_T2_JIT_AND_MOMENTUM_EXIT_v1.md`

T2 is a just-in-time motion-data resource, not scanner data and not an account property. The UI must use one aggregate motion request rather than one request per ticker.

`EXIT_SIGNAL` is account-unbound market-state evidence. It is not permission to send an order. The UI must not infer account, venue, environment, route, or authority from an exit state.

## Allowed files

Changes are limited to:

- `apps/command-center-v3/src/pages/ActiveTraderPage.tsx`
- `apps/command-center-v3/src/pages/activeTrader.types.ts`
- `apps/command-center-v3/src/pages/activeTrader.mock.ts`
- `apps/command-center-v3/src/pages/activeTrader.css`
- new files under `apps/command-center-v3/src/components/active-trader-motion/`
- new files under `apps/command-center-v3/src/hooks/` whose names begin with `useActiveTraderMotion`
- `apps/command-center-v3/e2e/active-trader-live-motion.spec.ts`
- `docs/_findings/ACTIVE_TRADER_LIVE_MOTION_UI_v1.md`

Do not modify backend Python, broker code, session control, feature flags, package manifests, lockfiles, deployment files, or existing workflows.

## Read contract

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

Unknown, absent, or malformed fields fail visibly to an honest unavailable or stale state. Never fabricate live values.

## Polling and bandwidth behavior

Create one aggregate polling hook that:

1. Performs no more than one request per refresh cycle, regardless of ticker count.
2. Honors server `ui_refresh_after_s`, clamped to 5–30 seconds.
3. Refreshes T2/open-position state at 5 seconds, near-fire T1 state at 10 seconds, and idle state at 30 seconds when instructed by the server.
4. Prevents overlapping requests.
5. Aborts on unmount.
6. Pauses or materially slows polling while the document is hidden, then refreshes when visible.
7. Applies bounded retry/backoff.
8. Preserves the last good payload during a temporary failure but labels it stale.
9. Never presents mock data as live.
10. Exposes a test seam proving one aggregate request per cycle.

Do not add WebSocket code in this tranche.

## Required UI behavior

### Near-fire motion rail

For every displayed ticker, update the existing row in place and show:

- T0/T1/T2 tier;
- admitted/not admitted;
- lease reason code;
- last update age;
- next refresh cadence;
- truthful stale/unavailable state.

Do not reorder rows solely because a price tick changed. Preserve selected-row identity across refreshes.

### T2 capacity

Show normal operating usage and provider ceiling separately, for example:

```text
T2 1 / 2 operating · 8 provider ceiling
```

Never render the provider ceiling as a target. Show push-primary posture and bounded pull-fallback budget.

### Open-position momentum panel

For each monitored open position, show:

- `HOLD`, `WATCH`, `EXIT_ARMED`, `EXIT_SIGNAL`, or `PROTECT_ONLY`;
- deterioration score;
- confirmation count;
- drawdown from high-water mark in R;
- high-water mark, entry, hard stop, and current price when present;
- arm/fire/recovery persistence;
- reason code and evidence freshness.

A temporary deterioration remains `WATCH` or returns to `HOLD`. `EXIT_ARMED` must be visibly distinct from `EXIT_SIGNAL`.

`EXIT_SIGNAL` remains display-only and account-unbound. Do not enable an order button, POST, broker call, account selection side effect, session activation, auto-flatten control, or hidden execution action.

### Honest empty and failure states

- Endpoint unavailable: `MOTION API UNAVAILABLE` with last-good age when available.
- Payload stale: `MOTION DATA STALE`.
- No near-fire symbols: normal empty state.
- No positions: `No active monitored positions.`
- Reference samples remain explicitly labeled and never merge into live counts.

## Accessibility and safety

- Do not encode state by color alone.
- Add accessible text for T2 tier, freshness, account-unbound state, and exit state.
- Preserve keyboard selection and modal focus.
- Respect reduced-motion preferences.
- Avoid flashing or layout shift.

## Tests

Playwright coverage must prove:

1. One aggregate request updates multiple rows.
2. A 5-second hint is honored without per-symbol fan-out.
3. A 10-second hint is honored for near-fire T1 data.
4. Selection survives refresh.
5. Temporary deterioration never displays `EXIT_SIGNAL`.
6. `WATCH` → `EXIT_ARMED` → `EXIT_SIGNAL` renders correctly.
7. Stale data renders `PROTECT_ONLY` without implying an exit occurred.
8. API failure preserves last-good data with bounded retry.
9. An exit signal remains account-unbound and creates no order/flatten control.
10. Malformed data fails closed.

## Validation

```bash
cd apps/command-center-v3
npm ci
npm run build
npx playwright test e2e/active-trader-live-motion.spec.ts --reporter=line
```

## Stop conditions

Stop if implementation would require:

- changing a backend contract;
- adding a POST or order action;
- binding an account, venue, or environment from motion evidence;
- enabling routing;
- changing dependencies or lockfiles;
- modifying files outside the allowlist;
- inventing motion data.

Commit, push, and keep the PR draft. Do not merge or deploy.

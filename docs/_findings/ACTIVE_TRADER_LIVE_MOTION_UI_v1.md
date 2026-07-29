# Active Trader Live Motion UI v1 — Findings

Bounded front-end tranche for the Active Trader aggregate motion surface. The UI is read-only and account agnostic: it displays market-state evidence but does not bind an account, venue, environment, route, or execution authority.

## Stack

- Original implementation base: `53362c8af28182295d017f5931f961601387e900`
- Current PR base: `agent/active-trader-motion-api-v1` (stacked backend PR #251)
- Branch: `agent/active-trader-live-motion-ui-v1`
- Draft PR: #252

The revised PR contains 14 UI/test/findings files. The original 13-file allowlist was deliberately widened by one file, `ActiveTraderHub.tsx`, after the account-agnostic architecture correction. No backend Python, broker, session, feature-flag, package, lockfile, or deployment file is modified by this UI tranche.

## Read contracts

- `GET /api/v3/active-trader/motion`, contract `active-trader-motion-snapshot-v1`.
- `GET /api/v3/active-trader/permission-queue`, sanitized by the stacked backend to return `account_binding_state: UNBOUND`, `accounts: []`, and `mode: REVIEW_ONLY`.

The UI fails closed to `MOTION API UNAVAILABLE` or `MOTION DATA STALE` when the motion endpoint is missing, unreadable, malformed, or stale. Unknown values never become fabricated live data.

## Account-agnostic taxonomy

The motion surface treats `EXIT_SIGNAL` as account-unbound market-state evidence.

- No account category is inferred from workflow or motion state.
- Venue identifiers are opaque strings.
- The UI account model has no environment-category boolean.
- Account environment is not encoded in account IDs or venue types.
- Account selection, capability verification, environment resolution, ownership, quantity, and authority are later runtime bindings.
- An allocation draft is not an order request.
- Every exit signal fails closed to `accountBound: false` when the field is absent or malformed.
- The live hub does not forward the legacy static account matrix.
- Live allocation capability remains empty until a dedicated runtime registry is connected.

Visible environment-specific review labels were removed from the revised Active Trader UI path. The authority rail now separates workflow authority, execution routes, and account binding.

## Polling and bandwidth

- Exactly one aggregate request per refresh cycle regardless of ticker count.
- Server `ui_refresh_after_s` is clamped to 5–30 seconds.
- T2/open-position cadence: 5 seconds.
- Near-fire T1 cadence: 10 seconds.
- Idle cadence: 30 seconds.
- AbortController prevents overlap and aborts on unmount.
- Hidden tabs slow polling and refresh on visibility return.
- Failure backoff is bounded at 5 → 10 → 20 → 30 seconds.
- Last-good data is retained and labeled stale.
- Reference data appears only behind an explicit reference-sample label.

## UI behavior

- Stable near-fire rows keyed and sorted by symbol.
- Separate T2 operating capacity and provider ceiling.
- Position states: `HOLD`, `WATCH`, `EXIT_ARMED`, `EXIT_SIGNAL`, `PROTECT_ONLY`.
- Displays deterioration score, confirmations, drawdown in R, current/entry/high-water/hard-stop levels, persistence, reason, and freshness.
- `EXIT_ARMED` and `EXIT_SIGNAL` are visually and accessibly distinct.
- Position cards state `ACCOUNT UNBOUND · NO ORDER PATH`.
- Empty state is `No active monitored positions.`
- No order, flatten, broker, account-binding, session-activation, or hidden execution control exists in the motion surface.

## Test coverage

`e2e/active-trader-live-motion.spec.ts` covers:

1. one aggregate request updating multiple rows;
2. 5-second cadence without per-symbol fan-out;
3. 10-second near-fire cadence;
4. selection preservation;
5. temporary deterioration remaining below `EXIT_SIGNAL`;
6. `WATCH` → `EXIT_ARMED` → `EXIT_SIGNAL`;
7. stale evidence producing `PROTECT_ONLY` without implied execution;
8. last-good preservation and bounded retry;
9. account-unbound exit evidence creating no order/flatten control and leaving `ACCOUNT BINDING: NONE` visible;
10. malformed payloads failing closed.

The original Claude run reported 10/10 passing and a successful application build. The stack and taxonomy changed after that run, so the revised head requires fresh executable validation.

## Existing unrelated test

`e2e/active-trader-tab.spec.ts` targets the removed `/v3/trading` tab-button path rather than the current `/v3/active-trader` route. It remains outside this tranche.

## Authority statement

This UI emits no POST, order, route, flatten, broker, session, or account-binding action. `EXIT_SIGNAL` is evidence only. A future execution orchestrator must receive a separate runtime account capability and authority envelope before it can form any executable request.

# WP-29(c): account-label browser evidence

Status: DRAFT — local fixture proof complete; publication and exact-head CI pending
as_of: 2026-10-24T03:41:44Z
Product source base: `325ff34f2b3b272090b78d5210a2847c8c30bd2a`
Design-Task: DSN-20261023-handoff-v3-P6-T293

Six actual Chromium tests render Watch, CIO Desk and Active Trader at **1440 × 1000** and **412 × 1000**, using the same synthetic `SPCX` symbol held in **Schwab Rollover IRA** and **Schwab Individual**. The tests use the unchanged product build. They add no product, account-registry, Active Trader engine, broker, order or stop behavior.

The screenshots establish how account scope is presented from supplied API fields. They do not validate real holdings, account ownership, producer completeness, market data, n8n execution or a deployed release. The screen header's zero portfolio and unavailable panels are deliberate empty fixtures, not operational observations.

## Evidence and current gaps

| Surface | Desktop | Phone | Verified account meaning |
|---|---|---|---|
| Watch / My watchlist | [1440 PNG](packets/wp29-account-labels-20261023/watch-1440.png), [receipt](packets/wp29-account-labels-20261023/watch-1440.json) | [412 PNG](packets/wp29-account-labels-20261023/watch-412.png), [receipt](packets/wp29-account-labels-20261023/watch-412.json) | One held symbol shows `held · 2 accounts`. Both exact names are asserted in the chip's `title` tooltip; the row has no visible account-name chips. |
| CIO Desk / Decisions | [1440 PNG](packets/wp29-account-labels-20261023/cio-1440.png), [receipt](packets/wp29-account-labels-20261023/cio-1440.json) | [412 PNG](packets/wp29-account-labels-20261023/cio-412.png), [receipt](packets/wp29-account-labels-20261023/cio-412.json) | One position decision displays `2 accounts` and both exact account-name chips. |
| Active Trader / Session review | [1440 PNG](packets/wp29-account-labels-20261023/active-trader-1440.png), [receipt](packets/wp29-account-labels-20261023/active-trader-1440.json) | [412 PNG](packets/wp29-account-labels-20261023/active-trader-412.png), [receipt](packets/wp29-account-labels-20261023/active-trader-412.json) | Two synthetic manual-fill observation rows display their own account names. The shared engine signal has no account label or account authority. Both account cells are asserted inside the viewport. |

All six PNGs were inspected. Watch's phone table stacks column headings; WP-31 owns the Watch layout follow-up. A native `title` tooltip is not equivalent to a visible, touch-accessible expansion of both account names. This package records that remaining gap rather than adding product changes outside item (c). The phone Active Trader capture scrolls the app's inner content so both account rows appear; the PNG remains an unedited 412 × 1000 viewport screenshot.

Observed Watch row widths were 958/958 pixels (client/scroll) on desktop and 382/382 on phone. Active Trader's table wrapper was 1222/1222 and 358/358 with zero horizontal scroll. These fixture measurements do not establish responsive behavior for arbitrary account names or data volumes.

## Fixture lineage and boundaries

The fixture is `apps/command-center-v3/e2e/fixtures/accountLabelFollowups.fixture.json`, with clock fixed to `2026-10-23T20:30:00Z`. It contains synthetic account keys and display names, not account digits, real positions, orders, fills, credentials or live data.

| View | Mocked source | Supplied fields | Current presentation source |
|---|---|---|---|
| Watch | `/api/v3/data-broker/watch-curation` | `my_watchlist.rows[].held_accounts`, `held_account_labels` | `watchListsModel.ts` resolves held names; `WatchProspects.tsx` carries the count and title on the held-row chip. |
| CIO Desk | `/api/v3/cio/home` | Position decision `accounts`, `account_labels` | `CioHub.tsx` renders the badge and one `AccountChip` per account. |
| Active Trader | `/api/v3/active-trader/session-review` | Per-review-row `account_label` | `ActiveTraderSessionReviewTab.tsx` appends the name only when supplied on that row. |

Active Trader is a shared advisory signal surface. The fixture does not allocate a shared signal to both accounts or imply that a signal, hypothetical review or manual-fill observation placed an order. No action buttons are clicked; the test validates display semantics only.

The Playwright spec intercepts every request. Every `/api/` GET is fulfilled from the fixture or an explicit empty fallback for unrelated panels. Every non-GET API request and every different-origin HTTP request is aborted and recorded; service workers are blocked. Each test asserts **zero attempted API mutations, zero external requests and zero page errors**. Each receipt retains the actual API paths requested, so the empty fallback is not represented as populated lineage.

The companion Python static server serves only the built SPA from a confined `dist` root on a loopback ephemeral port. It returns HTTP 410 for API GETs and has no upstream proxy, database, credential reader or mutation handler. No traffic was sent to the live server or production APIs. The sandbox's socket restriction was escalated through the formal approval tool for this exact fixture operation; no alternate transport was used. The fixture server was stopped after verification.

## Reproducible validation

- `npm run build` passed against unchanged product source (Vite 10.63 s; existing bundle-size warning only).
- `e2e/account-label-followups.spec.ts`: **6 passed**, 0 failed, 0 skipped, 0 flaky; final browser run `2026-10-24T03:41:40.280Z`, duration 3.443 s.
- `tests/test_ci_draft_pr_skip_20261023.py`: **87 passed**, including the new optional workflow's draft skip, ready-for-review, main-only push and concurrency rules.
- Python helper Ruff, whitespace and generated documentation index checks pass.

[verification.json](packets/wp29-account-labels-20261023/verification.json) records source/artifact SHA-256 digests, image dimensions and test statistics. The six adjacent JSON receipts record the fixture clock, account names, route, viewport, request paths and zero-write checks. Original local build/browser/XML receipts remain under `~/.cache/rtc/codex-wp29c-20261023/`.

From `apps/command-center-v3`, build the app and start the no-proxy fixture server in one terminal:

```sh
npm run build
python3 e2e/support/account_label_static_server.py --dist dist --port 4173 --port-file "$HOME/.cache/rtc/wp29-account-labels/port"
```

In a second terminal in that directory:

```sh
PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 WP29_SHOTS="$HOME/.cache/rtc/wp29-account-labels/screenshots" npx playwright test e2e/account-label-followups.spec.ts --project=chromium --reporter=line
```

Stop only that fixture server with Ctrl-C. Chromium and local application dependencies must already be installed or installed through the applicable dependency authorization. Local validation reused the existing dependency/browser cache; no dependency or lockfile changed.

## CI and coordinator handoff

`.github/workflows/account-label-followups-ui-validation.yml` runs the actual spec after dependency setup and a product build, starts the same static helper, and uploads screenshots plus receipts. It is an **optional** validation workflow: no required status context or branch protection changes. It keeps the exact existing draft guard, includes `ready_for_review`, triggers pushes only on `main`, and cancels superseded PR runs. It has read-only repository permission and no secrets, production API proxy or deployment step.

The worker commits this delivery locally and records one `PUSH_NEEDED` publication command. The coordinator/operator publishes the branch, checks the actual browser artifact and required checks on the published head, then owns merge and release. This report does not assert runtime/live DONE. Watch's visible/touch-accessible account-name expansion remains a separately owned product follow-up.

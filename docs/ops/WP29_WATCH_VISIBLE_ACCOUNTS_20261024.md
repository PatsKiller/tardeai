# WP-29c: visible Watch account names and page heading

Status: DRAFT — locally verified UI fix; publication and coordinator merge pending
as_of: 2026-10-24T04:27:30Z
Source base: `8b24e113740cda70c25e4823c16c46ea3b63cf7f`
Design-Task: DSN-20261024-wp29-watch-account-names-P1-T1

Watch now renders the resolved account names in desktop record rows, using the existing names-only `AccountChip` component. Two-account holdings show both names without hovering over the narrow symbol/status chip. Formerly held rows show the existing resolved last-sell account, labelled `Sold in`. The phone card already showed account names after WP-31; it keeps that Account fact and hides the added desktop group to avoid repetition.

The Watch view title is now a real level-one heading, preserving the existing text and appearance across tabs. The baseline title text was visible on the phone, but it was a plain `div` and did not expose a semantic heading. This fixes that accessibility gap; it does not claim the previous screen had no title text.

No API, account registry, broker, order, stop, Active Trader engine, n8n workflow, scheduler or producer behavior changed. The existing Star, Remove, record selection, next-step targets, filters and row decisions remain in place. Account names still come from `held_accounts`/`held_account_labels` or last-sell fields through the existing `accountName` resolution and digit filter. This Watch display accepts only a known alias or safe supplied name; missing labels for unknown keys display `Unlabelled account` instead of humanizing storage IDs into invented names. Row chips, phone facts, status tooltips and last-sell detail use that display rule. The UI does not independently verify account ownership or holdings.

## Actual browser proof

| Viewport | Screenshot | Receipt | Observed result |
|---|---|---|---|
| 1440 × 1000 | [Desktop](packets/watch-account-names-visible-20261024/watch-accounts-1440.png) | [JSON](packets/watch-account-names-visible-20261024/watch-accounts-1440.json) | Both account-name chips and the Watch heading are visible. Account group client/scroll width: 343/343 px. |
| 412 × 1000 | [Phone](packets/watch-account-names-visible-20261024/watch-accounts-412.png) | [JSON](packets/watch-account-names-visible-20261024/watch-accounts-412.json) | Both full account names remain visible in the existing Account fact. Heading and labelled card facts remain visible; client/scroll width: 355/355 px. |

Both unedited PNGs were visually inspected. They render the same synthetic `SPCX` holding in Schwab Rollover IRA and Schwab Individual, with a fixed clock of `2026-10-23T20:30:00Z`. The header's zero/empty/stale panels are empty fixtures, not live health or portfolio observations. Build identity is taken from the source SHA above; the local bundle's `source UNAVAILABLE` footer is not served-release evidence.

Before the product edit, the new heading/privacy subset reproduced **3 failures and 1 pass**: no semantic H1 at either width and no visible desktop account-name group; the phone's existing names-only fallback already passed. After the edit, the full browser run passes **22 tests**: ten new checks and twelve existing Watch action/layout regressions, with zero failures/skips/flakes. New cases cover digit-bearing supplied labels, numeric identifiers with valid human labels, and missing labels for unknown numeric or digit-free keys. They verify names-only/explicitly-unlabelled output plus the existing next-step href, star state, Remove control and selection behavior.

The ten new cases fulfill every API GET, reject and record every attempted API mutation and different-origin HTTP request, block service workers, and assert zero writes/external requests/page errors. Existing Watch regression cases exercise action POSTs only through mocked responses. No production request, notification, model call or real mutation occurs.

The local preview and optional CI job start Vite with `configFile:false`, an empty environment directory and `proxy:{}`. They serve only the build and have no live API proxy. No request was sent to port 7777, no credential was read, and the preview process was stopped after verification.

## Validation and handoff

`npm run build` passes, including its existing frontend checks. The new optional workflow passes **87 draft-workflow regression checks** with psycopg2 hidden using the coordinator's `nopg` shim. No Python test was added or changed in this UI delivery. The host-path and test-coverage ratchets report zero new violations/unlisted tests; whitespace, claim coverage, secrets and generated documentation INDEX checks pass.

`.github/workflows/watch-account-names-visible-ui-validation.yml` runs the real ten-case Chromium spec at the published head, with read-only repository permission, the exact draft skip guard, `ready_for_review`, main-only push triggers and PR concurrency cancellation. It uploads screenshots/receipts. No required status or branch-protection rule changes.

[verification.json](packets/watch-account-names-visible-20261024/verification.json) binds source and image/receipt hashes and browser/workflow statistics. Original build logs and before/after JSON reports are under `~/.cache/rtc/codex-wp29c-ui-20261024/`. A fresh CI run uses the checked-in optional workflow; the standalone spec is `apps/command-center-v3/e2e/watch-account-names-visible.spec.ts`.

WP-31's original owner released the merged source claim before this task claimed the Watch files. The earlier batch-14 account-label fixture/spec package was left untouched. This delivery has its own source claim and one `PUSH_NEEDED` command; the coordinator/operator publishes, verifies exact-head checks and merges. Local screenshots prove display behavior, not deployed or live n8n acceptance.

# WP-31 Watch rows and phone cards

Status: DRAFT — implementation and fixture verification complete; publication/release pending
as_of: 2026-10-24T02:49:00Z
Measured at: main base `fe826d2ecdb59a19bd7c510c8923c7b743f06eee`
Owner: codex-wp31-20261023; DSN-20261023-handoff-v3-P6-T31

Watch now keeps the desktop “why” on one line and renders readable record cards at phone
width. The original reason remains in its tooltip and record detail. Supporting facts remain
available in the context tooltip and detail; conflicts retain first position in the visible
context line. Mobile cards show stage, account, next trigger and last-trade P/L without an
inner sideways scroll. Missing account, stage or P/L facts remain explicitly unknown or
unavailable. Account labels reuse the existing name-only helpers.

The affected views are My Watchlist, System Suggests, Prospects and Full universe. Stage
buttons form two columns on phones. Full universe keeps its desktop table and shows the
same records as labelled cards on phones; row expansion also supports Enter/Space.
Existing stars, add/remove/dismiss, proposal and alert forms, record expansion, filters,
ranking and source fields retain their existing routes and meaning.

The two layout causes were the panels' fixed minimum widths and the legacy global phone
rule that turns every inline grid into a single column. That rule stacked both column
headings and every row cell. Scoped Watch CSS now owns those grids; the global fallback
and other pages are unchanged. Desktop explanations previously wrapped all supporting
facts; the new explanation and context lines truncate visually while retaining full text.

## Verification

The unchanged baseline passed **8 fixture browser tests** with screenshots at 1440 and
412 px. The changed views passed **14 regression browser tests**, including new assertions
for one-line desktop reasons, full reason tooltips, hidden phone headers, two-column stage
buttons and no inner horizontal scroll in the key panels. An additional fixture test passed
for account names without account digits and unchanged formerly-held NAVN P/L. No new
test file was introduced; the existing Watch Playwright suites carry the added assertions.

`npm run build`, TypeScript, UI standards and design-token checks passed. The build emits
its large-chunk advisory; this work does not change bundle splitting. The first new CSS
check caught a literal radius, which was replaced with the existing radius token before
final verification. Sandbox process restrictions initially prevented Chromium startup;
fixtures passed once the isolated browser was allowed to launch.

The fixture server used `127.0.0.1:4491` with its live API proxy removed. Browser API calls
were fulfilled from captured Watch fixtures; action requests were recorded and checked
locally. No request was sent to `127.0.0.1:7777`, no real command was submitted, and no
broker/order/stop implementation was changed. These screenshots contain historical fixture
data and do not demonstrate current production health or live source freshness.

## Before and after

Screenshots use the same captured fixtures and viewport dimensions. The packet's
[VERIFICATION.json](packets/watch-layout-20261023-wp31/VERIFICATION.json) pins their hashes,
source hashes, test counts and raw local log paths.

| View | Before | After |
|---|---|---|
| My Watchlist, 1440 px | [Before](packets/watch-layout-20261023-wp31/before-my-watchlist_1440.png) | [After](packets/watch-layout-20261023-wp31/after-my-watchlist_1440.png) |
| My Watchlist, 412 px | [Before](packets/watch-layout-20261023-wp31/before-my-watchlist_412.png) | [After](packets/watch-layout-20261023-wp31/after-my-watchlist_412.png) |
| Prospects, 412 px | [Before](packets/watch-layout-20261023-wp31/before-prospects_412.png) | [After](packets/watch-layout-20261023-wp31/after-prospects_412.png) |
| Full universe, 412 px | [Before](packets/watch-layout-20261023-wp31/before-full-universe_412.png) | [After](packets/watch-layout-20261023-wp31/after-full-universe_412.png) |

Raw screenshots and logs remain in `/home/johnclaw/.cache/rtc/codex-wp31-20261023/`.
The branch is `work/DSN-20261023-handoff-v3-P6-T31` in
`/home/johnclaw/wt-codex-wp31-20261023`. Its one publication command is recorded as
PUSH_NEEDED in the progress log. The claim remains held for coordinator publication,
required exact-head checks and release; this worker does not push, merge or deploy.

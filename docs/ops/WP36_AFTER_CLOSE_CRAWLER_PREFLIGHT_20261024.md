# WP-36 after-close observer: strict packet and scoped live evidence

Status: PARTIAL — strict harness tested; retirement observed with warnings; remaining views NOT_MEASURED
as_of: 2026-10-24T03:42:00Z
Measured at: source base `325ff34f2b3b272090b78d5210a2847c8c30bd2a`; served SHA `d0c8b70d8d915098094aa7180f25d6b0b0e0cffe`
Owner: codex-wp36-20261024; Design-Task DSN-20261022-site-validation-P3-T1

A separate strict GET observer is now available in the packet. The existing crawler was not
executed or modified. The new observer has fixture proofs, exact served-build identity,
credential-free transport and one global request queue for documents, assets and API reads.
It preserves the existing heavy-endpoint exclusions. It performs no clicks or writer calls.

A scoped after-close observation visited `/v3/retirement` at 1440 and 412 px. Both observations
are **WARN**: protected broker/credential/live-trading header reads were intentionally blocked.
Neither view had a page exception, error boundary, loading-only screen or horizontal page
scroll. These warnings are not a full data-completeness or production-readiness acceptance.
Other ordinary routes remain **NOT_MEASURED**; the coordinator prioritised a WP-13 CI fix
before the remaining run. Hermes/maturity and the other original heavy exclusions remain
**OWNER_HELD / NOT_MEASURED** and were not requested.

## Existing crawler findings

The frozen [legacy audit](packets/after-close-crawler-20261024-wp36/legacy-crawler-audit.json)
pins `/home/johnclaw/.cache/rtc/site-crawl/tools/crawl.mjs` and its source anchors.

| Requirement | Existing source finding |
|---|---|
| GET only | Line 81 also permits HEAD. |
| Global at most one request per second | Line 113 queues API requests; documents/assets fetch directly. External requests continue at line 93. |
| Stop on first 5xx/timeout | Lines 117–130 record errors and continue rather than terminally stopping. |
| No button acts | The runner discovers and clicks tabs around line 317; no no-click switch exists. |
| Pending Hermes/maturity proof | The HEAVY guard at line 60 intentionally excludes those endpoints. Replay does not close that proof. |
| No existing credential/profile loading | The tool creates fresh contexts; no storage/cookie file load was found. This does not remedy the other protocol gaps. |

The repository's older `scripts/crawl_v3_dashboard.py` imports a service-authenticated client,
retries server checks and can send alerts/write lane receipts. It was neither invoked nor
changed. Its existing scheduling and authority remain untouched.

## Delivered strict harness

[Strict observer](packets/after-close-crawler-20261024-wp36/strict-smoke.mjs):

- Production entry fixes the origin at `http://127.0.0.1:7777`; there is no alternate-base option.
  URI credentials, credential headers/query keys, non-GET methods, external origins and action
  URLs/queries are refused before HTTP. Broker/order/stop/credential/execution paths are held.
- Direct `node:http` uses fixed GET and a public header whitelist. It has no cookie jar,
  authentication helper, service token, proxy credential lookup or stored browser profile.
  Browser fulfilment drops Set-Cookie/authentication headers. A synthetic credential header
  is refused before transport. Sensitive values are never recorded in the receipt.
- One queue covers every document, asset, API and build-identity GET. The final limiter waits
  until at least 1,000 ms after prior completion, rounding up and rechecking early timer wakes.
  An absolute deadline and response-size cap bound each request; queued closed-view work is
  discarded rather than sent after its observation ends.
- The explicit after-close flag and Eastern weekday window are checked before requests.
  Weekday holidays are treated conservatively without an inferred holiday exemption.
- Initial build metadata pins a full SHA. Identity is checked around observations. Authentication,
  redirects/read errors, first 5xx, timeouts and release drift stop the run without retry or fallback.
- Fresh browser contexts block service workers/WebSockets; no tabs/buttons/forms are acted on.
  All original HEAVY branches are preserved verbatim, with their root paths also held.

This is bounded WP-36 observation, not the host-wide WP-07 proof reserved to the coordinator
by Handoff A1b step 3. WP-36 item 1 explicitly assigns after-close, slow GET observation to an
agent. This worker makes no host-readiness, scheduler-admission or cutover declaration.

## Verification and the timing correction

The CI-registered Python wrapper runs **21 hermetic protocol scenarios**. Together with the
canonical-gate registry suite, **26 pytest tests pass**. The cases cover market-window edges,
GET-only enforcement, exact origin, no credential transport, preserved heavy holds, business
and action refusal, global concurrent document/asset/API spacing, early timer wakes, auth/4xx/
5xx/redirect/timeout fail-stop, served SHA drift, response size, closed-view queues and headers.

A real Chromium fixture additionally proves that the disposable fixture listener receives zero
HTTP requests or WebSocket upgrades; POST/external/credential attempts do not reach transport,
response cookies do not enter the empty context, and the page has no JavaScript exceptions.
The fixture uses synthetic headers and mocked HTTP only; it contacts no live endpoint.

The first scoped live run made **49 GET requests, all HTTP 200**, on the pinned SHA. Its measured
minimum start gap was **999.01 ms**: a fractional Node timer woke slightly early. That run is
**not accepted as strict rate-compliance proof**. The final harness corrects it with a rounded,
rechecked wait and spacing after prior completion. An independent early-wakeup fixture was
added. Two subsequent metadata-only GETs on the same exact SHA measured **1,006.98 ms** apart.
Those two calls verify the corrected timing; they do not recapture or promote either UI view.
The combined live traffic was 51 GETs, with no retries, mutation methods, heavy endpoint or
broker/credential request transmitted. Initial view warnings remain recorded.

Proof files:

- [Protocol fixtures](packets/after-close-crawler-20261024-wp36/protocol-fixture-proof.json)
- [Browser fixture](packets/after-close-crawler-20261024-wp36/browser-fixture-proof.json)
- [Scoped live observations](packets/after-close-crawler-20261024-wp36/scoped-live-observation.json)
- [Corrected metadata timing](packets/after-close-crawler-20261024-wp36/corrected-rate-proof.json)

Raw live screenshots stay in
`/home/johnclaw/.cache/rtc/codex-wp36-20261024/live-retirement/`; they were not committed because
they can display private portfolio information. The committed projection contains source,
protocol and layout facts rather than response bodies. No mocks are labelled live evidence.

## Remaining scope and exact continuation

The packet's remaining-view matrix records all 32 ordinary route targets at both widths.
Retirement has WARN observations that need a strict final recapture; the other 31 routes
are NOT_MEASURED. The listed heavy API groups remain owner-held, separately from unattempted
ordinary views. Missing measurements are not empty-green results.

After the packet is published and the coordinator schedules the remaining run, this command
uses the exact observed served SHA and a new evidence directory:

```bash
cd /home/johnclaw/wt-codex-wp36-20261024
env -u NODE_OPTIONS -u NODE_PATH TRADEAI_LIVE_SMOKE_AFTER_CLOSE=1 node docs/ops/packets/after-close-crawler-20261024-wp36/strict-smoke.mjs --out=/home/johnclaw/.cache/rtc/codex-wp36-20261024/remaining-live-after-publication --expected-sha=d0c8b70d8d915098094aa7180f25d6b0b0e0cffe
```

Use it only outside the protected Eastern market window. It stops if that release has moved,
a real read/auth failure occurs, or a timeout/5xx happens. It never loads credentials or tries
an alternate authenticated path. Paste its receipt status, exact SHA, view results, held paths
and observed timing. Completing ordinary views still does not admit the heavy endpoint proof.
No source/financial repair is inferred from a warning; a reproducible P1/P2 needs its own file
claim, and P3 changes remain mockups for operator review.

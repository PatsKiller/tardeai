# PR #247 Independent Architecture Audit — 2026-07-28

## Verdict

**FAIL — NOT MERGE READY** at audited head:

```text
3aa1ab33cbf7b2d4cc731aeb1cc61f8368e60732
```

The original green suite proved mock-unit behavior, not the production claims in the PR
body. The corrective stack deliberately fails closed rather than manufacturing a live L2
consumer.

Corrective branch and verified head:

```text
agent/pr247-l2-truth-audit-fixes-v1
6ed1bf75c89cb7d08cdc7d0a2111390c03b24cc9
```

Focused audit CI: **94 passed**. Generic release-readiness: **success**.

## Controlling boundaries

- one long-lived gateway owns production Moomoo subscriptions;
- request handlers and cron jobs consume normalized snapshots and do not open competing
  OpenD contexts;
- arm intent, provider reachability, entitlement, accepted subscription, observed subtype,
  freshness, sequence integrity, tape evidence, and T2 admission are distinct facts;
- configuration alone cannot promote a symbol or event to T2;
- unknown quota blocks all new allocation, including P0;
- P0 may use reserved capacity but may not exceed the provider's hard remaining quota;
- missing or untrusted timestamps fail stale;
- no order, trade unlock, real 2FA, credential exposure, or LLM authority exists here.

## Blocking findings

### 1. The claimed single owner did not exist

`active_trader/l2_runtime.py` lazily opened a process-local gateway from the HTTP request
process, while `scalp_shadow_logger.py` still called the legacy
`market_observations/moomoo_t2.default_provider()` on each live cron invocation. That
legacy provider constructed its own `FutuTransport` and OpenQuoteContext. The two
processes did not share subscription lifecycle, buffers, quota state, or reconnect epoch.

The original AST guard inspected only the new module list and omitted the legacy scalp
path.

### 2. No production ingestion loop drove the new manager

The HTTP runtime restored desired symbols as `ARM_INTENT` only. It did not drive
`request_l2`, quote/ticker/book ingestion, freshness ticks, subscription release, quota
refresh, or reconnect recovery. Tests manually invoked `request_l2` and pushed mock
books; that proves deterministic units, not a production consumer.

### 3. Live quote and tape claims were unsupported

The real transport implemented subscribe/unsubscribe/query-subscription and order-book
reads, but no production quote/ticker ingestion populated `latest_quote` or the tape
buffer. A 1.5-second browser poll therefore did not prove a 1.5-second live market mark.

### 4. Config-only T2 promotion was unsafe

The branch introduced `effective_data_tier(cfg)`, allowing a config value to persist all
ignition rows as T2 without per-symbol fresh, entitled, confirmed, sequence-valid book
and tape evidence. The correction restores the established T0 shadow logger. Future T2
promotion requires per-event evidence, not a global switch.

### 5. Sequence integrity was optional

The T2 gate accepted a fresh book with no sequence identifier. The correction rejects
this as `SEQUENCE_UNVERIFIED`.

### 6. Fire-performance freshness failed open

A mark with a price but no parseable timestamp was treated as current. Material future
clock skew was clamped to zero age. The correction marks missing, invalid, stale, and
materially future timestamps as stale.

### 7. Fire query reintroduced alphabetical limiting

The fire query applied `LIMIT` to `DISTINCT ON (symbol) ORDER BY symbol`, so a large
session could select alphabetically rather than by global recency. The correction uses a
CTE and applies final recency order before `LIMIT`.

### 8. Current-mark fallback was N+1 database polling

The 1.5-second endpoint opened one `ticker_prices` query per fire. The correction batches
all visible symbols into one query.

### 9. MFE/MAE wording overstated coverage

The tracker stores extrema only from marks observed by the current server process. It
misses the path before first poll and loses state on restart. The correction exposes
`OBSERVED_MARKS_ONLY` and `coverage_complete_since_fire=false`; replay/finalized outcomes
remain the source of complete history.

### 10. Backend and served-UI provenance were conflated

The API preferred frontend `build-meta.json` when reporting its source commit. The
correction reports backend checkout and served UI provenance separately.

### 11. Quota failure preserved stale capacity

When `query_subscription` failed, the manager retained prior quota totals and remaining
capacity. That could authorize new subscriptions using stale provider truth. The
correction clears capacity to unknown and blocks every new request until quota is
refreshed successfully.

### 12. P0 bypassed the hard quota boundary

The original code exempted P0 from the only quota comparison. P0 should bypass the
reserved discretionary carve-out, not the provider's hard remaining quota. The
correction enforces the hard limit for all priorities.

### 13. Subscribe acceptance was mislabeled as subtype confirmation

Immediately after `subscribe()` returned success, the original manager populated every
configured subtype in `confirmed_subtypes`. It had not received a book, tape print, or
quote. The correction confirms `ORDER_BOOK`, `TICKER`, and `QUOTE` only when the
corresponding observations arrive.

### 14. Local quota was not reserved between provider refreshes

A successful request updated `own_used` but did not decrement remaining capacity or
increment total usage locally. Multiple requests between provider quota refreshes could
all evaluate against the same stale remaining value. The correction reserves and releases
local quota deterministically around confirmed transport operations.

### 15. Failed unsubscribe was reported as success

The original manager ignored the transport's unsubscribe return value and always marked
the symbol `UNSUBSCRIBED`, cleared quota, and released capacity. The correction keeps the
symbol `UNSUBSCRIBE_PENDING`, retains quota, exposes `UNSUBSCRIBE_FAILED`, and retries.

### 16. Scanner prices remain scan snapshots, not current marks

The scanner detail card still renders `trade_ai_scans.price` and `change_pct`. Those are
scan-time observations and are not refreshed by the fire-performance endpoint. This must
remain explicitly labeled as a scan snapshot until a shared current-mark projection is
added for scanner candidates. It is not a live-price feed.

### 17. The gateway singleton retained an implicit real-transport escape hatch

Even after disabling the HTTP runtime, `quote_gateway.get_gateway()` could construct the
real transport when called without injection. The correction now requires an explicit
transport for first ownership and rejects attempts to replace it with a different
transport. A future dedicated service must opt into that ownership visibly.

## Corrective changes on stacked PR #248

Implemented:

- production `get_runtime()` returns disconnected pending a dedicated gateway/IPC owner;
- the legacy scalp provider is scaffold-only and cannot construct `FutuTransport`;
- implicit real-gateway construction is prohibited;
- PR #247's config-only T2 logger changes are reverted to the PR #246 T0 baseline;
- T2 admission requires observed subtype and sequence evidence;
- unknown quota blocks every priority;
- P0 may use reserved capacity but cannot exceed hard remaining quota;
- accepted subscribe calls no longer fabricate confirmed subtypes;
- local quota is reserved/released between provider refreshes;
- failed unsubscribe remains pending and retains quota;
- untrusted mark timestamps fail stale;
- fire dedupe/order and mark batching are corrected;
- backend/UI provenance is separated;
- authority tests cover request and legacy scalp paths;
- a dedicated focused CI workflow runs the changed L2/ActiveTrader suites;
- independent audit regressions were added.

## Remaining blockers after this correction

The correction deliberately does **not** pretend to implement the missing service.
Before any live-L2 claim or deployment, a later reviewed PR must provide:

1. a dedicated long-lived Moomoo gateway service;
2. one production subscription owner;
3. IPC or normalized snapshot consumption by ActiveTrader and the scalp engine;
4. confirmed subtype accounting reconciled against OpenD truth;
5. quote, book, and ticker ingestion with separate timestamps and sequence/reconnect evidence;
6. reconnect and unsubscribe reconciliation across process restarts;
7. replay or durable feature snapshots for complete fire-path performance;
8. a current-mark projection for scanner candidates, clearly distinct from scan snapshots;
9. browser-capable tests against a running read-only server;
10. an operator-run, data-only on-host book+tape+quota round-trip.

## Authority closeout

```text
LIVE SESSION ENABLED: NO
TRADE UNLOCK CALLED: NO
REAL 2FA REQUESTED: NO
PAPER ORDER QUEUED/SUBMITTED: NO
LIVE ORDER QUEUED/SUBMITTED: NO
LIVE CREDENTIAL READ: NO
LLM FINANCIAL AUTHORITY: NONE
HOST CHANGED: NO
DATABASE WRITTEN: NO
SCHEDULE CHANGED: NO
SERVICE RESTARTS: 0
```

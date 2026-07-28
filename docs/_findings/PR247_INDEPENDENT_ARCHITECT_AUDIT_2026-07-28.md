# PR #247 Independent Architecture Audit — 2026-07-28

## Verdict

**FAIL — NOT MERGE READY** at audited head:

```text
3aa1ab33cbf7b2d4cc731aeb1cc61f8368e60732
```

The green mock test suite does not establish the production claims in the PR body.
The correction branch intentionally fails closed rather than manufacturing a live L2
consumer.

## Controlling boundaries

- one long-lived gateway owns production Moomoo subscriptions;
- request handlers and cron jobs consume normalized snapshots and do not open competing
  OpenD contexts;
- arm intent, provider reachability, entitlement, confirmed subscription, fresh data,
  sequence integrity, tape evidence, and T2 admission are distinct facts;
- configuration alone cannot promote a symbol or event to T2;
- missing or untrusted timestamps fail stale;
- no order, trade unlock, real 2FA, credential exposure, or LLM authority exists here.

## Blocking findings

### 1. The claimed single owner did not exist

`active_trader/l2_runtime.py` lazily opened a process-local gateway from the HTTP request
process, while `scalp_shadow_logger.py` still called the legacy
`market_observations/moomoo_t2.default_provider()` on each live cron invocation.  That
legacy provider constructed its own `FutuTransport` and OpenQuoteContext.  The two
processes did not share subscription lifecycle, buffers, quota state, or reconnect epoch.

The original AST guard inspected only the new module list and did not include the legacy
scalp path.

### 2. No production ingestion loop drove the new manager

The HTTP runtime restored desired symbols as `ARM_INTENT` only.  It did not drive
`request_l2`, quote/ticker/book ingestion, freshness ticks, subscription release, quota
refresh, or reconnect recovery.  Tests manually invoked `request_l2` and manually pushed
mock books; that proves deterministic units, not a production consumer.

### 3. Live quote and tape claims were unsupported

The real transport implemented subscribe/unsubscribe/query-subscription and order-book
reads, but no production quote/ticker ingestion populated `latest_quote` or the tape
buffer.  The 1.5-second browser poll therefore did not prove a 1.5-second live market
mark.

### 4. Config-only T2 promotion was unsafe

The branch introduced `effective_data_tier(cfg)`, allowing a config value to persist all
ignition rows as T2 without a per-symbol fresh/entitled/confirmed/sequence-valid book and
tape decision.  The correction restores the established T0 shadow logger.  Future T2
promotion requires per-event evidence, not a global switch.

### 5. Sequence integrity was optional

The T2 gate accepted a fresh book with no sequence identifier.  The correction rejects
this as `SEQUENCE_UNVERIFIED`.

### 6. Fire-performance freshness failed open

A mark with a price but no parseable timestamp was treated as current.  Material future
clock skew was clamped to zero age.  The correction marks missing, invalid, stale, and
materially future timestamps as stale.

### 7. Fire query reintroduced alphabetical limiting

The fire query applied `LIMIT` to `DISTINCT ON (symbol) ORDER BY symbol`, so a large
session could select alphabetically rather than by global recency.  The correction uses
a CTE and applies the final recency order before `LIMIT`.

### 8. Current-mark fallback was N+1 database polling

The 1.5-second endpoint opened one `ticker_prices` query per fire.  The correction batches
all visible symbols into one query.

### 9. MFE/MAE wording overstated coverage

The tracker stores extrema only from marks observed by the current server process.  It
misses the path before first poll and loses state on restart.  The correction exposes
`OBSERVED_MARKS_ONLY` and `coverage_complete_since_fire=false`; replay/finalized outcomes
remain the source of complete history.

### 10. Backend and served-UI provenance were conflated

The API preferred frontend `build-meta.json` when reporting its source commit.  The
correction reports backend checkout and served UI provenance separately.

## Corrective changes on stacked branch

Branch:

```text
agent/pr247-l2-truth-audit-fixes-v1
```

Implemented:

- production `get_runtime()` returns disconnected pending a dedicated gateway/IPC owner;
- legacy scalp provider is scaffold-only and cannot construct `FutuTransport`;
- PR #247's config-only T2 logger changes are reverted to the PR #246 T0 baseline;
- T2 admission requires sequence evidence;
- untrusted mark timestamps fail stale;
- fire dedupe/order and mark batching are corrected;
- backend/UI provenance is separated;
- authority tests cover the request and legacy scalp paths;
- independent audit regressions were added.

## Remaining blockers after this correction

This correction deliberately does **not** pretend to implement the missing service.
Before any live-L2 claim or deployment, a later reviewed PR must provide:

1. a dedicated long-lived Moomoo gateway service;
2. one production subscription owner;
3. IPC or normalized snapshot consumption by ActiveTrader and the scalp engine;
4. confirmed subtype accounting from OpenD truth;
5. fail-closed quota admission, including P0;
6. quote, book, and ticker ingestion with timestamps and sequence/reconnect evidence;
7. reconnect and unsubscribe reconciliation;
8. replay or durable feature snapshots for complete fire-path performance;
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

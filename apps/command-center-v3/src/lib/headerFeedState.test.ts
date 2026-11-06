// Pure-logic tests for headerFeedState.ts — synthetic fixtures only.
// No HTTP (never 127.0.0.1:7777), no broker, no real portfolio, holdings or
// account data.
//   node --experimental-strip-types apps/command-center-v3/src/lib/headerFeedState.test.ts
import { deriveHeaderFeedState } from './headerFeedState.ts'
import type { HeaderFeed } from './headerFeedState.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

function feed(over: Partial<HeaderFeed> = {}): HeaderFeed {
  return {
    key: 'overview',
    label: 'overview',
    hasData: false,
    loading: false,
    error: null,
    stale: false,
    ...over,
  }
}

// ---- (a) still loading -------------------------------------------------------
{
  const s = deriveHeaderFeedState([feed({ loading: true })])
  check('pending first load is the loading state', s.state === 'loading')
  check('loading names the pending feed', s.pending.join() === 'overview')
  check('loading says what it is doing', /Loading header metrics/.test(s.message ?? ''))
  check('loading is not retryable (nothing has failed)', s.retryable === false)
  check('loading is not an error and not stale', s.state !== 'error' && s.state !== 'stale')
}

// A slow queue with several feeds still in flight.
{
  const s = deriveHeaderFeedState([
    feed({ key: 'overview', label: 'overview', loading: true }),
    feed({ key: 'regime', label: 'risk regime', loading: true }),
  ])
  check('several pending feeds still read as loading', s.state === 'loading')
  check('every pending feed is named', s.pending.join() === 'overview,risk regime')
}

// ---- (b) request failed / timeout -------------------------------------------
{
  const s = deriveHeaderFeedState([feed({ error: 'request timed out after 30s' })])
  check('a failed request is the error state', s.state === 'error')
  check('error names the failed feed', s.failed.join() === 'overview')
  check('error carries the real message, not a made-up one', /timed out/.test(s.detail ?? ''))
  check('error is offered a retry', s.retryable === true)
  check('error message is not the stale message', !/last good/i.test(s.message ?? ''))
  check('error message is not the unknown/empty message', !/no payload/i.test(s.message ?? ''))
}

// A failure and a still-pending sibling: the failure wins until it is resolved.
{
  const s = deriveHeaderFeedState([
    feed({ key: 'overview', label: 'overview', error: 'HTTP 502' }),
    feed({ key: 'tradeAi', label: 'trade AI summary', loading: true }),
  ])
  check('failure outranks a pending sibling', s.state === 'error')
  check('error detail carries the failing feed message', s.detail === 'HTTP 502')
}

// ---- (c) data present but stale (last good retained) ------------------------
{
  const s = deriveHeaderFeedState([feed({ hasData: true, stale: true })])
  check('retained last-good data is the stale state', s.state === 'stale')
  check('stale names the feed that failed to refresh', s.staleFeeds.join() === 'overview')
  check('stale says it is showing last good data', /last good data/i.test(s.message ?? ''))
  check('stale is not the error state', s.state !== 'error')
  check('stale is retryable', s.retryable === true)
}

// A refresh failure with data retained is stale, not error: there IS something
// to show, and it is old. The error text is still carried verbatim.
{
  const s = deriveHeaderFeedState([feed({ hasData: true, error: 'upstream 502', stale: true })])
  check('failed refresh with data is stale, not error', s.state === 'stale')
  check('stale keeps the underlying error text', /upstream 502/.test(s.detail ?? ''))
}

// ---- (d) unknown / no payload ------------------------------------------------
{
  const s = deriveHeaderFeedState([feed()])
  check('settled with no payload is the unknown state', s.state === 'unknown')
  check('unknown is not loading', s.state !== 'loading')
  check('unknown is not an error', s.state !== 'error')
  check('unknown says no payload was returned', /no payload/i.test(s.message ?? ''))
  check('unknown is retryable', s.retryable === true)
}

// ---- success -----------------------------------------------------------------
{
  const s = deriveHeaderFeedState([feed({ hasData: true })])
  check('data with no failure is ready', s.state === 'ready')
  check('ready has no banner message', s.message === null)
  check('ready names the available feed', s.available.join() === 'overview')
  check('ready is not retryable', s.retryable === false)
  check('ready has no fabricated detail', s.detail === null)
}

// ---- partial: one ready feed, one failed with no payload --------------------
{
  const s = deriveHeaderFeedState([
    feed({ key: 'overview', label: 'overview', hasData: true }),
    feed({ key: 'tradeAi', label: 'trade AI summary', error: 'HTTP 500' }),
  ])
  check('a partial failure is still the error state', s.state === 'error')
  check('partial error names only the unavailable feed', s.failed.join() === 'trade AI summary')
  check('partial error keeps the available feed on screen', s.available.join() === 'overview')
  check('partial error says only some feeds are unavailable', /Some header feeds/.test(s.message ?? ''))
}

// ---- partial: data present, another feed still on first load ----------------
{
  const s = deriveHeaderFeedState([
    feed({ key: 'overview', label: 'overview', hasData: true }),
    feed({ key: 'regime', label: 'risk regime', loading: true }),
  ])
  check('partial + pending reads as loading the remainder', s.state === 'loading')
  check('partial loading says "remaining"', /remaining/.test(s.message ?? ''))
  check('partial loading keeps the loaded feed available', s.available.join() === 'overview')
}

// ---- ordering and no-data edge ----------------------------------------------
{
  const s = deriveHeaderFeedState([
    feed({ key: 'overview', label: 'overview', error: 'first' }),
    feed({ key: 'regime', label: 'risk regime', error: 'second' }),
  ])
  check('failed feeds are listed in input order', s.failed.join() === 'overview,risk regime')
  check('distinct error texts are joined honestly', s.detail === 'first · second')
}

{
  const s = deriveHeaderFeedState([])
  check('no feeds is unknown, never a false ready', s.state === 'unknown')
  check('no feeds names nothing', s.failed.length === 0 && s.available.length === 0)
  check('no feeds names no unavailable source', s.unavailable.length === 0)
}

// ---- partial unknown: one ready feed, one settled with no payload -----------
// The BLOCK review's case: a source answering 200 with a null payload while a
// sibling is healthy. It used to return ready with no banner and no Retry.
{
  const s = deriveHeaderFeedState([
    feed({ key: 'overview', label: 'overview', hasData: true }),
    feed({ key: 'tradeAi', label: 'trade AI summary' }), // settled, no payload, no error
  ])
  check('a ready feed beside a settled-empty feed is unknown, never ready', s.state === 'unknown')
  check('partial unknown names the settled-empty feed', s.unavailable.join() === 'trade AI summary')
  check('partial unknown keeps the loaded feed available', s.available.join() === 'overview')
  check('partial unknown is retryable', s.retryable === true)
  check('partial unknown has a banner message', s.message !== null)
  check('partial unknown says a payload is missing', /no payload/i.test(s.message ?? ''))
  check('partial unknown is not an error', s.state !== 'error')
  check('partial unknown does not borrow the stale message', !/last good/i.test(s.message ?? ''))
}

// A settled-empty source outranks a still-loading sibling: one is a fact, the
// other is only a hope.
{
  const s = deriveHeaderFeedState([
    feed({ key: 'overview', label: 'overview', loading: true }),
    feed({ key: 'regime', label: 'risk regime' }), // settled empty
  ])
  check('a settled-empty feed outranks a still-loading sibling', s.state === 'unknown')
  check('unknown precedence names the empty source', s.unavailable.join() === 'risk regime')
  check('unknown precedence still reports the pending source', s.pending.join() === 'overview')
  check('unknown precedence is retryable', s.retryable === true)
}

// ---- partial loading: one ready feed, one still on first load ---------------
{
  const s = deriveHeaderFeedState([
    feed({ key: 'overview', label: 'overview', hasData: true }),
    feed({ key: 'regime', label: 'risk regime', loading: true }),
  ])
  check('a ready feed beside a first-load feed is loading', s.state === 'loading')
  check('partial loading names the pending feed', s.pending.join() === 'risk regime')
  check('partial loading says it is loading the remainder', /remaining/.test(s.message ?? ''))
  check('partial loading is not retryable (nothing failed)', s.retryable === false)
  check('partial loading keeps the loaded feed available', s.available.join() === 'overview')
}

// ---- error precedence over unknown and loading ------------------------------
{
  const s = deriveHeaderFeedState([
    feed({ key: 'overview', label: 'overview', hasData: true }),
    feed({ key: 'regime', label: 'risk regime' }), // settled empty
    feed({ key: 'tradeAi', label: 'trade AI summary', error: 'HTTP 502' }),
  ])
  check('an error outranks a settled-empty feed', s.state === 'error')
  check('error precedence names the failed feed', s.failed.join() === 'trade AI summary')
  check('error precedence still reports the settled-empty feed', s.unavailable.join() === 'risk regime')
  check('error precedence wins over ready data', s.available.join() === 'overview')
  check('error precedence carries the transport text', s.detail === 'HTTP 502')
}

{
  const s = deriveHeaderFeedState([
    feed({ key: 'overview', label: 'overview', error: 'HTTP 502' }),
    feed({ key: 'regime', label: 'risk regime', loading: true }),
    feed({ key: 'tradeAi', label: 'trade AI summary' }), // settled empty
  ])
  check('failure outranks unknown and loading at once', s.state === 'error')
  check('failure precedence names the failed feed only', s.failed.join() === 'overview')
  check('failure precedence is retryable', s.retryable === true)
}

// ---- stale still outranks a loading sibling (unchanged semantics) -----------
{
  const s = deriveHeaderFeedState([
    feed({ key: 'overview', label: 'overview', hasData: true, stale: true }),
    feed({ key: 'regime', label: 'risk regime', loading: true }),
  ])
  check('stale last-good data outranks a loading sibling', s.state === 'stale')
  check('stale still names the retained feed', s.staleFeeds.join() === 'overview')
}

console.log(`\nheaderFeedState: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

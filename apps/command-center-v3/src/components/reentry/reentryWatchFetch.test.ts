// LQ-20261113-3062 (review 3051 A3): a watchlist 503 is UNKNOWN with its retry hint, never an empty row.
//   node --experimental-strip-types src/components/reentry/reentryWatchFetch.test.ts
// Synthetic responses only: fetch is injected, no server, no network.
import {
  DEFAULT_RETRY_SEC, MAX_RETRIES, MAX_RETRY_SEC, WATCH_CHUNK, fetchWatchChunk, loadWatchMap, retryDelaySec,
  unknownSymbols, watchUnknownMessage,
} from './reentryWatchFetch.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

// The StaleServe 503 body (scripts/lib/stale_serve.py, field name per LQ-3051 A1).
const DEFERRED = { ok: false, status: 'UNKNOWN', state: 'UNKNOWN', error: 'build_deferred', reason: 'REFUSED_CAP', retry_after_sec: 5 }
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const calls: string[] = []
const answering = (fn: (url: string) => Response | Promise<Response>) => async (url: string) => { calls.push(url); return fn(url) }

console.log('503 build_deferred -> UNKNOWN')
{
  const got = await fetchWatchChunk(answering(() => json(503, DEFERRED)), ['AAA', 'BBB'])
  check('no items written', Object.keys(got.items).length === 0)
  check('one UNKNOWN entry', got.unknown.length === 1)
  const u = got.unknown[0]
  check('state UNKNOWN', u?.state === 'UNKNOWN')
  check('names every symbol of the chunk', JSON.stringify(u?.symbols) === JSON.stringify(['AAA', 'BBB']))
  check('carries HTTP 503', u?.httpStatus === 503)
  check('carries error build_deferred', u?.error === 'build_deferred')
  check('carries reason REFUSED_CAP', u?.reason === 'REFUSED_CAP')
  check('carries retry_after_sec 5', u?.retryAfterSec === 5)
  const msg = watchUnknownMessage(got.unknown, { inSec: retryDelaySec(got.unknown), attempt: 0 })
  check('message says UNKNOWN', msg.includes('UNKNOWN'))
  check('message names HTTP 503 build_deferred', msg.includes('HTTP 503 build_deferred (REFUSED_CAP)'))
  check('message carries the retry hint', msg.includes('retrying in 5 s'))
  check('message says not empty', msg.includes('not known, not empty'))
}

console.log('other non-OK answers')
{
  const noBody = await fetchWatchChunk(answering(() => new Response('upstream down', { status: 502 })), ['CCC'])
  check('502 with a non-JSON body is UNKNOWN', noBody.unknown[0]?.httpStatus === 502 && noBody.unknown[0]?.error === 'HTTP 502')
  const okFalse = await fetchWatchChunk(answering(() => json(200, { ok: false, error: 'source_unavailable' })), ['DDD'])
  check('200 ok:false is UNKNOWN', okFalse.unknown[0]?.error === 'source_unavailable')
  const noItems = await fetchWatchChunk(answering(() => json(200, { ok: true })), ['EEE'])
  check('200 with no items list is UNKNOWN', noItems.unknown[0]?.error === 'no items list in the answer')
  const header = await fetchWatchChunk(answering(() => new Response('{}', { status: 503, headers: { 'Retry-After': '9' } })), ['FFF'])
  check('Retry-After header is the hint when the body has none', header.unknown[0]?.retryAfterSec === 9)
  const thrown = await fetchWatchChunk(async () => { throw new TypeError('Failed to fetch') }, ['GGG'])
  check('a network error is UNKNOWN with no HTTP status', thrown.unknown[0]?.httpStatus === null && thrown.unknown[0]?.error === 'Failed to fetch')
  check('a network error names the chunk\'s symbols', JSON.stringify(thrown.unknown[0]?.symbols) === JSON.stringify(['GGG']))
  let aborted = false
  try {
    await fetchWatchChunk(async () => { throw Object.assign(new Error('aborted'), { name: 'AbortError' }) }, ['HHH'])
  } catch (error) { aborted = (error as any)?.name === 'AbortError' }
  check('an abort propagates (unmount), it is not an UNKNOWN', aborted)
}

console.log('200 items still read')
{
  const got = await fetchWatchChunk(answering(() => json(200, { ok: true, data: { items: [{ symbol: 'aaa', last_price: 10 }] } })), ['AAA'])
  check('item keyed upper-case', got.items.AAA?.last_price === 10)
  check('no UNKNOWN', got.unknown.length === 0)
}

console.log('chunked load: a 503 chunk does not hide the good chunk, and never drops a symbol')
{
  calls.length = 0
  const symbols = Array.from({ length: WATCH_CHUNK + 3 }, (_, i) => `S${i}`)
  const got = await loadWatchMap(answering((url) => {
    const list = decodeURIComponent(url.split('symbols=')[1]).split(',')
    return list.includes('S0') ? json(503, DEFERRED) : json(200, { items: list.map(symbol => ({ symbol, last_price: 1 })) })
  }), symbols)
  check('two chunk requests', calls.length === 2)
  check('the good chunk is read', Object.keys(got.items).length === 3)
  check('the 503 chunk is UNKNOWN', unknownSymbols(got.unknown).size === WATCH_CHUNK)
  check('every symbol is either read or UNKNOWN', symbols.every(s => s in got.items || unknownSymbols(got.unknown).has(s)))
}

console.log('retry delay and exhaustion')
{
  const u = (retryAfterSec: number | null) => ({ state: 'UNKNOWN' as const, symbols: ['X'], httpStatus: 503, error: 'build_deferred', reason: null, retryAfterSec })
  check('largest server hint wins', retryDelaySec([u(5), u(30)]) === 30)
  check('no hint -> default', retryDelaySec([u(null)]) === DEFAULT_RETRY_SEC)
  check('hint clamped to the max', retryDelaySec([u(99999)]) === MAX_RETRY_SEC)
  check('fractional hint rounds up', retryDelaySec([u(0.2)]) === 1)
  const stopped = watchUnknownMessage([u(5)], { inSec: null, attempt: MAX_RETRIES })
  check('exhausted retries say so, still UNKNOWN', stopped.includes('UNKNOWN') && stopped.includes(`retry stopped after ${MAX_RETRIES} retries`))
  check('nothing unknown -> no message', watchUnknownMessage([], { inSec: null, attempt: 0 }) === '')
}

console.log(`\n${pass} passed, ${fail} failed`)
process.exit(fail ? 1 : 0)

// Pure-logic tests for httpOutcome.ts. Runnable with Node type-stripping:
//   node apps/command-center-v3/src/lib/httpOutcome.test.ts
//
// The defect: `if (!r.ok) throw` put 401 and 403 in the same bucket as a socket
// timeout, so the client burned an 8-step backoff ladder plus a 30s slow-retry
// loop against an endpoint that would never say yes, and told the operator it was
// "reconnecting". These assertions pin the separation.
import {
  classifyStatus, classifyError, parseRetryAfter, countsAsConnectionFailure,
} from './httpOutcome.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

const H = (h: Record<string, string>) => ({ get: (k: string) => h[k] ?? h[k.toLowerCase()] ?? null })

// ── authorization is terminal ────────────────────────────────────────────────
{
  for (const [status, kind] of [[401, 'UNAUTHORIZED'], [403, 'FORBIDDEN']] as const) {
    const o = classifyStatus(status, null)
    check(`${status} is ${kind}`, o.kind === kind)
    check(`${status} is terminal`, o.terminal === true)
    check(`${status} is NOT retryable`, o.retryable === false)
    check(`${status} does not raise the reconnect banner`, countsAsConnectionFailure(o) === false)
    check(`${status} keeps the last-good body`, o.keepLastGood === true)
    check(`${status} says waiting will not help`, o.message.includes('will not resolve by waiting'))
    check(`${status} never says reconnecting`, !/reconnect/i.test(o.message))
  }
}

// ── other 4xx are terminal too: repeating a wrong request stays wrong ─────────
{
  for (const status of [400, 404, 409, 422]) {
    const o = classifyStatus(status, null)
    check(`${status} is CLIENT_ERROR`, o.kind === 'CLIENT_ERROR')
    check(`${status} is terminal`, o.terminal === true)
    check(`${status} is not retryable`, o.retryable === false)
  }
}

// ── the retryable classes stay retryable ─────────────────────────────────────
{
  const cases: Array<[number, string]> = [
    [408, 'TIMEOUT'], [425, 'TIMEOUT'], [429, 'RATE_LIMITED'],
    [500, 'SERVER_ERROR'], [502, 'SERVER_ERROR'], [503, 'SERVER_BUSY'], [504, 'SERVER_ERROR'],
  ]
  for (const [status, kind] of cases) {
    const o = classifyStatus(status, null)
    check(`${status} is ${kind}`, o.kind === kind)
    check(`${status} is retryable`, o.retryable === true)
    check(`${status} is not terminal`, o.terminal === false)
  }
  check('503 does not raise the reconnect banner', countsAsConnectionFailure(classifyStatus(503, null)) === false)
  check('500 does raise the reconnect banner', countsAsConnectionFailure(classifyStatus(500, null)) === true)
}

// ── success and revalidation ─────────────────────────────────────────────────
{
  const ok = classifyStatus(200, null)
  check('200 is OK', ok.kind === 'OK' && !ok.terminal && !ok.retryable)
  const nm = classifyStatus(304, null)
  check('304 is NOT_MODIFIED', nm.kind === 'NOT_MODIFIED')
  check('304 keeps the last-good body', nm.keepLastGood === true)
  check('304 is not an error to retry', nm.retryable === false && nm.terminal === false)
}

// ── Retry-After ──────────────────────────────────────────────────────────────
{
  const now = Date.parse('2026-09-03T20:00:00Z')
  check('delta-seconds parses', parseRetryAfter('30', now) === 30_000)
  check('zero is honoured, not treated as absent', parseRetryAfter('0', now) === 0)
  check('an HTTP-date parses to a delay', parseRetryAfter('Thu, 03 Sep 2026 20:00:45 GMT', now) === 45_000)
  check('a past date clamps to zero', parseRetryAfter('Thu, 03 Sep 2026 19:59:00 GMT', now) === 0)
  check('an absurd delay is capped', parseRetryAfter('999999', now) === 5 * 60_000)
  check('garbage is null, not a guess', parseRetryAfter('soon', now) === null)
  check('missing is null', parseRetryAfter(null, now) === null)
  check('empty is null', parseRetryAfter('   ', now) === null)

  const limited = classifyStatus(429, H({ 'Retry-After': '12' }), now)
  check('429 carries the server-directed delay', limited.retryAfterMs === 12_000)
  const busy = classifyStatus(503, H({ 'Retry-After': '3' }), now)
  check('503 carries the server-directed delay', busy.retryAfterMs === 3_000)
  check('401 exposes no retry delay to act on', classifyStatus(401, H({ 'Retry-After': '5' }), now).retryable === false)
}

// ── thrown errors ────────────────────────────────────────────────────────────
{
  const abort = classifyError(Object.assign(new Error('aborted'), { name: 'AbortError' }))
  check('an abort is a TIMEOUT', abort.kind === 'TIMEOUT')
  check('an abort is retryable', abort.retryable === true)
  check('an abort raises the reconnect banner', countsAsConnectionFailure(abort) === true)

  const net = classifyError(new Error('Failed to fetch'))
  check('a network error is NETWORK', net.kind === 'NETWORK')
  check('a network error is retryable', net.retryable === true)
  check('a network error keeps the last-good body', net.keepLastGood === true)
}

// ── the separation itself ────────────────────────────────────────────────────
{
  const auth = classifyStatus(403, null)
  const busy = classifyStatus(503, null)
  check('authorization and busy are not the same class', auth.kind !== busy.kind)
  check('only one of them is retryable', auth.retryable !== busy.retryable)
  check('only one of them is terminal', auth.terminal !== busy.terminal)
}

console.log(`\nhttpOutcome: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)

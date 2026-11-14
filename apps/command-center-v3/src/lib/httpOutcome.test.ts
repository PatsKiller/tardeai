// Pure-logic tests for httpOutcome.ts. Runnable with Node type-stripping:
//   node apps/command-center-v3/src/lib/httpOutcome.test.ts
//
// The defect: `if (!r.ok) throw` put 401 and 403 in the same bucket as a socket
// timeout, so the client burned an 8-step backoff ladder plus a 30s slow-retry
// loop against an endpoint that would never say yes, and told the operator it was
// "reconnecting". These assertions pin the separation.
import {
  classifyStatus, classifyError, parseRetryAfter, countsAsConnectionFailure, parseErrorBody,
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

// ── the server's typed refusal survives classification ──────────────────────
{
  const refused = parseErrorBody(JSON.stringify({ ok: false, error: 'AGENT_CALLER_REFUSED', detail: 'Ask the CIO answers only the operator’s tailnet identity' }))
  check('the typed code is read from the body', refused.code === 'AGENT_CALLER_REFUSED')
  check('the server detail is kept', refused.detail === 'Ask the CIO answers only the operator’s tailnet identity')
  const noDetail = parseErrorBody(JSON.stringify({ ok: false, error: 'CSRF_REFUSED' }))
  check('a missing detail is null, never an invented sentence', noDetail.detail === null)
  check('a code survives without a detail', noDetail.code === 'CSRF_REFUSED')
  check('empty text is no code', parseErrorBody('').code === null && parseErrorBody('').detail === null)
  check('null text is no code', parseErrorBody(null).code === null)
  check('non-JSON is no code', parseErrorBody('<html>502 Bad Gateway</html>').code === null)
  check('a JSON array is no code', parseErrorBody('[1,2]').code === null)
  check('a lowercase word is not echoed as a code', parseErrorBody(JSON.stringify({ error: 'refused' })).code === null)
  check('an object error is not echoed as a code', parseErrorBody(JSON.stringify({ error: { code: 'X' } })).code === null)
  check('a whitespace code is trimmed', parseErrorBody(JSON.stringify({ error: '  NOT_FOUND  ' })).code === 'NOT_FOUND')
  check('a long detail is clipped', (parseErrorBody(JSON.stringify({ detail: 'x'.repeat(900) })).detail ?? '').length === 400)
  check('an HTTP_403 fallback code is accepted as a code', parseErrorBody(JSON.stringify({ error: 'HTTP_403' })).code === 'HTTP_403')
}

console.log(`\nhttpOutcome: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)

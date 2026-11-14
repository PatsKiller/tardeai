/** PR-016: the Risk page's decisions are built only from served counts. A null count (cio_truth nulls them when the
 *  broker read did not complete) must read as "not readable", never as zero and never as "nothing to review".
 *  Synthetic fixtures only — no live state, no broker. */
import assert from 'node:assert/strict'
import { riskDecisions } from './riskDecisions.ts'

// 1. No stops block: the page has not loaded a record, so it invents no decision.
assert.deepEqual(riskDecisions(undefined), [])
assert.deepEqual(riskDecisions({}), [])

// 2. Every count null with a served gap reason: one item that says the read failed, quoting the server's reason.
{
  const d = riskDecisions({ stops: { unprotected_count: null, unproven_count: null, pending_count: null, filled_count: null,
    gap: { reason: 'The last broker stop read did not complete (timeout).' } } })
  assert.equal(d.length, 1)
  assert.equal(d[0].id, 'stops-unreadable')
  assert.match(d[0].title, /not readable/)
  assert.equal(d[0].detail, 'The last broker stop read did not complete (timeout).')
  assert.equal(d[0].href, '/ops/health')
  assert.doesNotMatch(d[0].title, /\b0\b/, 'an unreadable count never prints as a zero')
}

// 3. Readable counts: one item per populated count, in review order, each routed to the evidence.
{
  const d = riskDecisions({ stops: { unproven_count: 2, unprotected_count: 5, pending_count: 8, filled_count: 0 } })
  assert.deepEqual(d.map(x => x.id), ['stops-unproven', 'stops-unprotected', 'stops-pending'])
  assert.match(d[0].title, /^Check 2 stops whose state was not recorded$/)
  assert.match(d[1].title, /^Review 5 counted positions with no broker stop$/)
  assert.match(d[2].title, /^8 resting stops are still awaiting activation$/)
  for (const x of d) assert.equal(x.href, '/portfolio?tab=Stop%20Management')
  assert.equal(d[2].title.includes('0'), false, 'a zero count adds no decision')
}

// 4. Singular wording and the filled queue's own destination.
{
  const d = riskDecisions({ stops: { unproven_count: 0, unprotected_count: 1, pending_count: 1, filled_count: 3 } })
  assert.deepEqual(d.map(x => x.id), ['stops-unprotected', 'stops-pending', 'stops-filled'])
  assert.match(d[0].title, /^Review 1 counted position with no broker stop$/)
  assert.match(d[1].title, /^1 resting stop is still awaiting activation$/)
  assert.match(d[2].title, /^3 stops have filled and await the holdings sync$/)
  assert.equal(d[2].href, '/risk?tab=exposure')
}

// 5. A readable book with nothing to review yields no decision — the page then says no served count names an item.
assert.deepEqual(riskDecisions({ stops: { unproven_count: 0, unprotected_count: 0, pending_count: 0, filled_count: 0 } }), [])

console.log('riskDecisions.test.ts: ok')

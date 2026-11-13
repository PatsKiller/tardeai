// Combined Home (operator controlling decision 2026-11-13): every hook for a path is a subscriber of ONE shared record.
// Pins: a subscriber whose poll comes due inside its own cadence takes the shared body (no second GET); polling pauses
// while the document is hidden; becoming visible reads at once; an operator refetch always reaches the server; a body
// read by one subscriber is handed to every other subscriber of that path, and to no other path.
// Synthetic values only.
import assert from 'node:assert/strict'
import {
  SHARED_ONE_SHOT_MS, listLastGood, noteLastGood, peekLastGood, resetLastGood, sharedPollAction, subscribeAnyBody, subscribeBody,
} from './useApi.ts'

const base = { manual: false, visible: true }

// ── reuse inside the subscriber's own cadence ────────────────────────────────────────────────────────
assert.equal(sharedPollAction({ ...base, held: null, nowMs: 1_000, intervalMs: 60_000, reason: 'mount' }), 'fetch', 'nothing held: read')
assert.equal(sharedPollAction({ ...base, held: { at: 0 }, nowMs: 30_000, intervalMs: 60_000, reason: 'tick' }), 'reuse', '30 s old body, 60 s poll: reuse')
assert.equal(sharedPollAction({ ...base, held: { at: 0 }, nowMs: 53_999, intervalMs: 60_000, reason: 'tick' }), 'reuse', 'inside 90% of the interval')
assert.equal(sharedPollAction({ ...base, held: { at: 0 }, nowMs: 54_000, intervalMs: 60_000, reason: 'tick' }), 'fetch', 'at 90% of the interval the body is due')
assert.equal(sharedPollAction({ ...base, held: { at: 0 }, nowMs: 100_000, intervalMs: 120_000, reason: 'tick' }), 'reuse',
  'a 120 s subscriber never re-reads a path a 60 s subscriber keeps fresh')
assert.equal(sharedPollAction({ ...base, held: { at: 10_000 }, nowMs: 5_000, intervalMs: 60_000, reason: 'tick' }), 'fetch', 'a body from the future is not trusted')
// one-shot hooks share only a burst
assert.equal(sharedPollAction({ ...base, held: { at: 0 }, nowMs: SHARED_ONE_SHOT_MS - 1, reason: 'mount' }), 'reuse')
assert.equal(sharedPollAction({ ...base, held: { at: 0 }, nowMs: SHARED_ONE_SHOT_MS, reason: 'mount' }), 'fetch', 'a one-shot read outside the burst reaches the server')

// ── operator refetch always reaches the server ───────────────────────────────────────────────────────
assert.equal(sharedPollAction({ ...base, manual: true, held: { at: 0 }, nowMs: 1, intervalMs: 60_000, reason: 'tick' }), 'fetch')
assert.equal(sharedPollAction({ ...base, manual: true, visible: false, held: null, nowMs: 1, intervalMs: 60_000, reason: 'tick' }), 'fetch')

// ── hidden tab: polls pause; mount and visible-again read ────────────────────────────────────────────
assert.equal(sharedPollAction({ ...base, visible: false, held: null, nowMs: 1, intervalMs: 60_000, reason: 'tick' }), 'paused', 'hidden: an interval tick does nothing')
assert.equal(sharedPollAction({ ...base, visible: false, held: { at: 0 }, nowMs: 600_000, intervalMs: 60_000, reason: 'tick' }), 'paused')
assert.equal(sharedPollAction({ ...base, visible: false, held: null, nowMs: 1, intervalMs: 60_000, reason: 'mount' }), 'fetch', 'first paint still reads once')
assert.equal(sharedPollAction({ ...base, held: { at: 0 }, nowMs: 600_000, intervalMs: 60_000, reason: 'visible' }), 'fetch', 'visible again with an old body: immediate read')
assert.equal(sharedPollAction({ ...base, held: { at: 590_000 }, nowMs: 600_000, intervalMs: 60_000, reason: 'visible' }), 'reuse',
  'visible again: the first subscriber reads, the others take its body')

// ── one body, every subscriber of that path, no other path ───────────────────────────────────────────
resetLastGood()
{
  const seenA: unknown[] = []
  const seenB: unknown[] = []
  const seenOther: unknown[] = []
  const changed: string[] = []
  const offA = subscribeBody('/api/x', j => seenA.push(j))
  const offB = subscribeBody('/api/x', j => seenB.push(j))
  const offO = subscribeBody('/api/y', j => seenOther.push(j))
  const offAny = subscribeAnyBody(p => changed.push(p))
  const self = (j: unknown) => seenA.push(['self', j])
  const offSelf = subscribeBody('/api/x', self)
  noteLastGood('/api/x', { v: 1 }, 1_000, self)
  assert.deepEqual(seenA, [{ v: 1 }])
  assert.deepEqual(seenB, [{ v: 1 }])
  assert.deepEqual(seenOther, [], 'a different path never receives the body')
  assert.equal(seenA.filter(x => Array.isArray(x)).length, 0, 'the reader that applied the body is not handed it twice')
  assert.deepEqual(changed, ['/api/x'])
  assert.deepEqual(peekLastGood('/api/x'), { json: { v: 1 }, at: 1_000 })
  assert.deepEqual(listLastGood().map(([p]) => p), ['/api/x'])
  offB()
  noteLastGood('/api/x', { v: 2 }, 2_000)
  assert.deepEqual(seenB, [{ v: 1 }], 'an unsubscribed hook gets nothing more')
  offA(); offO(); offAny(); offSelf()
}
resetLastGood()
assert.equal(peekLastGood('/api/x'), null)
console.log('useApiShared: ok')

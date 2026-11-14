// OBS-R2 (operator, live Chrome 2026-11-14): the Risk page printed two clocks — Positions · Nov 14, 11:00 ET
// and Stops · last broker read Nov 13, 8:55 PM ET — with no statement of whether they describe the same book.
// One shared rule: the stop read is reconciled when it is at or after the positions snapshot; otherwise it is
// unreconciled SINCE the stop read, and the reason says what that means. Unknown clocks are never "reconciled".
// Synthetic fixtures only (public repo): no real accounts, symbols or values.
import assert from 'node:assert/strict'
import { stopReconciliation } from './stopReconciliation.ts'

const POS = '2031-03-07T16:00:00Z'      // positions snapshot
const STOP_OLD = '2031-03-06T21:55:00Z' // stop read 18.1 h earlier
const STOP_SAME = '2031-03-07T16:00:00Z'
const STOP_NEW = '2031-03-07T18:30:00Z'

// --- reconciled -------------------------------------------------------------------------------------------
const same = stopReconciliation({ positionsAsOf: POS, stopsAsOf: STOP_SAME })
assert.equal(same.state, 'reconciled')
assert.equal(same.since, null)
assert.match(same.reason, /at or after the positions snapshot/)

const newer = stopReconciliation({ positionsAsOf: POS, stopsAsOf: STOP_NEW })
assert.equal(newer.state, 'reconciled', 'a stop read newer than the snapshot is not an unreconciled pair')

// --- unreconciled since the stop read, with the size of the gap in the reason ------------------------------
const old = stopReconciliation({ positionsAsOf: POS, stopsAsOf: STOP_OLD })
assert.equal(old.state, 'unreconciled')
assert.equal(old.since, STOP_OLD, 'the pair has been out of step since the stop read')
assert.match(old.reason, /18\.1 h older than the positions snapshot/)
assert.match(old.reason, /opened, closed or resized after that read/)

// A second shape the same rule must handle: an unreadable-but-present stop clock is unknown, never reconciled.
const malformed = stopReconciliation({ positionsAsOf: POS, stopsAsOf: 'Nov 13, 8:55 PM ET' })
assert.equal(malformed.state, 'unknown')
assert.match(malformed.reason, /stop read clock .*not a readable time/)

// --- unknown beats wrong ----------------------------------------------------------------------------------
const noStops = stopReconciliation({ positionsAsOf: POS, stopsAsOf: null })
assert.equal(noStops.state, 'unknown')
assert.match(noStops.reason, /no broker stop read is published/)

const noPositions = stopReconciliation({ positionsAsOf: undefined, stopsAsOf: STOP_OLD })
assert.equal(noPositions.state, 'unknown')
assert.match(noPositions.reason, /positions snapshot time is not published/)

const neither = stopReconciliation({})
assert.equal(neither.state, 'unknown')
assert.equal(neither.since, null)

// A numeric millisecond clock is accepted for the same reason the payload's ISO strings are.
const ms = stopReconciliation({ positionsAsOf: Date.parse(POS), stopsAsOf: Date.parse(STOP_OLD) })
assert.equal(ms.state, 'unreconciled')
assert.equal(ms.since, STOP_OLD)

// --- the reason sentences, pinned (the page prefixes "Reconciled" / "Unreconciled since <clock>") ---------
assert.equal(stopReconciliation({ positionsAsOf: POS, stopsAsOf: STOP_OLD }).reason,
  'the broker order read is 18.1 h older than the positions snapshot; a position opened, closed or resized ' +
  'after that read can carry a stop state read against a different book')
assert.equal(stopReconciliation({ positionsAsOf: POS, stopsAsOf: STOP_SAME }).reason,
  'the broker order read is at or after the positions snapshot')

console.log('stopReconciliation.test.ts: ok')

import { POSITION_WRITER_LANES, positionWriterNote } from './sourceClock.ts'

const assert = {
  ok(value: unknown, message: string) { if (!value) throw new Error(message) },
  equal(actual: unknown, expected: unknown, message?: string) {
    if (!Object.is(actual, expected)) throw new Error(message ?? `Expected ${String(expected)}, received ${String(actual)}`)
  },
  matches(text: string, rx: RegExp) { if (!rx.test(text)) throw new Error(`expected ${rx} in: ${text}`) },
}

// FQ-112: the source clock must name the writer and the time it wrote the source.
const note = positionWriterNote('2026-11-04T11:30:03-05:00')
assert.ok(note, 'a dated positions clock produces a note')
assert.matches(note!, /schwab-position-sync/)
assert.matches(note!, /snaptrade-sync/)
assert.matches(note!, /11:30/)
assert.matches(note!, /run receipt is not recorded/)
assert.matches(note!, /its last successful run cannot be confirmed/)
assert.equal(POSITION_WRITER_LANES.join(','), 'schwab-position-sync,snaptrade-sync')

// It must not assert an unrecorded success or invent a last-run time.
assert.ok(!/last successful run (was|at) /i.test(note!), 'never claims a last successful run')

// No clock → the writer is still identified; the note says exactly what is missing.
for (const missing of [null, undefined, 'not-a-date']) {
  const bare = positionWriterNote(missing)
  assert.matches(bare!, /schwab-position-sync \/ snaptrade-sync/)
  assert.matches(bare!, /no recorded write time/)
  assert.matches(bare!, /run receipt is not recorded/)
  assert.ok(!/last successful run (was|at) /i.test(bare!), 'never claims a last successful run')
}

console.log('source clock attribution: passed')

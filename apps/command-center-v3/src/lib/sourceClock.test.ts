// FQ-112, repaired for review of PR 2641 (cx-openai-3, P2 F1/F2).
//
// F1: `positions.as_of` is the positions snapshot's evidence clock (`positions_built_at`, else the oldest
// contributing data clock) — not a writer-event time, and it does not name a writer. The note must name the
// CONFIGURED lanes and describe the clock by its real basis; unknown provenance stays unknown.
// F2: the note must not make a receipt/last-run claim of its own — the DeskPage source row renders that from
// execution evidence, and a frozen contradiction here is exactly what the reviewer rendered.
import { POSITION_WRITER_LANES, positionWriterNote } from './sourceClock.ts'

const assert = {
  ok(value: unknown, message: string) { if (!value) throw new Error(message) },
  equal(actual: unknown, expected: unknown, message?: string) {
    if (!Object.is(actual, expected)) throw new Error(message ?? `Expected ${String(expected)}, received ${String(actual)}`)
  },
  matches(text: string, rx: RegExp) { if (!rx.test(text)) throw new Error(`expected ${rx} in: ${text}`) },
  doesNotMatch(text: string, rx: RegExp, message: string) { if (rx.test(text)) throw new Error(`${message}: ${text}`) },
}

const note = positionWriterNote('2026-11-04T11:30:03-05:00')
assert.ok(note, 'a dated positions clock produces a note')

// It names the configured lanes and the date the snapshot carries.
assert.matches(note!, /configured source lanes are schwab-position-sync \/ snaptrade-sync/)
assert.matches(note!, /11:30/)
assert.equal(POSITION_WRITER_LANES.join(','), 'schwab-position-sync,snaptrade-sync')

// F1: it must not claim a writer, or call the snapshot clock a write time.
assert.doesNotMatch(note!, /written by/i, 'the note claims a writer the evidence does not establish')
assert.doesNotMatch(note!, /time the positions were written/i, 'the note relabels the snapshot clock as a write event')
assert.matches(note!, /not a record of which lane wrote the file or when it last ran/)
assert.matches(note!, /evidence clock/)

// F2: no receipt or last-run claim of its own — the source row owns that evidence.
assert.doesNotMatch(note!, /run receipt/i, 'the note freezes a receipt claim the source row can contradict')
assert.doesNotMatch(note!, /last successful run/i, 'the note asserts a last-run state it cannot see')
assert.doesNotMatch(note!, /cannot be confirmed/i, 'the note asserts an unconfirmability it cannot see')

// No clock → still says what is missing, still names the configured lanes, still asserts no writer.
for (const missing of [null, undefined, 'not-a-date']) {
  const bare = positionWriterNote(missing)
  assert.ok(bare, 'an undated clock still produces a note')
  assert.matches(bare!, /no recorded clock/)
  assert.matches(bare!, /configured source lanes are schwab-position-sync \/ snaptrade-sync/)
  assert.matches(bare!, /not recorded here/)
  assert.doesNotMatch(bare!, /written by/i, 'the undated note claims a writer')
  assert.doesNotMatch(bare!, /run receipt|last successful run|cannot be confirmed/i, 'the undated note makes a receipt claim')
}

console.log('source clock attribution: passed')

// node --experimental-strip-types src/lib/askCioModel.test.ts
// Ask the CIO UI model on the fixture (src/fixtures/askCio.fixture.ts).
declare const process: { exit(code?: number): never }
import { ASK_RESPONSE, LIST, THREAD } from '../fixtures/askCio.fixture.ts'
import {
  ASK_PATHS, MAX_QUESTION_CHARS, buildAskBody, currentVersion, entityLabel, filterSummaries, isAskShortcut, isPending,
  latestAnswer, relativeAge, trackedChips, sizingLine, sortSummaries, statusLabel, statusTone, trackedEntities, unwrap,
  validateQuestion, type ThreadSummary,
} from './askCioModel.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}
function ok(name: string, cond: unknown) { if (!cond) { failed++; console.error(`FAIL ${name}`) } }

// validation: quantities optional, never prompted
eq('empty refused', validateQuestion('   '), { ok: false, reason: 'Type a question.' })
eq('whitespace collapsed', validateQuestion('  Is  TSLA a buy? '), { ok: true, question: 'Is TSLA a buy?' })
ok('no quantity needed', validateQuestion('Invest in Skydance after Musk’s $1B?').ok)
ok('too long refused', !validateQuestion('x'.repeat(MAX_QUESTION_CHARS + 1)).ok)

// body
eq('quick body', buildAskBody('q', { requestId: 'r1' }), { question: 'q', depth: 'quick', client_request_id: 'r1' })
eq('deep follow-up body', buildAskBody('q', { deep: true, threadId: 'thr_1', requestId: 'r2' }),
  { question: 'q', depth: 'deep', client_request_id: 'r2', thread_id: 'thr_1' })
eq('paths', [ASK_PATHS.ask, ASK_PATHS.thread('thr_a'), ASK_PATHS.untrack('thr_a')],
  ['/api/v2/cio/ask', '/api/v2/cio/asks/thr_a', '/api/v2/cio/asks/thr_a/untrack'])

// shortcut
ok('cmd-k', isAskShortcut({ key: 'k', metaKey: true }))
ok('ctrl-k', isAskShortcut({ key: 'K', ctrlKey: true }))
ok('plain k is typing', !isAskShortcut({ key: 'k' }))
ok('ctrl-shift-k not ours', !isAskShortcut({ key: 'k', ctrlKey: true, shiftKey: true }))

// thread
eq('latest answer is the re-answer', latestAnswer(THREAD)?.status, 'reanswer')
eq('current version of turn 1 is v2', currentVersion(THREAD.turns[0])?.version, 2)
eq('turn kinds in order', THREAD.turns.map(t => t.turn_kind), ['ask', 'follow_up', 'reanswer'])
eq('tracked entities', trackedEntities(THREAD).map(e => entityLabel(e)), ['TSLA', 'SpaceX (private)'])
ok('private entity has no ticker', THREAD.entities[1].symbol === null)
eq('status labels', [statusLabel('quick'), statusLabel('reanswer'), statusLabel(null)],
  ['Quick answer', 'Updated on new information', 'Asked'])
eq('status tones', [statusTone('deep'), statusTone('capped'), statusTone('failed')], ['ai', 'warning', 'danger'])
ok('deep_pending is pending', isPending('deep_pending') && !isPending('deep'))

// sizing: operator-named quantities only, never a recommendation
const rows = THREAD.turns[0].answers[0].sizing_context!
eq('sizing lines', rows.map(sizingLine), [
  '100 TSLA: ≈ $25,000 · 2.5% of portfolio · loss at reference stop ≈ $2,000',
  '1,000 TSLA: ≈ $250,000 · 25.0% of portfolio · over the 12% limit · loss at reference stop ≈ $20,000',
])
ok('no recommended size anywhere', !/recommend(ed)? (size|quantity)|you should buy/i.test(JSON.stringify(THREAD)))

// list
const L = unwrap<{ threads: ThreadSummary[] }>(LIST)!
eq('sorted newest first', sortSummaries(L.threads).map(t => t.thread_id), [THREAD.thread_id, 'thr_1111111111111111'])
eq('filter by ticker', filterSummaries(L.threads, 'tsla').map(t => t.thread_id), [THREAD.thread_id])
eq('filter by name', filterSummaries(L.threads, 'skyd').length, 1)
eq('ask response unwraps', unwrap<{ thread_id: string }>(ASK_RESPONSE)?.thread_id, THREAD.thread_id)
eq('error envelope unwraps to null', unwrap({ ok: false, error: 'CSRF_REFUSED' }), null)

// header flags for tracked names
eq('tracked chips dedupe and label', trackedChips([
  { thread_id: 'thr_a', key: 'g1', symbol: 'TSLA', name: 'Tesla', kind: 'security' },
  { thread_id: 'thr_b', key: 'g1', symbol: 'TSLA', name: 'Tesla', kind: 'security' },
  { thread_id: 'thr_c', key: 'ent_1', symbol: null, name: 'Skydance', kind: 'private_entity' },
]), [{ key: 'g1', label: 'TSLA', thread_id: 'thr_a' }, { key: 'ent_1', label: 'Skydance (private)', thread_id: 'thr_c' }])
eq('tracked chips tolerate a missing payload', trackedChips(undefined), [])

// age
const now = new Date('2026-10-23T15:20:00Z')
eq('ages', [relativeAge('2026-10-23T15:10:00Z', now), relativeAge('2026-10-21T15:20:00Z', now), relativeAge(null, now)],
  ['10m ago', '2d ago', ''])

if (failed) { console.error(`askCioModel: ${failed} failure(s)`); process.exit(1) }
console.log('askCioModel: all checks passed')

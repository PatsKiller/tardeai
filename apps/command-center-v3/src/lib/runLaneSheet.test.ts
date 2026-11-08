// LQ-20261107-611 · Run-a-lane sheet model. Runs in the CC-v3 build:
//   node --experimental-strip-types src/lib/runLaneSheet.test.ts
import { batchPath, canCancelQueued, filterLanes, progressSummary, receiptLine, type BatchProgress, type LaneRow } from './runLaneSheet.ts'
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => { const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`) }
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }
const row = (id: string): LaneRow => ({ lane_id: id, family: id.split('-')[0], dry: { available: true, reason: null }, live: { available: false, reason: 'x' }, run_all_live: { included: false, excluded_because: [] }, run_all_dry: { included: true } })

t('search matches lane id or family, case-insensitively, and an empty query keeps all', () => {
  const rows = [row('sec-fundamentals-ingest'), row('news-rss'), row('sec-13f')]
  eq(filterLanes(rows, 'SEC').map(r => r.lane_id), ['sec-fundamentals-ingest', 'sec-13f'])
  eq(filterLanes(rows, 'rss').length, 1)
  eq(filterLanes(rows, '  ').length, 3)
  eq(filterLanes(null, 'x'), [])
})
t('receipt lines name flock_held, cancelled, and the output signal', () => {
  eq(receiptLine(null), 'never run through the executor')
  eq(receiptLine({ state: 'RUN_SKIPPED_LOCK', flock_held: true }).startsWith('skipped: lane lock held (flock_held)'), true)
  eq(receiptLine({ state: 'RUN_REFUSED', reason: 'cancelled_by_operator' }), 'cancelled before it started')
  eq(receiptLine({ state: 'RUN_DONE', exit_code: 0, duration_s: 1.25, output_signal_advanced: false }), 'exit 0 · 1.3 s · output signal advanced: no')
  eq(receiptLine({ state: 'RUN_DONE', exit_code: 0, output_signal_advanced: null }).endsWith('not measured'), true)
})
t('progress summary and cancel availability follow the counts', () => {
  const p: BatchProgress = { batch_id: 'b', total: 4, finished: false, counts: { queued: 2, running: 1, done: 1, failed: 0, cancelled: 0 }, runs: [] }
  eq(progressSummary(p), '2 queued · 1 running · 1 done of 4')
  eq(canCancelQueued(p), true)
  eq(canCancelQueued({ ...p, counts: { ...p.counts, queued: 0 } }), false)
  eq(progressSummary(null), 'waiting for the first row')
  eq(batchPath('a/b'), '/api/v2/ops/controls/lanes/batch/a%2Fb')
})
import { unwrapEnvelope } from './runLaneSheet.ts'
t('envelope: wrapped, bare, and wrong-shaped bodies', () => {
  eq(unwrapEnvelope({ ok: true, data: { lanes: [] } }, 'lanes'), { lanes: [] })
  eq(unwrapEnvelope({ lanes: [1] }, 'lanes'), { lanes: [1] })
  eq(unwrapEnvelope({ ok: true, data: { x: 1 } }, 'lanes'), null)
  eq(unwrapEnvelope(null, 'lanes'), null)
})
console.log(`${n} passed`)

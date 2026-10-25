// A gap is a gap, never 0: jobs tiles and data-approval tiles. Synthetic inputs only.
// Runs in the CC-v3 build:  node --experimental-strip-types src/lib/measuredCount.test.ts
import { countText, dataApprovalTiles, jobsCount, jobsMissed, jobsNotMeasured, measured } from './measuredCount.ts'

declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`)
}
const ok = (c: unknown, m: string) => { if (!c) fail(m) }
function t(name: string, fn: () => void) { fn(); console.log(`  [PASS] ${name}`) }

t('measured: numbers stay, anything else is a gap with a reason', () => {
  eq(measured(0), { value: 0, reason: null })
  eq(measured(null, 'scan running').value, null)
  eq(countText(measured(undefined)), '—')
  eq(countText(measured('3')), '—', 'a string is not a count')
  eq(countText({ value: 2, reason: 'x', atLeast: true }), '2+')
})

t('jobs: Missed 0 with unmeasured jobs is a gap, not 0', () => {
  const s = { due_today: 20, succeeded: 5, failed: 1, missed: 0, unknown: 14 }
  const m = jobsMissed(s)
  eq(m.value, null)
  ok(m.reason?.includes('14 jobs not measured'), `reason names the unmeasured count: ${m.reason}`)
  eq(jobsNotMeasured(s).value, 14)
})

t('jobs: a positive missed count with unmeasured jobs is a floor', () => {
  const m = jobsMissed({ missed: 2, unknown: 3 })
  eq([m.value, m.atLeast, countText(m)], [2, true, '2+'])
})

t('jobs: fully measured → a real 0', () => {
  eq(jobsMissed({ missed: 0, unknown: 0 }), { value: 0, reason: null })
  eq(jobsMissed({ missed: 0, not_measured: 0, missed_measured: true }).value, 0)
})

t('jobs: server says missed detection unavailable → gap with the server reason', () => {
  const m = jobsMissed({ missed: 0, not_measured: 0, missed_measured: false, gap_reasons: { missed: 'Fixture monitor missing' } })
  eq([m.value, m.reason], [null, 'Fixture monitor missing'])
})

t('jobs: no observation → every tile is a gap', () => {
  eq(jobsMissed(null).value, null)
  eq(jobsCount(undefined, 'failed').value, null)
  eq(jobsCount({ failed: 1 }, 'failed').value, 1)
  eq(jobsCount({}, 'due_today').value, null)
  eq(jobsNotMeasured({}).value, null)
})

const counts = { approved: 0, ready: 0, notReady: 0, findings: 0 }
t('data approvals: scan running with unchecked rows → "—" with N of M checked', () => {
  const rows = [{ verdict: null }, { verdict: 'APPROVED' }, {}]
  const tiles = dataApprovalTiles(rows, { ...counts, approved: 1 }, { state: 'RUNNING' })
  eq(tiles.approved.value, null)
  eq(tiles.findings.reason, 'Scan running · 1 of 3 checked')
  eq(countText(tiles.notReady), '—')
})

t('data approvals: no rows → gap, never 0', () => {
  eq(dataApprovalTiles([], counts, { state: 'RUNNING' }).ready.reason, 'Scan running · no domain checked yet')
  eq(dataApprovalTiles(null, counts, null).approved.value, null)
})

t('data approvals: every row checked → real counts including real zeros', () => {
  const tiles = dataApprovalTiles([{ verdict: 'APPROVED' }, { verdict: 'NOT_READY' }], { approved: 1, ready: 0, notReady: 1, findings: 0 }, { state: 'DONE' })
  eq([tiles.approved.value, tiles.ready.value, tiles.notReady.value, tiles.findings.value], [1, 0, 1, 0])
})

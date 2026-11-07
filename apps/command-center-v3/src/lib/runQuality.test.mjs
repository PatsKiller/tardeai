// Run-quality helpers (design pages/jobs v003). Synthetic lane data only.
//   node --experimental-strip-types src/lib/runQuality.test.mjs
import { QUALITY_GRADES, checkRows, gradeChip, isQualityKey, notAsDesigned, notAsDesignedCount, qualityHistoryQuery, qualityTiles } from './runQuality.ts'
let n = 0
const eq = (a, b, m) => { const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) { console.log(`  [FAIL] ${m}: expected ${y} got ${x}`); process.exit(1) } }
const t = (name, fn) => { fn(); n++; console.log(`  [PASS] ${name}`) }

t('six grades in the mockup order', () => eq(QUALITY_GRADES.map(g => g.key), ['good', 'degraded', 'empty', 'failed', 'not_live', 'unproven'], 'order'))
t('tiles read summary.quality_counts; a missing count is null, never 0', () => {
  const tiles = qualityTiles({ quality_counts: { GOOD: 3, DEGRADED: 0, FAILED: 2 } })
  eq(tiles.map(x => x.value), [3, 0, null, 2, null, null], 'values')
  eq(qualityTiles(null).every(x => x.value === null), true, 'no summary')
  eq(notAsDesignedCount({ quality_not_as_designed: 4 }), 4, 'nad'); eq(notAsDesignedCount({}), null, 'nad missing')
})
t('NOT_LIVE chip names the reason; unknown/absent grade shows nothing', () => {
  eq(gradeChip({ grade: 'NOT_LIVE', sub: 'skipped' }), { label: 'Not live · skipped', tone: 'neutral' }, 'skipped')
  eq(gradeChip({ grade: 'NOT_LIVE', sub: 'dry_run' })?.label, 'Not live · dry run', 'dry')
  eq(gradeChip({ grade: 'DEGRADED' }), { label: 'Degraded', tone: 'warning' }, 'degraded')
  // RUNQFIX 2026-11-07: a run that stated a reviewed idle reason is GOOD · idle → "Good · nothing due"
  eq(gradeChip({ grade: 'GOOD', sub: 'idle' }), { label: 'Good · nothing due', tone: 'success' }, 'idle')
  eq(gradeChip({ grade: 'GOOD', sub: 'something_else' })?.label, 'Good', 'other GOOD subs stay plain')
  eq(gradeChip({ grade: 'EMPTY', sub: 'unexpected' })?.label, 'Empty', 'EMPTY sub not shown')
  eq(/nothing due/.test(QUALITY_GRADES.find(g => g.grade === 'GOOD').means), true, 'GOOD definition names nothing due')
  eq(gradeChip(null), null, 'null'); eq(gradeChip({ grade: 'OK' }), null, 'unknown grade')
})
t('not-as-designed only on an explicit false', () => {
  eq(notAsDesigned({ grade: 'GOOD', as_designed: false }), true, 'false'); eq(notAsDesigned({ grade: 'GOOD', as_designed: null }), false, 'null')
})
t('quality query reads every job and only a known grade', () => {
  eq(qualityHistoryQuery({ quality: 'degraded' }), '/api/v2/jobs-history?filter=all&offset=0&limit=50&quality=degraded', 'degraded')
  eq(qualityHistoryQuery({ quality: 'bogus', q: ' disk ' }), '/api/v2/jobs-history?filter=all&offset=0&limit=50&q=disk', 'bogus')
  eq(qualityHistoryQuery({ quality: 'degraded,empty,bogus,degraded' }), '/api/v2/jobs-history?filter=all&offset=0&limit=50&quality=degraded%2Cempty', 'multi')
  eq(isQualityKey('not_live'), true, 'key'); eq(isQualityKey('NOT_LIVE'), false, 'upper')
})
t('checks are ordered, marked and worded', () => {
  const rows = checkRows({ grade: 'EMPTY', checks: { as_designed: { result: 'pass', value: 0 }, item_count: { result: 'fail', value: 0, detail: 'rows_written = 0' }, ran_live: { result: 'pass', value: 'n8n ledger' }, zz_new: { result: 'unknown', value: null } } })
  eq(rows.map(r => [r.key, r.mark, r.value]), [['ran_live', '✓', 'n8n ledger'], ['item_count', '✕', '0'], ['as_designed', '✓', 'no issues'], ['zz_new', '–', '—']], 'rows')
  eq(rows[1].detail, 'rows_written = 0', 'detail')
})
console.log(`runQuality: ${n} passed`)

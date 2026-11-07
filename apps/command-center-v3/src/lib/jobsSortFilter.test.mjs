// Jobs & n8n sort / filter helpers (operator 2026-11-06). Synthetic rows only.
//   node --experimental-strip-types src/lib/jobsSortFilter.test.mjs
import { CLIENT_SORTS, HISTORY_SORTS, RAN_OPTIONS, isRan, isSortIn, joinMulti, parseMulti, pickedLabel, ranMatches, sortRows, toggleMulti, withSortFilter } from './jobsSortFilter.ts'
let n = 0
const eq = (a, b, m) => { const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) { console.log(`  [FAIL] ${m}: expected ${y} got ${x}`); process.exit(1) } }
const t = (name, fn) => { fn(); n++; console.log(`  [PASS] ${name}`) }
const NOW = Date.parse('2026-11-07T12:00:00Z')

t('ran keys match the server', () => {
  eq(RAN_OPTIONS.map(([k]) => k), ['', '1h', '24h', '7d', 'older', 'never'], 'keys')
  eq([isRan('7d'), isRan('2d'), isRan(''), isRan(null)], [true, false, false, false], 'isRan')
})
t('sort lists: history has every server sort, client the four rows can answer', () => {
  eq(HISTORY_SORTS.map(([k]) => k), ['attention', 'last_run_desc', 'last_run_asc', 'quality', 'missed', 'name'], 'history')
  eq(CLIENT_SORTS.map(([k]) => k), ['attention', 'last_run_desc', 'last_run_asc', 'name'], 'client')
  eq([isSortIn(CLIENT_SORTS, 'quality'), isSortIn(HISTORY_SORTS, 'quality')], [false, true], 'isSortIn')
})
t('parseMulti trims, dedupes, drops unknown keys', () => {
  eq(parseMulti(' degraded,,empty,bogus,degraded ', k => ['degraded', 'empty'].includes(k)), ['degraded', 'empty'], 'parse')
  eq(parseMulti(null, () => true), [], 'null')
})
t('toggleMulti adds and removes; joinMulti empties to null', () => {
  eq(toggleMulti(['a'], 'b'), ['a', 'b'], 'add'); eq(toggleMulti(['a', 'b'], 'a'), ['b'], 'remove')
  eq(joinMulti(['a', 'b']), 'a,b', 'join'); eq(joinMulti([]), null, 'empty')
})
t('ranMatches windows; missing time = never ran', () => {
  const ago = h => new Date(NOW - h * 3_600_000).toISOString()
  eq(['1h', '24h', '7d', 'older', 'never'].map(w => ranMatches(ago(0.5), w, NOW)), [true, true, true, false, false], '30 min')
  eq(['1h', '24h', '7d', 'older', 'never'].map(w => ranMatches(ago(30), w, NOW)), [false, false, true, false, false], '30 h')
  eq(['1h', '24h', '7d', 'older', 'never'].map(w => ranMatches(ago(24 * 18), w, NOW)), [false, false, false, true, false], '18 d')
  eq(['1h', 'older', 'never'].map(w => ranMatches(null, w, NOW)), [false, false, true], 'null')
  eq(ranMatches('garbage', 'never', NOW), true, 'unparseable'); eq(ranMatches(null, null, NOW), true, 'no window')
})
t('sortRows: attention keeps order, time sorts put never-ran last, name is case-blind', () => {
  const rows = [{ n: 'charlie', at: '2026-11-03T00:00:00Z' }, { n: 'Alpha', at: null }, { n: 'bravo', at: '2026-11-07T00:00:00Z' }, { n: 'delta', at: '2026-10-01T00:00:00Z' }]
  const ids = (s) => sortRows(rows, s, r => r.at, r => r.n).map(r => r.n)
  eq(ids('attention'), ['charlie', 'Alpha', 'bravo', 'delta'], 'attention'); eq(ids(null), ids('attention'), 'default')
  eq(ids('last_run_desc'), ['bravo', 'charlie', 'delta', 'Alpha'], 'desc'); eq(ids('last_run_asc'), ['delta', 'charlie', 'bravo', 'Alpha'], 'asc')
  eq(ids('name'), ['Alpha', 'bravo', 'charlie', 'delta'], 'name'); eq(rows[0].n, 'charlie', 'input untouched')
})
t('withSortFilter adds ran/sort; default sort and unknowns stay off the URL', () => {
  eq(withSortFilter('/api/v2/jobs-history?filter=all', { ran: '24h', sort: 'missed' }), '/api/v2/jobs-history?filter=all&ran=24h&sort=missed', 'set')
  eq(withSortFilter('/api/v2/jobs-history?filter=all', { ran: 'x', sort: 'attention' }), '/api/v2/jobs-history?filter=all', 'default')
})
t('pickedLabel reads as a sentence', () => {
  eq(pickedLabel(['Degraded']), 'Degraded', 'one'); eq(pickedLabel(['Degraded', 'Empty']), 'Degraded or Empty', 'two')
  eq(pickedLabel(['A', 'B', 'C']), 'A, B or C', 'three'); eq(pickedLabel([]), '', 'none')
})
console.log(`jobsSortFilter: ${n} passed`)

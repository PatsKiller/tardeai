import { needsActionFrom, routerPath, severityTone } from './needsAction.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}
const now = Date.parse('2026-10-21T13:00:00Z')
const ok = { as_of: '2026-10-21T12:59:30Z', all_sources_answered: true, sources: { health: { status: 'OK' }, queue: { status: 'OK' } },
  items: [
    { severity: 'P2', title: 'queue', why: 'w', where: '/v3/system?tab=Jobs', source: 'queue', since: null },
    { severity: 'P0', title: 'stops', why: 'w', where: '/v3/risk', source: 'health', since: '2026-10-21T12:00:00Z' },
    { severity: 'P9', title: 'junk' }] }
const m = needsActionFrom(ok, { nowMs: now })
check('counts by severity; unknown severities dropped', m.state === 'ITEMS' && m.counts.P0 === 1 && m.counts.P2 === 1 && m.items.length === 2)
check('sorted P0 first; where made router-relative', m.items[0].title === 'stops' && m.items[0].where === '/risk' && m.items[1].where === '/system?tab=Jobs')
const clear = needsActionFrom({ ...ok, items: [] }, { nowMs: now })
check('empty + every source answered = CLEAR', clear.state === 'CLEAR')
const partial = needsActionFrom({ ...ok, items: [], all_sources_answered: false, sources: { health: { status: 'OK' }, queue: { status: 'UNAVAILABLE' } } }, { nowMs: now })
check('empty but a source missing is never CLEAR', partial.state === 'UNAVAILABLE' && partial.unavailableSources[0] === 'queue')
check('fetch error with no payload is UNAVAILABLE', needsActionFrom(null, { error: 'HTTP 502' }).state === 'UNAVAILABLE')
check('loading', needsActionFrom(null, { loading: true }).state === 'LOADING')
check('a failed refresh keeps items as STALE', needsActionFrom(ok, { error: 'timeout', nowMs: now }).state === 'STALE')
check('old answer is STALE', needsActionFrom({ ...ok, as_of: '2026-10-21T11:00:00Z' }, { nowMs: now }).state === 'STALE')
check('malformed is UNAVAILABLE', needsActionFrom({ all_sources_answered: true }).state === 'UNAVAILABLE')
check('routerPath', routerPath('/v3/communications') === '/communications' && routerPath('/v3') === '/' && routerPath('https://x') === '/' && routerPath(null) === '/')
check('tones', severityTone('P0') === 'danger' && severityTone('P2') === 'warning' && severityTone('P3') === 'info')
console.log(`needsAction: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)

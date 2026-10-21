import { countsLabel, platformHealthFrom, toneFor, worstOf } from './platformHealth.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

const now = Date.parse('2026-10-21T13:00:00Z')
const fresh = '2026-10-21T12:59:30Z'
const item = (id: string, group: string, status: any, value: any, extra: any = {}) =>
  ({ id, group, label: id, status, value, as_of: fresh, source: 'test', reason: null, ...extra })
const ok = {
  schema: 'PlatformHealth@v1', status: 'OK', as_of: fresh,
  items: [
    item('n8n.healthz', 'n8n', 'OK', 'ok'),
    item('unit.portfolio-server', 'services', 'OK', 'up 25m'),
    item('unit.failed_tradeai', 'services', 'WARN', 1, { reason: 'failed: tradeai-portfolio-backup-cadence.service' }),
    item('postgres.main', 'postgres', 'UNKNOWN', null, { reason: 'DB unreachable' }),
    item('host.disk.root', 'host', 'OK', '76.7% used'),
  ],
}

check('no payload is UNAVAILABLE, no rows, never OK', platformHealthFrom(null, { nowMs: now }).state === 'UNAVAILABLE')
check('first load is LOADING', platformHealthFrom(null, { nowMs: now, loading: true }).state === 'LOADING')
check('failed first fetch keeps the error', platformHealthFrom(null, { nowMs: now, error: 'HTTP 502' }).reason === 'HTTP 502')
check('server UNAVAILABLE is UNAVAILABLE', platformHealthFrom({ status: 'UNAVAILABLE', items: [], error: 'boom' }, { nowMs: now }).state === 'UNAVAILABLE')
check('empty items is UNAVAILABLE, not OK', platformHealthFrom({ status: 'OK', items: [] }, { nowMs: now }).state === 'UNAVAILABLE')

const h = platformHealthFrom(ok, { nowMs: now })
const pg = h.rows.find(r => r.id === 'postgres.main')!
check('UNKNOWN row shows UNKNOWN, not a value or zero', pg.status === 'UNKNOWN' && pg.value === 'UNKNOWN' && pg.reason === 'DB unreachable')
check('UNKNOWN is never toned success', toneFor(pg.status) === 'neutral')
check('WARN row keeps its count and reason', h.rows.find(r => r.id === 'unit.failed_tradeai')!.value === '1')
check('overall is the worst row (WARN beats UNKNOWN and OK)', h.state === 'WARN')
check('groups follow the platform order', h.groups.map(g => g.group).join(',') === 'n8n,services,host,postgres')
check('counts label', countsLabel(h.counts) === '1 WARN · 1 UNKNOWN · 3 OK')

const weird = platformHealthFrom({ ...ok, items: [item('x', 'host', 'GREEN', 5), item('y', 'host', undefined, 0)] }, { nowMs: now })
check('an unrecognised status is UNKNOWN, never OK', weird.rows.every(r => r.status === 'UNKNOWN' && r.value === 'UNKNOWN'))

const old = platformHealthFrom({ ...ok, items: [item('n8n.healthz', 'n8n', 'OK', 'ok', { as_of: '2026-10-21T12:57:00Z' })] }, { nowMs: now })
check('as_of older than 2 min is STALE', old.rows[0].status === 'STALE' && old.state === 'STALE')
const noAsOf = platformHealthFrom({ ...ok, items: [item('n8n.healthz', 'n8n', 'OK', 'ok', { as_of: null })] }, { nowMs: now })
check('missing as_of is STALE, not OK', noAsOf.rows[0].status === 'STALE')
const refresh = platformHealthFrom(ok, { nowMs: now, error: 'timeout' })
check('a failed refresh over a kept payload is STALE', refresh.rows.find(r => r.id === 'n8n.healthz')!.status === 'STALE' && refresh.reason === 'refresh failed: timeout')
check('a kept UNKNOWN stays UNKNOWN on refresh failure', refresh.rows.find(r => r.id === 'postgres.main')!.status === 'UNKNOWN')

const crit = platformHealthFrom({ ...ok, items: [...ok.items, item('n8n.container.m8m-n8n', 'n8n', 'CRIT', 'exited')] }, { nowMs: now })
check('CRIT dominates and tones danger', crit.state === 'CRIT' && toneFor(crit.state) === 'danger')
check('worstOf empty is UNKNOWN', worstOf([]) === 'UNKNOWN')
check('value 0 from a real measurement is shown as 0', platformHealthFrom({ ...ok, items: [item('unit.failed_tradeai', 'services', 'OK', 0)] }, { nowMs: now }).rows[0].value === '0')

console.log(`platformHealth: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)

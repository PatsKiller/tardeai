const assert = {
  equal(actual: unknown, expected: unknown, message = 'expected equality') { if (actual !== expected) throw new Error(`${message}: ${String(actual)} !== ${String(expected)}`) },
}
import { ageText, canAct, matchesFilter, refLink, sortIncidents, sourceText, statusLabel, type Incident } from './incidents.ts'

const base: Incident = {
  schema: 'IncidentRecord@v1', id: 'INC-261027-kmpqrs', opened_at: '2026-10-27T10:00:00Z', updated_at: '2026-10-27T10:00:00Z',
  status: 'open', source: { kind: 'watcher', watcher: 'deploy_failures' }, title: 't', evidence: [], attempts: [], fix_refs: [],
}
assert.equal(statusLabel('blocked').tone, 'danger')
assert.equal(statusLabel('fixed').tone, 'success')
assert.equal(statusLabel('weird').label, 'Unknown (weird)')
assert.equal(ageText('2026-10-27T10:00:00Z', null, Date.parse('2026-10-27T10:12:00Z')), '12 min')
assert.equal(ageText('2026-10-27T10:00:00Z', null, Date.parse('2026-10-27T13:05:00Z')), '3 h 05 min')
assert.equal(ageText('2026-10-25T10:00:00Z', '2026-10-27T14:00:00Z'), '2 d 4 h')
assert.equal(ageText(null), '—')
assert.equal(sourceText(base), 'watcher · deploy_failures')
assert.equal(refLink({ kind: 'pr', ref: '2232' }).href, 'https://github.com/PatsKiller/tardeai/pull/2232')
assert.equal(refLink({ kind: 'pr', ref: 'https://github.com/PatsKiller/tardeai/pull/9' }).label, 'PR #9')
assert.equal(refLink({ kind: 'receipt', ref: 'data/x.json' }).href, undefined)
assert.equal(matchesFilter({ ...base, status: 'blocked' }, 'active'), true)
assert.equal(matchesFilter({ ...base, status: 'fixed' }, 'active'), false)
assert.equal(canAct({ ...base, status: 'fixed' }).close, false)
assert.equal(canAct({ ...base, acknowledged: { at: 'x', actor: 'op' } }).ack, false)
const sorted = sortIncidents([{ ...base, id: 'b', status: 'fixed' }, { ...base, id: 'a', status: 'blocked' }, { ...base, id: 'c' }])
assert.equal(sorted.map(r => r.id).join(','), 'c,a,b')
console.log('incidents.test.ts ok')

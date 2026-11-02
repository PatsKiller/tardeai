const assert = {
  equal(actual: unknown, expected: unknown, message = 'expected equality') { if (actual !== expected) throw new Error(`${message}: ${String(actual)} !== ${String(expected)}`) },
}
import { ageText, canAct, escalationStatus, matchesFilter, refLink, severityLabel, sortIncidents, sourceText, statusLabel, type Incident } from './incidents.ts'

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
assert.equal(escalationStatus(base), null)
assert.equal(escalationStatus({ escalations: [] }), null)
assert.equal(escalationStatus({ escalations: [{ at: 'x', delivered: false }] })?.label, 'Escalation delivery unconfirmed (1 attempt)')
assert.equal(escalationStatus({ escalations: [{ at: 'x' }] })?.tone, 'warning')
assert.equal(escalationStatus({ escalations: [{ at: 'x', delivered: 'true' as unknown as boolean }] })?.tone, 'warning')
assert.equal(escalationStatus({ escalations: [{ at: 'x', delivered: true }] })?.label, '1 of 1 escalation deliveries confirmed')
assert.equal(escalationStatus({ escalations: [{ at: 'x', delivered: true }, { at: 'y', delivered: false }] })?.label, '1 of 2 escalation deliveries confirmed')
assert.equal(escalationStatus({ escalations: [{ at: 'x', delivered: true }, { at: 'y', delivered: false }] })?.tone, 'warning')
assert.equal(severityLabel(' p0 ').label, 'P0')
assert.equal(severityLabel(undefined).label, 'Severity unknown')
assert.equal(severityLabel('critical').label, 'Severity unknown (CRITICAL)')
assert.equal(severityLabel('P4').label, 'Severity unknown (P4)')
const triaged = sortIncidents([
  { ...base, id: 'old-p3', severity: 'P3' },
  { ...base, id: 'closed-p0', status: 'closed', severity: 'P0' },
  { ...base, id: 'blocked-p0', status: 'blocked', severity: 'P0' },
  { ...base, id: 'open-p1', severity: 'P1' },
  { ...base, id: 'unknown' },
])
assert.equal(triaged.map(r => r.id).join(','), 'blocked-p0,open-p1,old-p3,unknown,closed-p0')
const samePriority = sortIncidents([
  { ...base, id: 'new', severity: 'P1', opened_at: '2026-10-27T12:00:00Z' },
  { ...base, id: 'old', severity: 'P1' },
])
assert.equal(samePriority.map(r => r.id).join(','), 'old,new')
console.log('incidents.test.ts ok')

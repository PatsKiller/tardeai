// Home v010 clocks (campaign item 1, controlling decision 2026-11-13 §2): every slice ages from its OWN absolute
// source clock at render time. A payload's `age_s` is a snapshot; it may only stand in when the slice has no as_of.
// The check time is absolute and carries its own render-time age. Synthetic fixtures only.
import assert from 'node:assert/strict'
import { API, ageSecondsFrom, ageText, buildModel, statusFrom, type HomeStatusWire, type HomeV010Inputs, type Read } from './homeV010.ts'

const NOW = Date.parse('2026-11-13T15:00:00Z')
const AT = '2026-11-13T14:59:00Z'
const read = <T,>(source: string, data: T): Read<T> => ({ state: 'OK', data, error: null, at: AT, source })
const gate = (id: string, extra: Record<string, unknown> = {}) => ({
  id, label: id, required: true, state: 'OK', source_id: `src_${id}`,
  as_of: '2026-11-13T13:00:00Z', age_s: 60, threshold_s: 900, reason: null, needs_backend: false, ...extra,
})
const statusWire = (gates: unknown[]): Read<HomeStatusWire> => read(API.status, {
  schema: 'HomeStatus@v1', verdict: 'YES',
  trade_ready: { verdict: 'YES', cause: 'every required input read OK', computed_at: AT },
  gates, blockers: [], unknown_inputs: [],
} as never)
const CLEAR = (gates: unknown[]): HomeV010Inputs => ({
  sinceClose: read(API.sinceClose, { status: 'ok', cio_brief: { status: 'available', stop_advice: [] } } as never),
  approvals: read(API.approvals, { ok: true, data: { count: 0, urgent_count: 0, as_of: AT } } as never),
  incidents: read(API.incidents, { state: 'OK', items: [], counts: { P0: 0, P1: 0 }, data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 } } as never),
  lastSeen: read(API.lastSeen, { ok: true, read: { status: 'NOT_RECORDED', seen_at: null } } as never),
  status: statusWire(gates),
})

// 1. A gate ages from as_of at the render clock, not from the served age_s (which said 60 s for a 2 h old clock).
{
  const st = statusFrom(CLEAR([gate('portfolio')]).status, NOW)
  assert.equal(st.gates?.[0].age, '2 h 0 m')
}

// 2. The same wire rebuilt one client-minute later ages one minute: nothing is stored.
{
  const g = [gate('portfolio')]
  const a = statusFrom(CLEAR(g).status, NOW).gates![0].age
  const b = statusFrom(CLEAR(g).status, NOW + 600_000).gates![0].age
  assert.equal(a, '2 h 0 m')
  assert.equal(b, '2 h 10 m')
}

// 3. age_s remains the honest fallback ONLY when the slice carries no readable as_of.
{
  assert.equal(statusFrom(CLEAR([gate('no-clock', { as_of: null, age_s: 90 })]).status, NOW).gates![0].age, '1 m')
  assert.equal(statusFrom(CLEAR([gate('bad-clock', { as_of: 'not a time', age_s: 90 })]).status, NOW).gates![0].age, '1 m')
}

// 4. No stored relative wording is echoed, even if a payload carries one: the age is re-derived from as_of.
{
  const st = statusFrom(CLEAR([gate('portfolio', { age_text: 'just now', age_label: 'just now' })]).status, NOW)
  assert.equal(st.gates?.[0].age, '2 h 0 m')
  assert.doesNotMatch(st.gates?.[0].age, /just now/i)
}

// 5. Slice freshness is independent of the parent status document: two gates at different source clocks age
//    differently, and the envelope's own computed_at does not touch either.
{
  const st = statusFrom(CLEAR([gate('old'), gate('fresh', { as_of: '2026-11-13T14:59:00Z' })]).status, NOW)
  assert.equal(st.gates?.[0].age, '2 h 0 m')
  assert.equal(st.gates?.[1].age, '1 m')
}

// 6. The check time is absolute and its age is computed at render (the view prints both).
{
  const m = buildModel(CLEAR([gate('portfolio')]), NOW)
  assert.equal(m.checkedAt, AT, 'the check time is the latest read receipt, kept absolute')
  assert.equal(ageText(ageSecondsFrom(m.checkedAt, NOW)), '1 m')
  assert.equal(ageText(ageSecondsFrom(m.checkedAt, NOW + 3_600_000)), '1 h 1 m', 'the same check time ages with the client clock')
}

console.log('homeV010.clock: ok')

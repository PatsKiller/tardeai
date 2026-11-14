import { readinessFromPlan, nextReadinessAction, readinessEvidenceLine, READINESS_UNAVAILABLE } from './redeployReadiness.ts'

const assert = {
  equal(actual: unknown, expected: unknown, what = '') {
    if (!Object.is(actual, expected)) throw new Error(`${what}Expected ${String(expected)}, received ${String(actual)}`)
  },
  ok(value: unknown, what = '') {
    if (!value) throw new Error(`${what}expected a truthy value, received ${String(value)}`)
  },
}

// ── The regression (RR-014): a plan with NO readiness key must never be operator-ready. ──
// The old client fallback returned {state:'OPERATOR_READY', operator_ready:true} as soon as its
// own missing-list was empty. This is the exact input that used to do it.
const noReadiness = { legs: [{ symbol: 'AAA', price_stale: false }], hermes_narrative: 'memo', oversight_status: 'pass' }
const unavailable = readinessFromPlan(noReadiness, [])
assert.equal(unavailable.state, READINESS_UNAVAILABLE, 'no readiness must fail closed: ')
assert.equal(unavailable.operator_ready, false, 'no readiness is never operator-ready: ')
assert.equal(unavailable.authoritative, false, 'no readiness is not authoritative: ')
assert.equal(unavailable.display, 'READINESS UNAVAILABLE')
assert.equal(unavailable.evidence.length, 0)
assert.ok(unavailable.reasons.length === 1 && /did not return a readiness state/.test(unavailable.reasons[0]), 'reason names the absence: ')

// Client evidence is carried as evidence only — it never selects a state, empty or not.
const withEvidence = readinessFromPlan({}, ['legs', 'PM memo'])
assert.equal(withEvidence.state, READINESS_UNAVAILABLE)
assert.equal(withEvidence.operator_ready, false)
assert.equal(withEvidence.evidence.join('|'), 'legs|PM memo')
assert.equal(readinessEvidenceLine(withEvidence), 'Client checks also flag: legs, PM memo.')
assert.ok(/does not make the plan operator-ready/.test(readinessEvidenceLine(unavailable) ?? ''), 'empty evidence is explained, not upgraded: ')

// ── Server readiness is authoritative and is copied, not invented. ──
const server = readinessFromPlan({
  readiness: { state: 'ANALYTICS_READY', reasons: ['oversight pending'], operator_ready: false, display: 'ANALYTICS READY — OVERSIGHT PENDING' },
}, ['legs'])
assert.equal(server.state, 'ANALYTICS_READY')
assert.equal(server.operator_ready, false)
assert.equal(server.authoritative, true)
assert.equal(server.display, 'ANALYTICS READY — OVERSIGHT PENDING')
assert.equal(server.reasons.join('|'), 'oversight pending')
assert.equal(server.evidence.length, 0, 'client evidence is not shown beside an authoritative server state: ')
assert.equal(readinessEvidenceLine(server), null)

const ready = readinessFromPlan({ readiness: { state: 'OPERATOR_READY', operator_ready: true } })
assert.equal(ready.operator_ready, true)
assert.equal(ready.display, 'OPERATOR READY', 'missing display is humanised, not invented: ')

// Strict typing: a truthy non-boolean is not operator-ready, and a non-string state is not a state.
for (const operator_ready of ['yes', 1, {}, []]) {
  assert.equal(readinessFromPlan({ readiness: { state: 'OPERATOR_READY', operator_ready } }).operator_ready, false, `operator_ready=${JSON.stringify(operator_ready)} must be strict false: `)
}
for (const state of ['', '   ', null, undefined, 7, {}]) {
  const r = readinessFromPlan({ readiness: { state, operator_ready: true } })
  assert.equal(r.state, READINESS_UNAVAILABLE, `state=${JSON.stringify(state)} must be unavailable: `)
  assert.equal(r.operator_ready, false)
}
assert.equal(readinessFromPlan({ readiness: { state: 'DATA_INCOMPLETE', reasons: 'legs' } }).reasons.length, 0, 'a non-array reasons field is not iterated: ')
assert.equal(readinessFromPlan({ readiness: { state: 'DATA_INCOMPLETE', reasons: ['legs', 3, null, ' '] } }).reasons.join('|'), 'legs', 'non-string reasons are dropped: ')
assert.equal(readinessFromPlan(null).state, READINESS_UNAVAILABLE)

// ── The next action always names what to do, and never implies an order. ──
assert.ok(/Readiness unavailable .* reload/.test(nextReadinessAction(unavailable)), 'unavailable action says reload: ')
assert.equal(nextReadinessAction(readinessFromPlan({ readiness: { state: 'QUOTES_STALE', operator_ready: false } })), 'Refresh quotes')
assert.equal(nextReadinessAction(readinessFromPlan({ readiness: { state: 'DATA_INCOMPLETE', reasons: ['fresh quotes'], operator_ready: false } })), 'Refresh quotes')
assert.equal(nextReadinessAction(readinessFromPlan({ readiness: { state: 'OVERSIGHT_PENDING', operator_ready: false } })), 'Run oversight')
assert.equal(nextReadinessAction(readinessFromPlan({ readiness: { state: 'OVERSIGHT_FAILED', operator_ready: false } })), 'Review oversight findings')
assert.equal(nextReadinessAction(readinessFromPlan({ readiness: { state: 'DATA_INCOMPLETE', reasons: ['legs'], operator_ready: false } })), 'Resolve: legs')
assert.equal(nextReadinessAction(ready), 'Review comparison, approve plan for operator implementation review')
assert.equal(nextReadinessAction(readinessFromPlan({ readiness: { state: 'OPERATOR_LOCKED', operator_ready: false } })), 'Review plan readiness')
for (const r of [unavailable, server, ready]) {
  assert.ok(!/place|submit|buy|sell|share/i.test(nextReadinessAction(r)), 'no action implies an order: ')
}

console.log('redeploy readiness (fail-closed) contract: passed')
